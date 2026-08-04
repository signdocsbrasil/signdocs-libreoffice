# SPDX-License-Identifier: MPL-2.0
"""
The Terms / Privacy gate.

Nothing server-side refuses a send from an account that has not accepted, so
this client-side check is the whole gate. That inverts the usual rule here:
everywhere else a failed lookup degrades to letting the user proceed, because
the server is the authority. Not here — an unconfirmed acceptance must stop
the send, or the gate is decorative.
"""

import pytest

from signdocs import api
from signdocs.httpclient import HttpError, NetworkError
from signdocs.store import JsonStore

STAGE = "hml"


@pytest.fixture
def store():
    return JsonStore()


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(store_, method, path, payload=None, stage=None):
        seen.append({"method": method, "path": path, "payload": payload})
        if path.endswith("/status"):
            return fake.status
        return {"ok": True}

    fake.status = {"required": {"tos": "2.1", "privacy": "1.4"},
                   "urls": {"tos": "https://s/tos", "privacy": "https://s/pp"},
                   "accepted": {}, "needsAcceptance": True,
                   "stale": ["CONSENT_TOS", "CONSENT_PRIVACY"]}
    monkeypatch.setattr(api, "_call", fake)
    fake.seen = seen
    return fake


# ------------------------------------------------------------------ status
def test_status_surfaces_the_stale_list(store, calls):
    out = api.policy_status(store, stage=STAGE)
    assert out["stale"] == ["CONSENT_TOS", "CONSENT_PRIVACY"]
    assert out["needsAcceptance"] is True
    assert out["urls"]["tos"] == "https://s/tos"


def test_an_accepted_account_reports_nothing_stale(store, calls):
    calls.status = {"required": {"tos": "2.1"}, "urls": {}, "accepted": {},
                    "needsAcceptance": False, "stale": []}
    assert api.policy_status(store, stage=STAGE)["stale"] == []


def test_an_unrecognised_policy_is_dropped_not_shown(store, calls):
    """
    DPA is the case that matters: its click-through was retired across every
    channel, so a server still listing it must not make this extension
    reintroduce a gate the business removed.
    """
    calls.status = {"required": {}, "urls": {}, "accepted": {},
                    "needsAcceptance": True,
                    "stale": ["CONSENT_TOS", "CONSENT_DPA", "SOMETHING_NEW"]}
    assert api.policy_status(store, stage=STAGE)["stale"] == ["CONSENT_TOS"]


def test_an_empty_response_is_not_read_as_accepted(store, monkeypatch):
    # A blank body must not look like "nothing stale", which would open the
    # gate. It yields no stale list, and the caller treats a failed lookup as
    # a refusal rather than inferring consent.
    monkeypatch.setattr(api, "_call", lambda *a, **k: None)
    out = api.policy_status(store, stage=STAGE)
    assert out["stale"] == []
    assert out["needsAcceptance"] is False


# ------------------------------------------------------------------ accept
def test_accept_posts_the_action_and_version(store, calls):
    api.policy_accept(store, "CONSENT_TOS", "2.1", url="https://s/tos",
                      stage=STAGE)
    sent = calls.seen[-1]
    assert sent["path"] == "/policy-consent/accept"
    assert sent["payload"]["action"] == "CONSENT_TOS"
    assert sent["payload"]["version"] == "2.1"
    assert sent["payload"]["url"] == "https://s/tos"


def test_accept_never_sends_an_email(store, calls):
    # Identity is taken from the verified ID token server-side. This record is
    # evidence that a named person accepted a named version, so the client does
    # not get to nominate who that was.
    api.policy_accept(store, "CONSENT_PRIVACY", "1.4", stage=STAGE)
    assert "email" not in calls.seen[-1]["payload"]


@pytest.mark.parametrize("action", ["CONSENT_DPA", "", None, "consent_tos",
                                    "ANYTHING"])
def test_accept_refuses_an_action_the_gate_does_not_cover(store, calls, action):
    with pytest.raises(api.ValidationError):
        api.policy_accept(store, action, "1.0", stage=STAGE)
    assert calls.seen == []


def test_accept_refuses_a_missing_version(store, calls):
    # Recording acceptance of "no version" would produce a record that proves
    # nothing about what was agreed to.
    with pytest.raises(api.ValidationError):
        api.policy_accept(store, "CONSENT_TOS", None, stage=STAGE)
    assert calls.seen == []


def test_a_failed_accept_propagates(store, monkeypatch):
    # The caller must be able to tell the write did not happen, so it can stop
    # the send rather than proceed on an acceptance that was never stored.
    def boom(*a, **k):
        raise HttpError(500, "upstream")

    monkeypatch.setattr(api, "_call", boom)
    with pytest.raises(HttpError):
        api.policy_accept(store, "CONSENT_TOS", "2.1", stage=STAGE)


def test_a_status_lookup_failure_propagates(store, monkeypatch):
    def offline(*a, **k):
        raise NetworkError("no route")

    monkeypatch.setattr(api, "_call", offline)
    with pytest.raises(NetworkError):
        api.policy_status(store, stage=STAGE)
