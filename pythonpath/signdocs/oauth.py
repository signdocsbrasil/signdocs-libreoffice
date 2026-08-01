# SPDX-License-Identifier: MPL-2.0
"""
Sign-in against the SignDocs account, RFC 8252 native-app style.

The user authenticates on **login.signdocs.com.br** — Cognito managed login on
our own domain — and the extension receives an ID token. That token identifies
the person; it grants no API access on its own. Everything the extension then
calls goes to the `/libreoffice/*` add-on tier, which holds the API credential
server-side in Secrets Manager. Nothing secret ships in this file.

Differences from the SignDocs OAuth broker this module used to target, all of
which simplify it:

* **No Dynamic Client Registration.** Cognito implements no RFC 7591, so the
  client id is fixed and shipped. That is safe precisely because it is a public
  client with no secret — the id is not a credential.
* **Every loopback port is pre-registered** on the app client, so the exact
  redirect URI still matches whichever port turns out to be free. Cognito
  honours `http://127.0.0.1:<port>/callback` despite the documentation
  suggesting `http://localhost` is the only HTTP exception; that was verified
  against a real managed-login domain rather than inferred.
* **Refresh tokens are not rotated.** Our broker replaced the refresh token on
  every use, so the new one had to reach disk before the new access token was
  used. Cognito reuses it and simply omits `refresh_token` from the refresh
  response, so the rule here is the opposite: never overwrite a stored token
  with an absent one.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from signdocs import config
from signdocs.httpclient import HttpError, NetworkError, post_form

#: How long to wait for the user to finish signing in.
CONSENT_TIMEOUT = 300

#: Refresh this many seconds before nominal expiry so a request cannot start
#: with a token that expires mid-flight.
EXPIRY_SKEW = 60

#: ID tokens live in memory only, keyed by stage. The cache has a real expiry,
#: so it cannot go stale.
_tokens = {}


class NotConnected(Exception):
    """No usable credentials. The caller should offer to sign in."""


class AuthorizationFailed(Exception):
    """The user cancelled, or the callback never arrived."""


class NoFreePort(Exception):
    """Every registered loopback port was busy."""


# ---------------------------------------------------------------- PKCE bits
def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_verifier():
    """43-character URL-safe verifier, the RFC 7636 minimum length."""
    return secrets.token_urlsafe(32)


def challenge_for(verifier):
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def pack_state(nonce):
    return _b64url(json.dumps({"n": nonce}).encode("utf-8"))


def unpack_state(packed):
    padding = "=" * (-len(packed) % 4)
    value = json.loads(base64.urlsafe_b64decode(packed + padding).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("state is not an object")
    return value


# ------------------------------------------------------- loopback listener
_CLOSE_PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>SignDocs Brasil</title>
<style>
 body{font:16px/1.5 system-ui,sans-serif;margin:0;display:flex;height:100vh;
      align-items:center;justify-content:center;background:#f6f7f9;color:#1f2933}
 .card{background:#fff;padding:2rem 2.5rem;border-radius:12px;text-align:center;
       box-shadow:0 1px 3px rgba(0,0,0,.12)}
 @media (prefers-color-scheme:dark){body{background:#12161c;color:#e6e9ee}
       .card{background:#1b2029;box-shadow:none}}
</style></head>
<body><div class="card"><p><strong>%(headline)s</strong></p>
<p>Você já pode fechar esta janela e voltar ao LibreOffice.</p></div></body></html>
"""


class _CallbackHandler(BaseHTTPRequestHandler):
    server_version = "SignDocsBrasil"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API name
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != config.LOOPBACK_PATH:
            # Browsers ask for /favicon.ico on the way past; that must not be
            # mistaken for the callback and end the wait with no code.
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        self.server.signdocs_result = {k: v[0] for k, v in params.items() if v}

        headline = (
            "Não foi possível entrar."
            if "error" in self.server.signdocs_result
            else "Login concluído."
        )
        body = (_CLOSE_PAGE % {"headline": headline}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # The default writes to stderr, which on Windows means a console
        # window nobody asked for.
        pass


def _bind_loopback():
    """
    Bind the first free registered port.

    Bound to 127.0.0.1 explicitly, never 0.0.0.0: this socket briefly receives
    an authorization code and nothing off-machine has any business reaching it.
    """
    last = None
    for port in config.LOOPBACK_PORTS:
        try:
            server = HTTPServer((config.LOOPBACK_HOST, port), _CallbackHandler)
        except OSError as exc:
            last = exc
            continue
        server.signdocs_result = None
        server.timeout = 1
        return server, port
    raise NoFreePort(
        "Nenhuma porta local livre entre %d e %d (%s)."
        % (config.LOOPBACK_PORTS[0], config.LOOPBACK_PORTS[-1], last)
    )


def _await_callback(server, timeout, now=time.time):
    deadline = now() + timeout
    while server.signdocs_result is None and now() < deadline:
        server.handle_request()
    return server.signdocs_result


# ------------------------------------------------------------------ tokens
def authorize_url(redirect_uri, challenge, state, lang=None):
    """
    Build the managed-login URL.

    `lang` localises the sign-in page. A Brazilian user meeting an English
    login form on their way into a Brazilian e-signature product is a jarring
    first impression, and it is one query parameter to avoid.
    """
    params = {
        "response_type": "code",
        "client_id": config.COGNITO["client_id"],
        "redirect_uri": redirect_uri,
        "scope": " ".join(config.COGNITO["scopes"]),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "lang": lang or config.DEFAULT_LOGIN_LANG,
    }
    return config.COGNITO["domain"] + "/oauth2/authorize?" + urllib.parse.urlencode(params)


def _remember(store, stage, tokens):
    """
    Cache the ID token and persist the refresh token.

    The add-on tier verifies an **ID** token — it is the only one carrying the
    email claim — so that is what gets cached and sent.

    Cognito omits `refresh_token` from a refresh response because it does not
    rotate them. Writing that absence through would delete a perfectly good
    token and force a fresh sign-in on the next launch.
    """
    refresh = tokens.get("refresh_token")
    if refresh:
        try:
            store.set(config.stage_key("refresh_token", stage), refresh)
        except Exception:
            # A read-only profile costs the user their session at next launch,
            # but discarding a working token now helps nobody.
            pass

    id_token = tokens.get("id_token")
    if not id_token:
        raise AuthorizationFailed("O servidor não devolveu um id_token.")
    expires_in = tokens.get("expires_in") or 0
    _tokens[stage] = (id_token, time.time() + max(0, expires_in - EXPIRY_SKEW))
    return id_token


def _forget(store, stage):
    _tokens.pop(stage, None)
    try:
        store.delete(config.stage_key("refresh_token", stage))
    except Exception:
        pass


def connect(store, stage=None, open_browser=None, timeout=CONSENT_TIMEOUT,
            lang=None):
    """
    Run the interactive sign-in. Blocking — worker thread only, never the
    office's dispatch thread.

    `lang` should be the office's UI language so the login page matches the
    rest of the application; the caller in ui/ passes it.
    """
    stage = stage or config.current_stage(store)
    open_browser = open_browser or webbrowser.open

    server, port = _bind_loopback()
    try:
        redirect_uri = config.redirect_uri(port)
        verifier = new_verifier()
        nonce = secrets.token_urlsafe(16)
        state = pack_state(nonce)

        open_browser(
            authorize_url(redirect_uri, challenge_for(verifier), state, lang))
        result = _await_callback(server, timeout)
    finally:
        server.server_close()

    if result is None:
        raise AuthorizationFailed(
            "O login não foi concluído dentro de %d segundos." % timeout
        )

    # Check the nonce before anything else: an unsolicited request to the
    # loopback port must not be able to feed us a code.
    try:
        returned = unpack_state(result.get("state", ""))
    except Exception:
        raise AuthorizationFailed("Resposta de login inválida.")
    if returned.get("n") != nonce:
        raise AuthorizationFailed("Resposta de login inválida.")

    if result.get("error"):
        raise AuthorizationFailed(result.get("error_description") or result["error"])
    code = result.get("code")
    if not code:
        raise AuthorizationFailed("Resposta de login inválida.")

    tokens = post_form(config.COGNITO["domain"] + "/oauth2/token", {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": config.COGNITO["client_id"],
        "code_verifier": verifier,
    })
    return _remember(store, stage, tokens or {})


def refresh(store, stage=None):
    stage = stage or config.current_stage(store)

    try:
        token = store.get(config.stage_key("refresh_token", stage))
    except Exception:
        token = None
    if not token:
        raise NotConnected("Não conectado.")

    try:
        tokens = post_form(config.COGNITO["domain"] + "/oauth2/token", {
            "grant_type": "refresh_token",
            "refresh_token": token,
            "client_id": config.COGNITO["client_id"],
        })
    except HttpError:
        # Rejected by Cognito, so it is dead — keeping it would reproduce the
        # same failure on every later call.
        _forget(store, stage)
        raise NotConnected("Sessão expirada. Entre novamente.")
    except NetworkError:
        # Offline is not unauthorised: the token may be perfectly good, so do
        # NOT discard it.
        raise

    return _remember(store, stage, tokens or {})


def bearer_token(store, stage=None):
    """
    A valid ID token for the add-on API, refreshing when the cached one is
    stale. Named for what it is used as, not for Cognito's `access_token` —
    which carries no email and would be rejected by the identity resolver.
    """
    stage = stage or config.current_stage(store)
    cached = _tokens.get(stage)
    if cached and cached[1] > time.time():
        return cached[0]
    return refresh(store, stage)


def is_connected(store, stage=None):
    stage = stage or config.current_stage(store)
    if _tokens.get(stage):
        return True
    try:
        return bool(store.get(config.stage_key("refresh_token", stage)))
    except Exception:
        return False


def disconnect(store, stage=None):
    _forget(store, stage or config.current_stage(store))
