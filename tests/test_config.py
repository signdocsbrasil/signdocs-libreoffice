# SPDX-License-Identifier: MPL-2.0
"""
Endpoint and stage selection.

Pointing production traffic at HML (or the reverse) is a silent, expensive
mistake — the hosted signing SPA has shipped exactly that bug before — so the
defaults are asserted rather than assumed.

The hostnames matter more here than in most config: they are compiled into a
.oxt that users install and update on their own schedule, so a wrong or
unstable one cannot be fixed by redeploying.
"""

import pytest

from signdocs import config
from signdocs.store import JsonStore


@pytest.fixture
def store():
    return JsonStore()


def test_defaults_to_production(store):
    assert config.current_stage(store) == "prod"
    assert config.endpoints(store)["api"] == "https://libreoffice-api.signdocs.com.br"


def test_api_base_includes_the_route_prefix(store):
    assert config.api_base(store) == (
        "https://libreoffice-api.signdocs.com.br/libreoffice"
    )
    assert config.api_base(store, "hml") == (
        "https://libreoffice-api-hml.signdocs.com.br/libreoffice"
    )


def test_hosts_are_stable_custom_domains_not_execute_api():
    # An auto-generated {apiId}.execute-api host changes whenever the stack is
    # recreated, which would break every installed .oxt in the field.
    for stage in ("prod", "hml"):
        host = config.STAGES[stage]["api"]
        assert host.endswith(".signdocs.com.br"), host
        assert "execute-api" not in host


def test_stage_round_trips(store):
    config.set_stage(store, "hml")
    assert config.current_stage(store) == "hml"
    assert config.endpoints(store)["api"] == "https://libreoffice-api-hml.signdocs.com.br"

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


def test_sessions_are_namespaced_per_stage():
    # Testing against HML must never clobber the production session.
    assert config.stage_key("refresh_token", "prod") == "signdocs.refreshToken.prod"
    assert config.stage_key("refresh_token", "hml") == "signdocs.refreshToken.hml"
    assert config.stage_key("sends", "prod") != config.stage_key("sends", "hml")


# ------------------------------------------------------------------ login
def test_each_stage_has_its_own_pool_and_login_host():
    """
    backend-sign-docs deploys one Cognito pool per Amplify branch — master is
    production (421 users), dev is homologação (6). Sharing one login between
    stages would let production credentials open homologação data and the
    reverse, which is the separation staging exists to provide.
    """
    prod, hml = config.STAGES["prod"], config.STAGES["hml"]
    assert prod["login"] == "https://login.signdocs.com.br"
    assert hml["login"] == "https://login-hml.signdocs.com.br"
    assert prod["login"] != hml["login"]
    # Different pools mean different app clients; reusing one would not even
    # work, since the audience is bound per pool.
    assert prod["client_id"] != hml["client_id"]


def test_login_uses_our_own_domain_not_amazoncognito():
    # Users type their SignDocs password on these pages; an amazoncognito.com
    # host reads as phishing and is exactly what a procurement reviewer would
    # flag.
    for stage in ("prod", "hml"):
        assert "amazoncognito.com" not in config.STAGES[stage]["login"]
        assert config.STAGES[stage]["login"].endswith(".signdocs.com.br")


def test_email_scope_is_requested():
    # The add-on tier resolves identity, quota and ownership from the email
    # claim, which is only present when this scope is granted.
    assert "email" in config.SCOPES
    assert "openid" in config.SCOPES


def test_no_client_secret_anywhere():
    # Public clients: shipping the id is safe precisely because there is no
    # secret. If one ever appears here, something has gone very wrong.
    for stage in ("prod", "hml"):
        assert config.STAGES[stage]["client_id"]
        assert "client_secret" not in config.STAGES[stage]


# --------------------------------------------------------------- loopback
def test_document_ceiling_matches_the_api():
    assert config.MAX_BASE64_BYTES == 10 * 1024 * 1024


def test_loopback_redirects_are_ipv4_literals_on_distinct_ports():
    uris = config.redirect_uris()
    assert len(uris) == len(config.LOOPBACK_PORTS) == len(set(uris))
    for uri in uris:
        # Every one of these is pre-registered on the Cognito app client, and
        # the redirect URI is exact-matched. `[::1]` is never used: the
        # listener binds the 127.0.0.1 literal.
        assert uri.startswith("http://127.0.0.1:")
        assert uri.endswith("/callback")
        assert "::1" not in uri


def test_redirect_uri_is_stable_for_a_given_port():
    # This formatting is a wire contract with the Cognito app client's
    # registered callback list, not cosmetics.
    assert config.redirect_uri(8712) == "http://127.0.0.1:8712/callback"


def test_login_language_uses_pt_BR_not_pt():
    # Cognito silently ignores `pt` and falls back to English — verified
    # against the live login page. Getting this wrong looks exactly like the
    # localisation feature not working at all.
    assert config.LOGIN_LANG["pt"] == "pt-BR"
    assert config.DEFAULT_LOGIN_LANG == "pt-BR"


def test_every_ui_language_maps_to_a_login_language():
    from signdocs.ui import strings

    for lang in ("pt", "en", "es"):
        assert lang in config.LOGIN_LANG
    # The office can only ever report one of these three.
    assert set(config.LOGIN_LANG) == {"pt", "en", "es"}
    assert strings.Strings("de").lang in config.LOGIN_LANG
