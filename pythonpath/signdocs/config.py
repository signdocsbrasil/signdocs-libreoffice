# SPDX-License-Identifier: MPL-2.0
"""
Endpoints, storage keys and limits.

The extension ships pointing at production. HML is reachable only by setting
the stage in the extension's own settings dialog — deliberately not
auto-detected, because a desktop install has no reliable signal about which
SignDocs environment its operator intends.
"""

STAGES = {
    "prod": {
        "api": "https://api.signdocs.com.br",
        "auth": "https://auth.signdocs.com.br",
    },
    "hml": {
        # Note the dash: api-hml, not api.hml.
        "api": "https://api-hml.signdocs.com.br",
        "auth": "https://auth-hml.signdocs.com.br",
    },
}

DEFAULT_STAGE = "prod"

STORAGE = {
    "stage": "signdocs.stage",
    # Per-stage suffix, so switching to HML for a test cannot clobber the
    # production client registration or its refresh token.
    "client_id": "signdocs.clientId.",
    "refresh_token": "signdocs.refreshToken.",
    "sends": "signdocs.sends.",
    "sender_email": "signdocs.senderEmail",
    "profile": "signdocs.profile",
}

#: Scopes the extension actually exercises. The server offers six; asking for
#: more than we use gets refused on principle.
SCOPES = ("transactions:read", "transactions:write", "steps:write")

#: The API rejects a base64 document body over 10MB; fail before the upload.
MAX_BASE64_BYTES = 10 * 1024 * 1024

#: Loopback ports offered for the RFC 8252 redirect.
#:
#: The authorization server exact-matches the redirect URI *including the
#: port* — RFC 8252 §7.3 port-agnostic matching is not implemented — so all of
#: these get registered in a single Dynamic Client Registration call and
#: whichever is free at connect time is used. Registering per launch instead
#: would grow OAUTH_DCR# records without bound.
LOOPBACK_PORTS = (8712, 8713, 8714, 8715, 8716, 8717, 8718, 8719)

#: Always the literal 127.0.0.1. `[::1]` is not in the authorization server's
#: loopback check and would be rejected as non-https.
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PATH = "/callback"


def redirect_uri(port):
    return "http://{0}:{1}{2}".format(LOOPBACK_HOST, port, LOOPBACK_PATH)


def redirect_uris():
    """Every candidate, for the one-shot client registration."""
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


def stage_key(name, stage):
    """Storage key for a per-stage value, e.g. signdocs.clientId.prod."""
    return STORAGE[name] + stage
