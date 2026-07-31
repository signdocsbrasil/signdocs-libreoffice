# SPDX-License-Identifier: MPL-2.0
"""
OAuth 2.1 authorization-code + PKCE, RFC 8252 native-app style.

The extension is a **public client**: it ships no secret and cannot keep one.
Instead it registers itself once via RFC 7591 Dynamic Client Registration,
then runs the authorization-code flow with PKCE S256 against a transient
loopback listener.

Three properties of the authorization server shape this file, and none of them
are guesses — they are what `external-api/src/handlers/oauth/` actually does:

* `register.ts` accepts loopback redirect URIs over http. That is what lets a
  desktop app skip the CDN-hosted callback page the ONLYOFFICE plugin needs.
* `authorize.ts` **exact-matches the redirect URI including the port**. RFC 8252
  §7.3 port-agnostic loopback matching is not implemented, so every candidate
  port is registered up front in one DCR call and we bind whichever is free.
  Registering per launch instead would grow OAUTH_DCR# records without bound.
* `token.ts` rotates the refresh token on every use and deletes the presented
  one immediately. Persist the new one *before* using the new access token, or
  a crash in between logs the user out for good.
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
from signdocs.httpclient import HttpError, NetworkError, get_json, post_form, post_json

#: How long to wait for the user to finish consenting. Matches the 300s
#: single-use lifetime of the authorization code — waiting longer would only
#: collect a code the server has already expired.
CONSENT_TIMEOUT = 300

#: Refresh this many seconds before nominal expiry, so a request cannot start
#: with a token that expires mid-flight. Access tokens live 900s.
EXPIRY_SKEW = 60

CLIENT_NAME = "SignDocs Brasil para LibreOffice"

#: Access tokens are held in memory only, never written to the profile, keyed
#: by stage. This cache has a real expiry (unlike the module-scope secrets
#: cache in external-api that needed a manual bust), so it cannot go stale.
_access_tokens = {}


class NotConnected(Exception):
    """No usable credentials. The caller should offer to connect."""


class AuthorizationFailed(Exception):
    """The user denied consent, or the callback never arrived."""


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
    raw = base64.urlsafe_b64decode(packed + padding)
    value = json.loads(raw.decode("utf-8"))
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
            # Browsers cheerfully ask for /favicon.ico on the way past; that
            # must not be mistaken for the callback.
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        self.server.signdocs_result = {k: v[0] for k, v in params.items() if v}

        headline = (
            "Autorização negada."
            if "error" in self.server.signdocs_result
            else "Autorização concluída."
        )
        body = (_CLOSE_PAGE % {"headline": headline}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # The default implementation writes to stderr, which on Windows means
        # a console window nobody asked for.
        pass


def _bind_loopback():
    """
    Bind the first free registered port.

    Bound to 127.0.0.1 explicitly, never 0.0.0.0: this socket briefly receives
    an authorization code, and nothing outside the machine has any business
    reaching it.
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


# ------------------------------------------------------------ registration
def ensure_client_id(store, stage=None, endpoints=None):
    """
    Register once per stage and cache the id forever.

    The client id is public by construction — the server issues no secret and
    advertises `token_endpoint_auth_methods_supported: ["none"]` — so caching
    it in the profile costs nothing.
    """
    stage = stage or config.current_stage(store)
    endpoints = endpoints or config.STAGES[stage]
    key = config.stage_key("client_id", stage)

    try:
        existing = store.get(key)
    except Exception:
        existing = None
    if existing:
        return existing

    payload = post_json(
        endpoints["auth"] + "/oauth2/register",
        {
            "client_name": CLIENT_NAME,
            # Every candidate port, because the server exact-matches the
            # redirect URI and we cannot know which one will be free.
            "redirect_uris": config.redirect_uris(),
            "scope": " ".join(config.SCOPES),
        },
    )
    client_id = (payload or {}).get("client_id")
    if not client_id:
        raise AuthorizationFailed("O servidor não devolveu um client_id.")

    try:
        store.set(key, client_id)
    except Exception:
        # Losing the cache means re-registering next launch. Annoying, not
        # fatal, and not worth failing a connection the user asked for.
        pass
    return client_id


def authorize_url(endpoints, client_id, redirect_uri, challenge, state):
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(config.SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return endpoints["auth"] + "/oauth2/authorize?" + query


# ------------------------------------------------------------------ tokens
def _remember(store, stage, tokens):
    """
    Persist the refresh token, then arm the access token.

    Order matters and is the whole point: the server has already invalidated
    the refresh token we presented, so if the process dies between here and
    the next launch without the replacement on disk, the user is logged out
    permanently.
    """
    refresh = tokens.get("refresh_token")
    if refresh:
        try:
            store.set(config.stage_key("refresh_token", stage), refresh)
        except Exception:
            # A read-only profile costs the user their session at next launch,
            # but throwing away a working access token now helps nobody.
            pass

    access = tokens.get("access_token")
    if not access:
        raise AuthorizationFailed("O servidor não devolveu um access_token.")
    expires_in = tokens.get("expires_in") or 0
    _access_tokens[stage] = (access, time.time() + max(0, expires_in - EXPIRY_SKEW))
    return access


def _forget(store, stage):
    _access_tokens.pop(stage, None)
    try:
        store.delete(config.stage_key("refresh_token", stage))
    except Exception:
        pass


def connect(store, stage=None, open_browser=None, timeout=CONSENT_TIMEOUT):
    """
    Run the full interactive flow. Blocking — call it from a worker thread,
    never from the office's dispatch thread.
    """
    stage = stage or config.current_stage(store)
    endpoints = config.STAGES[stage]
    open_browser = open_browser or webbrowser.open

    client_id = ensure_client_id(store, stage, endpoints)
    server, port = _bind_loopback()
    try:
        redirect_uri = config.redirect_uri(port)
        verifier = new_verifier()
        nonce = secrets.token_urlsafe(16)
        state = pack_state(nonce)

        open_browser(authorize_url(
            endpoints, client_id, redirect_uri, challenge_for(verifier), state
        ))

        result = _await_callback(server, timeout)
    finally:
        server.server_close()

    if result is None:
        raise AuthorizationFailed(
            "A autorização não foi concluída dentro de %d segundos." % timeout
        )

    # Check the nonce before looking at anything else: an unsolicited request
    # to the loopback port must not be able to feed us a code.
    try:
        returned = unpack_state(result.get("state", ""))
    except Exception:
        raise AuthorizationFailed("Resposta de autorização inválida.")
    if returned.get("n") != nonce:
        raise AuthorizationFailed("Resposta de autorização inválida.")

    if result.get("error"):
        raise AuthorizationFailed(
            result.get("error_description") or result["error"]
        )
    code = result.get("code")
    if not code:
        raise AuthorizationFailed("Resposta de autorização inválida.")

    tokens = post_form(endpoints["auth"] + "/oauth2/token", {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    })
    return _remember(store, stage, tokens or {})


def refresh(store, stage=None):
    stage = stage or config.current_stage(store)
    endpoints = config.STAGES[stage]

    try:
        token = store.get(config.stage_key("refresh_token", stage))
    except Exception:
        token = None
    if not token:
        raise NotConnected("Não conectado.")

    client_id = None
    try:
        client_id = store.get(config.stage_key("client_id", stage))
    except Exception:
        pass
    if not client_id:
        raise NotConnected("Registro do cliente perdido.")

    try:
        tokens = post_form(endpoints["auth"] + "/oauth2/token", {
            "grant_type": "refresh_token",
            "refresh_token": token,
            "client_id": client_id,
        })
    except HttpError:
        # The server rejected it, so it is dead — keeping it would only
        # produce the same failure on every later call.
        _forget(store, stage)
        raise NotConnected("Sessão expirada. Conecte-se novamente.")
    except NetworkError:
        # Offline is not the same as unauthorised: the token may still be
        # perfectly good, so do NOT discard it.
        raise

    return _remember(store, stage, tokens or {})


def access_token(store, stage=None):
    """Valid access token, refreshing when the cached one is stale."""
    stage = stage or config.current_stage(store)
    cached = _access_tokens.get(stage)
    if cached and cached[1] > time.time():
        return cached[0]
    return refresh(store, stage)


def is_connected(store, stage=None):
    stage = stage or config.current_stage(store)
    if _access_tokens.get(stage):
        return True
    try:
        return bool(store.get(config.stage_key("refresh_token", stage)))
    except Exception:
        return False


def disconnect(store, stage=None):
    _forget(store, stage or config.current_stage(store))


def discover(endpoints):
    """RFC 8414 metadata. Used by the settings dialog's connectivity check."""
    return get_json(endpoints["auth"] + "/.well-known/oauth-authorization-server")
