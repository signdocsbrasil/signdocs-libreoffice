# SPDX-License-Identifier: MPL-2.0
"""
Sign-in against Cognito managed login.

Two behaviours are worth more than the rest, and both are asserted directly:

* the **ID** token is what gets cached and presented, not the access token —
  only the ID token carries the email claim the add-on tier resolves identity
  from, so caching the wrong one fails at every call site with a confusing
  message;
* a refresh that returns **no** `refresh_token` must leave the stored one
  alone. Cognito does not rotate refresh tokens and simply omits the field,
  so writing that absence through would delete a working token and force a
  fresh sign-in. This is the exact inverse of the previous broker's rule, and
  the most likely thing to get wrong when porting.

The loopback leg runs against a real bound socket rather than a mock, so the
handler, port selection and state check are exercised as shipped.
"""

import base64
import hashlib
import json
import threading
import urllib.parse
import urllib.request

import pytest

from signdocs import config, oauth
from signdocs.httpclient import HttpError, NetworkError
from signdocs.store import JsonStore


@pytest.fixture(autouse=True)
def _clear_token_cache():
    oauth._tokens.clear()
    yield
    oauth._tokens.clear()


@pytest.fixture
def store():
    return JsonStore()


def tokens(**over):
    payload = {
        "id_token": "id-1",
        "access_token": "at-1",
        "refresh_token": "rt-1",
        "expires_in": 3600,
    }
    payload.update(over)
    return payload


# ------------------------------------------------------------------- PKCE
def test_verifier_meets_rfc7636_length():
    verifier = oauth.new_verifier()
    assert 43 <= len(verifier) <= 128
    assert oauth.new_verifier() != verifier


def test_challenge_is_unpadded_base64url_sha256():
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(b"abc123").digest()
    ).decode().rstrip("=")
    assert oauth.challenge_for("abc123") == expected
    assert "=" not in oauth.challenge_for("abc123")


def test_state_round_trips():
    packed = oauth.pack_state("nonce-1")
    assert oauth.unpack_state(packed)["n"] == "nonce-1"
    assert "=" not in packed


def test_unpack_state_rejects_a_non_object():
    packed = base64.urlsafe_b64encode(json.dumps([1, 2]).encode()).decode().rstrip("=")
    with pytest.raises(ValueError):
        oauth.unpack_state(packed)


# -------------------------------------------------------- authorize URL
def test_authorize_url_targets_our_own_login_domain():
    url = oauth.authorize_url("prod", "http://127.0.0.1:8712/callback", "chal", "st")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    # Users type their password here, so it must be our hostname and not an
    # amazoncognito.com one.
    assert url.startswith("https://login.signdocs.com.br/oauth2/authorize?")
    assert query["client_id"] == [config.STAGES["prod"]["client_id"]]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8712/callback"]
    assert query["code_challenge_method"] == ["S256"]
    # `email` is the claim the add-on tier resolves identity from.
    assert "email" in query["scope"][0].split()
    assert "openid" in query["scope"][0].split()


def test_authorize_url_localises_the_login_page():
    import urllib.parse as up
    q = up.parse_qs(up.urlparse(
        oauth.authorize_url("prod", "http://127.0.0.1:8712/callback", "c", "s")).query)
    # Defaults to Brazilian Portuguese rather than Cognito's English default.
    assert q["lang"] == ["pt-BR"]

    q = up.parse_qs(up.urlparse(
        oauth.authorize_url("prod", "http://127.0.0.1:8712/callback", "c", "s", "en")).query)
    assert q["lang"] == ["en"]


def test_connect_passes_the_language_through(monkeypatch, store):
    seen = {}

    def capture(url):
        import urllib.parse as up
        seen["lang"] = up.parse_qs(up.urlparse(url).query).get("lang")
        _drive_browser(url)

    monkeypatch.setattr(oauth, "post_form", lambda *a, **k: tokens())
    oauth.connect(store, "prod", open_browser=capture, timeout=15, lang="es")
    assert seen["lang"] == ["es"]


def test_each_stage_signs_in_against_its_own_pool():
    prod = oauth.authorize_url("prod", "http://127.0.0.1:8712/callback", "c", "s")
    hml = oauth.authorize_url("hml", "http://127.0.0.1:8712/callback", "c", "s")
    assert prod.startswith("https://login.signdocs.com.br/")
    assert hml.startswith("https://login-hml.signdocs.com.br/")
    # A production credential must not open homologação data, nor the reverse.
    assert config.STAGES["prod"]["client_id"] not in hml


# ------------------------------------------------------------- loopback
def test_bind_loopback_listens_only_on_127_0_0_1():
    server, port = oauth._bind_loopback()
    try:
        assert port in config.LOOPBACK_PORTS
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_bind_loopback_skips_a_busy_port():
    first, first_port = oauth._bind_loopback()
    try:
        second, second_port = oauth._bind_loopback()
        try:
            assert second_port != first_port
        finally:
            second.server_close()
    finally:
        first.server_close()


def _drive_browser(url, extra=None):
    """Stand in for the user's browser: fetch the redirect URI with a result."""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    redirect = query["redirect_uri"][0]
    params = {"state": query["state"][0]}
    params.update(extra or {"code": "auth-code-1"})

    def go():
        # Browsers ask for this on the way past; it must not be mistaken for
        # the callback.
        try:
            urllib.request.urlopen(redirect.rsplit("/", 1)[0] + "/favicon.ico", timeout=5)
        except Exception:
            pass
        urllib.request.urlopen(redirect + "?" + urllib.parse.urlencode(params), timeout=5)

    threading.Thread(target=go, daemon=True).start()


def test_connect_completes_against_a_real_loopback_socket(monkeypatch, store):
    exchanged = {}

    def fake_post_form(url, fields, headers=None, timeout=None):
        exchanged["url"] = url
        exchanged.update(fields)
        return tokens()

    monkeypatch.setattr(oauth, "post_form", fake_post_form)

    token = oauth.connect(store, "prod", open_browser=_drive_browser, timeout=15)

    # The ID token, not the access token.
    assert token == "id-1"
    assert exchanged["url"] == "https://login.signdocs.com.br/oauth2/token"
    assert exchanged["grant_type"] == "authorization_code"
    assert exchanged["code"] == "auth-code-1"
    assert exchanged["client_id"] == config.STAGES["prod"]["client_id"]
    # PKCE: the verifier, not the challenge, goes to the token endpoint.
    assert len(exchanged["code_verifier"]) >= 43
    assert exchanged["redirect_uri"].startswith("http://127.0.0.1:")
    # No client_secret: this is a public client and cannot hold one.
    assert "client_secret" not in exchanged
    assert store.get(config.stage_key("refresh_token", "prod")) == "rt-1"


def test_connect_rejects_a_mismatched_state(monkeypatch, store):
    monkeypatch.setattr(oauth, "post_form",
                        lambda *a, **k: pytest.fail("must not reach the token endpoint"))

    def hostile_browser(url):
        _drive_browser(
            url.replace("state=", "state=" + oauth.pack_state("wrong") + "&ignored="),
            {"code": "attacker-code"},
        )

    with pytest.raises(oauth.AuthorizationFailed):
        oauth.connect(store, "prod", open_browser=hostile_browser, timeout=15)


def test_connect_surfaces_a_cancelled_login(monkeypatch, store):
    monkeypatch.setattr(oauth, "post_form",
                        lambda *a, **k: pytest.fail("must not reach the token endpoint"))

    def denying_browser(url):
        _drive_browser(url, {"error": "access_denied",
                             "error_description": "Login cancelado."})

    with pytest.raises(oauth.AuthorizationFailed) as excinfo:
        oauth.connect(store, "prod", open_browser=denying_browser, timeout=15)
    assert "cancelado" in str(excinfo.value)


def test_connect_times_out_without_a_callback(monkeypatch, store):
    monkeypatch.setattr(oauth, "post_form", lambda *a, **k: pytest.fail("no code"))
    with pytest.raises(oauth.AuthorizationFailed):
        oauth.connect(store, "prod", open_browser=lambda url: None, timeout=1)


def test_connect_requires_an_id_token(monkeypatch, store):
    # An access token alone is useless: it carries no email claim, so the
    # add-on tier would reject every subsequent call.
    monkeypatch.setattr(oauth, "post_form",
                        lambda *a, **k: tokens(id_token=None))
    with pytest.raises(oauth.AuthorizationFailed):
        oauth.connect(store, "prod", open_browser=_drive_browser, timeout=15)


# --------------------------------------------------------------- refresh
def test_a_refresh_without_a_new_refresh_token_keeps_the_stored_one(monkeypatch, store):
    """
    The inverse of the previous broker's rule, and the easiest thing to get
    wrong when porting. Cognito does not rotate refresh tokens: it omits the
    field entirely. Writing that absence through would delete a working token
    and force a fresh sign-in on the next launch.
    """
    store.set(config.stage_key("refresh_token", "prod"), "rt-original")
    monkeypatch.setattr(oauth, "post_form",
                        lambda *a, **k: tokens(refresh_token=None, id_token="id-2"))

    assert oauth.refresh(store, "prod") == "id-2"
    assert store.get(config.stage_key("refresh_token", "prod")) == "rt-original"


def test_a_rotated_refresh_token_is_still_persisted_if_one_arrives(monkeypatch, store):
    store.set(config.stage_key("refresh_token", "prod"), "rt-old")
    monkeypatch.setattr(oauth, "post_form",
                        lambda *a, **k: tokens(refresh_token="rt-new"))
    oauth.refresh(store, "prod")
    assert store.get(config.stage_key("refresh_token", "prod")) == "rt-new"


def test_expiry_is_shortened_by_the_skew():
    import time as _time
    oauth._remember(JsonStore(), "prod", tokens(expires_in=3600))
    _, expires_at = oauth._tokens["prod"]
    remaining = expires_at - _time.time()
    # 3600s nominal, refreshed 60s early.
    assert 3530 < remaining <= 3540


def test_a_rejected_refresh_token_is_discarded(monkeypatch, store):
    store.set(config.stage_key("refresh_token", "prod"), "rt-dead")
    monkeypatch.setattr(oauth, "post_form", lambda *a, **k: (_ for _ in ()).throw(
        HttpError(400, "invalid_grant", {"error": "invalid_grant"})))

    with pytest.raises(oauth.NotConnected):
        oauth.refresh(store, "prod")
    # Keeping it would reproduce the same failure on every later call.
    assert store.get(config.stage_key("refresh_token", "prod")) is None


def test_an_offline_refresh_keeps_the_token(monkeypatch, store):
    store.set(config.stage_key("refresh_token", "prod"), "rt-good")
    monkeypatch.setattr(oauth, "post_form", lambda *a, **k: (_ for _ in ()).throw(
        NetworkError("dns failure")))

    with pytest.raises(NetworkError):
        oauth.refresh(store, "prod")
    # Offline is not unauthorised. Discarding here would log a user out for
    # walking into a lift.
    assert store.get(config.stage_key("refresh_token", "prod")) == "rt-good"


def test_refresh_without_a_stored_token_reports_not_connected(store):
    with pytest.raises(oauth.NotConnected):
        oauth.refresh(store, "prod")


def test_bearer_token_uses_the_cache_then_refreshes(monkeypatch, store):
    store.set(config.stage_key("refresh_token", "prod"), "rt-1")
    calls = []

    def fake_post_form(url, fields, headers=None, timeout=None):
        calls.append(fields)
        return tokens(id_token="id-%d" % len(calls), refresh_token=None)

    monkeypatch.setattr(oauth, "post_form", fake_post_form)

    assert oauth.bearer_token(store, "prod") == "id-1"
    assert oauth.bearer_token(store, "prod") == "id-1"
    assert len(calls) == 1, "a live cached token must not trigger a refresh"
    assert calls[0]["grant_type"] == "refresh_token"

    oauth._tokens["prod"] = ("id-1", 0)
    assert oauth.bearer_token(store, "prod") == "id-2"


def test_connected_state_and_disconnect(store):
    assert oauth.is_connected(store, "prod") is False
    store.set(config.stage_key("refresh_token", "prod"), "rt-1")
    assert oauth.is_connected(store, "prod") is True

    oauth.disconnect(store, "prod")
    assert oauth.is_connected(store, "prod") is False
    assert store.get(config.stage_key("refresh_token", "prod")) is None


def test_stages_hold_independent_sessions(store):
    store.set(config.stage_key("refresh_token", "prod"), "rt-prod")
    store.set(config.stage_key("refresh_token", "hml"), "rt-hml")

    oauth.disconnect(store, "hml")

    # Testing against HML must never cost the user their production session.
    assert oauth.is_connected(store, "prod") is True
    assert oauth.is_connected(store, "hml") is False
