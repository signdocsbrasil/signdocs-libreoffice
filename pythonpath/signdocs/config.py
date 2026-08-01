# SPDX-License-Identifier: MPL-2.0
"""
Endpoints, storage keys and limits.

The extension ships pointing at production. Homologação is reachable only by
setting the stage in the extension's own Configurações dialog — deliberately
not auto-detected, because a desktop install has no reliable signal about
which SignDocs environment its operator intends.
"""

STAGES = {
    "prod": {
        "api": "https://libreoffice-api.signdocs.com.br",
    },
    "hml": {
        "api": "https://libreoffice-api-hml.signdocs.com.br",
    },
}

DEFAULT_STAGE = "prod"

#: Path prefix every add-on route sits under.
API_PREFIX = "/libreoffice"

#: Sign-in, via Cognito managed login on our own domain.
#:
#: Stage-independent on purpose: **one Cognito pool serves both prod and
#: hml**, so the login host and app client are the same either way. Only the
#: add-on API differs per stage. Do not "helpfully" add a per-stage login
#: host — there isn't one.
COGNITO = {
    "domain": "https://login.signdocs.com.br",
    # A public client. This id is not a credential — the client has no secret,
    # which is what makes shipping it in an extension safe. Cognito implements
    # no RFC 7591, so unlike the previous broker there is nothing to register
    # at runtime.
    "client_id": "7eufhdc7d2khb857n9amvpaidt",
    # `email` is the one that matters: the add-on tier reads the email claim
    # from the ID token to establish identity, quota and ownership.
    "scopes": ("openid", "email", "profile"),
}

STORAGE = {
    "stage": "signdocs.stage",
    # Per-stage suffix so switching to HML for a test cannot clobber the
    # production session.
    "refresh_token": "signdocs.refreshToken.",
    "sends": "signdocs.sends.",
    "sender_email": "signdocs.senderEmail",
    "profile": "signdocs.profile",
}

#: The API rejects a base64 document body over 10MB; fail before the upload.
MAX_BASE64_BYTES = 10 * 1024 * 1024

#: Loopback ports offered for the RFC 8252 redirect.
#:
#: All eight are pre-registered as callback URLs on the Cognito app client,
#: because the redirect URI is exact-matched and we cannot know which port
#: will be free. Cognito honours the `127.0.0.1` literal despite its docs
#: suggesting `http://localhost` is the only HTTP exception — verified against
#: a real managed-login domain, with an unregistered URI as a control.
LOOPBACK_PORTS = (8712, 8713, 8714, 8715, 8716, 8717, 8718, 8719)

LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PATH = "/callback"


def redirect_uri(port):
    return "http://{0}:{1}{2}".format(LOOPBACK_HOST, port, LOOPBACK_PATH)


def redirect_uris():
    """Every candidate. Must match the app client's registered list exactly."""
    return [redirect_uri(port) for port in LOOPBACK_PORTS]


def current_stage(store):
    try:
        return "hml" if store.get(STORAGE["stage"]) == "hml" else DEFAULT_STAGE
    except Exception:
        # An unreadable profile must not take the extension down, and
        # production is the safe default.
        return DEFAULT_STAGE


def set_stage(store, stage):
    try:
        store.set(STORAGE["stage"], "hml" if stage == "hml" else DEFAULT_STAGE)
    except Exception:
        # Non-fatal: the session just won't remember the choice.
        pass


def endpoints(store):
    return STAGES[current_stage(store)]


def api_base(store, stage=None):
    """Base URL for the add-on tier, including the /libreoffice prefix."""
    return STAGES[stage or current_stage(store)]["api"] + API_PREFIX


def stage_key(name, stage):
    """Storage key for a per-stage value, e.g. signdocs.refreshToken.prod."""
    return STORAGE[name] + stage
