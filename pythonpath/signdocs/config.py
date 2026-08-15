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
        "login": "https://login.signdocs.com.br",
        # Public client on the production pool (us-east-1_7wz2lnW8F). Not a
        # credential: the client has no secret, which is what makes shipping
        # it in an extension safe.
        "client_id": "7eufhdc7d2khb857n9amvpaidt",
    },
    "hml": {
        "api": "https://libreoffice-api-hml.signdocs.com.br",
        "login": "https://login-hml.signdocs.com.br",
        # Public client on the homologação pool (us-east-1_smgTkPiS3).
        "client_id": "trmc0ascars41ln0o9s7fhf4i",
    },
}

DEFAULT_STAGE = "prod"

#: Path prefix every add-on route sits under.
API_PREFIX = "/libreoffice"

#: Sign-in, via Cognito managed login on our own domain.
#:
#: **Per stage, and it has to be.** backend-sign-docs deploys a separate
#: Cognito pool per Amplify branch — master/prod is us-east-1_7wz2lnW8F and
#: dev/hml is us-east-1_smgTkPiS3, with entirely separate user populations.
#: Pointing both stages at one pool would let production credentials open
#: homologação data and the reverse, which is precisely the separation staging
#: exists to provide.
#:
#: (The SSM parameter /signdocs/hml/cognito-user-pool-id currently names the
#: PROD pool. That governs external-api's admin auth, not this, but it is the
#: reason the shared-pool assumption looked correct at first glance.)
SCOPES = ("openid", "email", "profile")

#: LibreOffice UI language -> Cognito managed-login `lang` code.
#:
#: Note **pt-BR**, not `pt`: Cognito silently ignores `pt` and falls back to
#: English, which is the sort of thing that looks like the feature simply not
#: working. Verified against the live login page — `lang=pt-BR` renders
#: "Senha", `lang=pt` renders "Enter password".
#:
#: Cognito also drops a `lang` cookie after the first request, so the choice
#: persists in that browser until it is changed or cookies are cleared.
LOGIN_LANG = {
    "pt": "pt-BR",
    "en": "en",
    "es": "es",
}
DEFAULT_LOGIN_LANG = "pt-BR"

STORAGE = {
    "stage": "signdocs.stage",
    # Per-stage suffix so switching to HML for a test cannot clobber the
    # production session.
    "refresh_token": "signdocs.refreshToken.",
    "sends": "signdocs.sends.",
    # Retired: the sender is the signed-in account, read from the ID token.
    # The server sets `owner` from the verified identity and ignores the
    # client, so a stored preference could only ever disagree with reality.
    "profile": "signdocs.profile",
}

#: The API rejects a base64 document body over 10MB; fail before the upload.
MAX_BASE64_BYTES = 10 * 1024 * 1024

#: How long a signer has, in hours. Mirrors DEFAULT_SIGNING_WINDOW_MINUTES in
#: external-api/src/config/signing-window.ts (4320 minutes). Copied rather than
#: fetched — the create response does not carry it — so a test asserts the two
#: agree, the same way the order-forcing rule is pinned to the server's list.
#: The consumer app's window is 10 days and is NOT this number.
SIGNING_WINDOW_HOURS = 72

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
