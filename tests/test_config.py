# SPDX-License-Identifier: MPL-2.0
"""
Endpoint and stage selection.

Pointing production traffic at HML (or the reverse) is a silent, expensive
mistake — the hosted signing SPA has shipped exactly that bug before — so the
defaults and the per-stage key namespacing are asserted rather than assumed.
"""

import pytest

from signdocs import config
from signdocs.store import JsonStore


@pytest.fixture
def store():
    return JsonStore()


def test_defaults_to_production(store):
    assert config.current_stage(store) == "prod"
    assert config.endpoints(store)["api"] == "https://api.signdocs.com.br"
    assert config.endpoints(store)["auth"] == "https://auth.signdocs.com.br"


def test_hml_host_uses_a_dash_not_a_dot():
    # api-hml.signdocs.com.br, never api.hml.signdocs.com.br.
    assert config.STAGES["hml"]["api"] == "https://api-hml.signdocs.com.br"
    assert config.STAGES["hml"]["auth"] == "https://auth-hml.signdocs.com.br"


def test_stage_round_trips(store):
    config.set_stage(store, "hml")
    assert config.current_stage(store) == "hml"
    assert config.endpoints(store)["api"] == "https://api-hml.signdocs.com.br"

    config.set_stage(store, "prod")
    assert config.current_stage(store) == "prod"


def test_unknown_stage_falls_back_to_production(store):
    config.set_stage(store, "banana")
    assert config.current_stage(store) == "prod"

    store.set(config.STORAGE["stage"], "PROD-ish")
    assert config.current_stage(store) == "prod"


def test_unreadable_store_falls_back_to_production():
    class Hostile(object):
        def get(self, key, default=None):
            raise IOError("blocked")

        def set(self, key, value):
            raise IOError("blocked")

    assert config.current_stage(Hostile()) == "prod"
    # Must not raise; the choice just isn't remembered.
    config.set_stage(Hostile(), "hml")


def test_credentials_are_namespaced_per_stage():
    assert config.stage_key("client_id", "prod") != config.stage_key("client_id", "hml")
    assert config.stage_key("client_id", "prod") == "signdocs.clientId.prod"
    assert config.stage_key("refresh_token", "hml") == "signdocs.refreshToken.hml"


def test_scopes_are_only_what_the_extension_exercises():
    assert set(config.SCOPES) == {
        "transactions:read",
        "transactions:write",
        "steps:write",
    }
    # Enumeration and webhook scopes are deliberately absent.
    assert "webhooks:write" not in config.SCOPES
    assert "evidence:read" not in config.SCOPES


def test_document_ceiling_matches_the_api():
    # signing-sessions/create.ts rejects a base64 body over 10MB.
    assert config.MAX_BASE64_BYTES == 10 * 1024 * 1024


def test_loopback_redirects_are_ipv4_literals_on_distinct_ports():
    uris = config.redirect_uris()
    assert len(uris) == len(config.LOOPBACK_PORTS) == len(set(uris))
    for uri in uris:
        # `[::1]` is not in the authorization server's loopback check and is
        # rejected as non-https, so IPv6 must never appear here.
        assert uri.startswith("http://127.0.0.1:")
        assert uri.endswith("/callback")
        assert "::1" not in uri


def test_redirect_uri_is_stable_for_a_given_port():
    # The authorization server exact-matches the registered string, so this
    # formatting is a wire contract, not cosmetics.
    assert config.redirect_uri(8712) == "http://127.0.0.1:8712/callback"
