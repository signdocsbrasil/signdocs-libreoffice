"""
The signed-in address is refused as a signer only when the account is a subuser.

Pure logic, so it lives here rather than in the smoke probe: the predicate that
decides is what matters, and getting it wrong in the permissive direction just
defers the error to the server, while getting it wrong in the strict direction
would stop ordinary users naming themselves — which is the single commonest
thing anyone does with this extension.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pythonpath"))

from signdocs import oauth  # noqa: E402


def blocked(state):
    """Mirror of dialogs._blocked_signer_email, which needs UNO to import."""
    user = ((state or {}).get("quota") or {}).get("user") or {}
    return user.get("email", "") if user.get("isSubuser") else ""


def state_for(email, is_subuser):
    user = {"email": email, "plan": "Gratuito"}
    if is_subuser:
        user["isSubuser"] = True
    return {"quota": {"user": user}}


def test_a_subusers_own_address_is_blocked():
    s = state_for("sub@x.com", True)
    assert oauth.matches_account("sub@x.com", blocked(s)) is True


def test_case_and_whitespace_do_not_evade_the_block():
    s = state_for("sub@x.com", True)
    for typed in ("SUB@X.COM", " sub@x.com ", "Sub@X.com"):
        assert oauth.matches_account(typed, blocked(s)) is True


def test_a_subuser_may_still_name_somebody_else():
    # Only their OWN address is a problem. Whether another address belongs to
    # some other master's subuser is a directory question the server answers.
    s = state_for("sub@x.com", True)
    assert oauth.matches_account("cliente@x.com", blocked(s)) is False


def test_an_ordinary_user_may_name_themselves():
    # The commonest action in the whole extension: send a document to yourself.
    s = state_for("solo@x.com", False)
    assert blocked(s) == ""
    assert oauth.matches_account("solo@x.com", blocked(s)) is False


@pytest.mark.parametrize("state", [
    None,
    {},
    {"quota": None},
    {"quota": {}},
    {"quota": {"user": None}},
    {"quota": {"user": {}}},
])
def test_a_missing_or_failed_quota_lookup_blocks_nobody(state):
    # init_session is fail-soft by design; a failed lookup must not start
    # rejecting signers. The server still refuses a genuine subuser.
    assert blocked(state) == ""
