# SPDX-License-Identifier: MPL-2.0
"""
The authorization flow.

Two behaviours here are worth more than the rest put together, and both are
asserted directly rather than inferred:

* the rotated refresh token reaches the profile **before** the access token is
  armed — the server has already invalidated the presented one, so the reverse
  order turns a crash into a permanent logout;
* a refresh that fails because the machine is offline must **not** discard the
  refresh token, while one the server rejects must.

The loopback leg runs for real against a bound socket rather than a mock, so
the handler, the port selection and the state check are exercised as shipped.
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
    oauth._access_tokens.clear()
    yield
    oauth._access_tokens.clear()


@pytest.fixture
def store():
    s = JsonStore()
    s.set(config.stage_key("client_id", "prod"), "dcr_test")
    return s


# ------------------------------------------------------------------- PKCE
def test_verifier_meets_rfc7636_length():
    verifier = oauth.new_verifier()
    assert 43 <= len(verifier) <= 128
    assert oauth.new_verifier() != verifier


def test_challenge_is_unpadded_base64url_sha256():
    verifier = "abc123"
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    assert oauth.challenge_for(verifier) == expected
    # Padding would be rejected: the server compares the string it was given.
    assert "=" not in oauth.challenge_for(verifier)


def test_state_round_trips():
    packed = oauth.pack_state("nonce-1")
    assert oauth.unpack_state(packed)["n"] == "nonce-1"
    assert "=" not in packed


def test_unpack_state_rejects_a_non_object():
    packed = base64.urlsafe_b64encode(json.dumps([1, 2]).encode()).decode().rstrip("=")
    with pytest.raises(ValueError):
        oauth.unpack_state(packed)


def test_authorize_url_carries_everything_the_server_requires():
    url = oauth.authorize_url(
        config.STAGES["prod"], "dcr_x", "http://127.0.0.1:8712/callback", "chal", "st"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith("https://auth.signdocs.com.br/oauth2/authorize?")
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["dcr_x"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8712/callback"]
    assert query["code_challenge"] == ["chal"]
    # The server advertises S256 only; `plain` is not offered and must never
    # be sent.
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == [" ".join(config.SCOPES)]


# ---------------------------------------------------------- registration
def test_registration_happens_once_and_is_cached(monkeypatch):
    calls = []

    def fake_post_json(url, payload, headers=None, timeout=None):
        calls.append(payload)
        return {"client_id": "dcr_abc"}

    monkeypatch.setattr(oauth, "post_json", fake_post_json)
    s = JsonStore()

    assert oauth.ensure_client_id(s, "prod") == "dcr_abc"
    assert oauth.ensure_client_id(s, "prod") == "dcr_abc"
    assert len(calls) == 1, "a cached client id must not re-register"

    # Every candidate port is registered up front, because authorize.ts
    # exact-matches the redirect URI including the port.
    assert calls[0]["redirect_uris"] == config.redirect_uris()
    assert len(calls[0]["redirect_uris"]) == len(config.LOOPBACK_PORTS)


def test_registration_is_namespaced_per_stage(monkeypatch):
    monkeypatch.setattr(
        oauth, "post_json",
        lambda url, payload, headers=None, timeout=None: {
            "client_id": "dcr_" + ("hml" if "hml" in url else "prod")
        },
    )
    s = JsonStore()
    assert oauth.ensure_client_id(s, "prod") == "dcr_prod"
    assert oauth.ensure_client_id(s, "hml") == "dcr_hml"
    assert s.get(config.stage_key("client_id", "prod")) == "dcr_prod"
    assert s.get(config.stage_key("client_id", "hml")) == "dcr_hml"


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
        exchanged.update(fields)
        return {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 900}

    monkeypatch.setattr(oauth, "post_form", fake_post_form)

    token = oauth.connect(store, "prod", open_browser=_drive_browser, timeout=15)

    assert token == "at-1"
    assert exchanged["grant_type"] == "authorization_code"
    assert exchanged["code"] == "auth-code-1"
    assert exchanged["client_id"] == "dcr_test"
    # PKCE: the verifier, not the challenge, goes to the token endpoint.
    assert len(exchanged["code_verifier"]) >= 43
    assert exchanged["redirect_uri"].startswith("http://127.0.0.1:")
    assert store.get(config.stage_key("refresh_token", "prod")) == "rt-1"


def test_connect_rejects_a_mismatched_state(monkeypatch, store):
    monkeypatch.setattr(
        oauth, "post_form",
        lambda *a, **k: pytest.fail("must not reach the token endpoint"),
    )

    def hostile_browser(url):
        # An unsolicited hit on the loopback port must not be able to feed us
        # a code.
        _drive_browser(
            url.replace("state=", "state=" + oauth.pack_state("wrong") + "&ignored="),
            {"code": "attacker-code"},
        )

    with pytest.raises(oauth.AuthorizationFailed):
        oauth.connect(store, "prod", open_browser=hostile_browser, timeout=15)


def test_connect_surfaces_a_denied_consent(monkeypatch, store):
    monkeypatch.setattr(
        oauth, "post_form",
        lambda *a, **k: pytest.fail("must not reach the token endpoint"),
    )

    def denying_browser(url):
        _drive_browser(url, {
            "error": "access_denied",
            "error_description": "Autorização negada pelo usuário.",
        })

    with pytest.raises(oauth.AuthorizationFailed) as excinfo:
        oauth.connect(store, "prod", open_browser=denying_browser, timeout=15)
    assert "negada" in str(excinfo.value)


def test_connect_times_out_without_a_callback(monkeypatch, store):
    monkeypatch.setattr(oauth, "post_form", lambda *a, **k: pytest.fail("no code"))
    with pytest.raises(oauth.AuthorizationFailed):
        oauth.connect(store, "prod", open_browser=lambda url: None, timeout=1)


# --------------------------------------------------------------- refresh
def test_rotated_refresh_token_is_persisted_before_the_access_token_is_armed():
    """
    The ordering guarantee. token.ts deletes the presented refresh token the
    moment it issues a replacement, so if the process dies after we start
    using the new access token but before the new refresh token is on disk,
    the user can never reconnect without re-consenting.
    """
    observed = {}

    class OrderSpy(JsonStore):
        def set(self, key, value):
            if key.startswith(config.STORAGE["refresh_token"]):
                observed["armed_at_write_time"] = "prod" in oauth._access_tokens
            JsonStore.set(self, key, value)

    spy = OrderSpy()
    oauth._remember(spy, "prod", {
        "access_token": "at", "refresh_token": "rt", "expires_in": 900,
    })

    assert observed["armed_at_write_time"] is False
    assert spy.get(config.stage_key("refresh_token", "prod")) == "rt"
    assert oauth._access_tokens["prod"][0] == "at"


def test_expiry_is_shortened_by_the_skew():
    oauth._remember(JsonStore(), "prod", {"access_token": "at", "expires_in": 900})
    _, expires_at = oauth._access_tokens["prod"]
    import time as _time
    remaining = expires_at - _time.time()
    # 900s nominal, refreshed 60s early.
    assert 830 < remaining <= 840


def test_a_rejected_refresh_token_is_discarded(monkeypatch, store):
    store.set(config.stage_key("refresh_token", "prod"), "rt-dead")

    def reject(*a, **k):
        raise HttpError(400, "invalid_grant", {"error": "invalid_grant"})

    monkeypatch.setattr(oauth, "post_form", reject)

    with pytest.raises(oauth.NotConnected):
        oauth.refresh(store, "prod")
    # Keeping it would reproduce the same failure on every later call.
    assert store.get(config.stage_key("refresh_token", "prod")) is None


def test_an_offline_refresh_keeps_the_token(monkeypatch, store):
    store.set(config.stage_key("refresh_token", "prod"), "rt-good")

    def offline(*a, **k):
        raise NetworkError("dns failure")

    monkeypatch.setattr(oauth, "post_form", offline)

    with pytest.raises(NetworkError):
        oauth.refresh(store, "prod")
    # Offline is not unauthorised. Discarding here would log a user out for
    # walking into a lift.
    assert store.get(config.stage_key("refresh_token", "prod")) == "rt-good"


def test_refresh_without_a_stored_token_reports_not_connected(store):
    with pytest.raises(oauth.NotConnected):
        oauth.refresh(store, "prod")


def test_access_token_uses_the_cache_then_refreshes(monkeypatch, store):
    store.set(config.stage_key("refresh_token", "prod"), "rt-1")
    calls = []

    def fake_post_form(url, fields, headers=None, timeout=None):
        calls.append(fields)
        return {"access_token": "at-%d" % len(calls), "refresh_token": "rt-next",
                "expires_in": 900}

    monkeypatch.setattr(oauth, "post_form", fake_post_form)

    assert oauth.access_token(store, "prod") == "at-1"
    assert oauth.access_token(store, "prod") == "at-1"
    assert len(calls) == 1, "a live cached token must not trigger a refresh"
    assert calls[0]["grant_type"] == "refresh_token"

    # Expire it and the next call refreshes.
    oauth._access_tokens["prod"] = ("at-1", 0)
    assert oauth.access_token(store, "prod") == "at-2"


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
