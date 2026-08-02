# SPDX-License-Identifier: MPL-2.0
"""
Rendering the plan and remaining allowance.

This is billing information shown to the user, so the failure that matters is
not a crash but a confident wrong number. Every case here is one the backend
can actually produce — the shapes are taken from `channel-quota-init`'s
response and `checkChannelQuota`'s four sources.
"""

import pytest

from signdocs.ui import strings


@pytest.fixture
def s():
    return strings.Strings("pt")


def info(plan="Gratuito", **quota):
    body = {"allowed": True, "source": "shared_free_pool",
            "used": 1, "remaining": 2, "limit": 3}
    body.update(quota)
    return {"allowed": body["allowed"], "quota": body,
            "user": {"email": "a@b.com", "plan": plan}}


# ----------------------------------------------------------------- happy
def test_paid_plan_shows_plan_name_and_both_numbers(s):
    line = strings.quota_line(s, info(
        plan="Iniciante 80", source="paid_plan", used=12, remaining=68, limit=80))
    assert "Iniciante 80" in line
    assert "68" in line and "80" in line


def test_free_user_reports_the_shared_pool_limit_not_the_plan_limit(s):
    """
    The single most misleading case available.

    A planless account is written a Customer record with plan `Gratuito`, and
    `getPlanLimit('Gratuito')` returns **5**. But `isFree` makes `isPaid`
    false, so the enforced quota comes from the shared free pool, which is
    **3**. Deriving the limit from the plan name would show a ceiling 67%
    higher than the one the server actually applies.
    """
    line = strings.quota_line(s, info(plan="Gratuito", remaining=2, limit=3))
    assert "3" in line
    assert "5" not in line


def test_credits_do_not_borrow_the_plan_wording(s):
    # source=credits sets limit == credits, so "2 de 2" would be nonsense.
    line = strings.quota_line(s, info(source="credits", remaining=7, limit=7))
    assert "7" in line
    assert "de 7" not in line


# --------------------------------------------------------------- blocked
def test_exhausted_says_so_rather_than_showing_zero(s):
    assert strings.quota_line(s, info(remaining=0, limit=3)) == s("quota_blocked")


def test_server_allowed_false_outranks_a_positive_remaining(s):
    """
    A blocked channel gate returns `allowed: false` while `remaining` still
    reads above zero. The server's own decision has to win, or the extension
    would promise a send that is certain to be refused.
    """
    line = strings.quota_line(s, info(allowed=False, remaining=3, limit=3))
    assert line == s("quota_blocked")


# ------------------------------------------------------------ degradation
@pytest.mark.parametrize("bad", [
    None, {}, "nope", 42, [],
    {"quota": None},
    {"quota": "nope"},
    {"quota": {}},
    {"quota": {"remaining": 2}},                      # no limit
    {"quota": {"limit": 3}},                          # no remaining
    {"quota": {"remaining": "2", "limit": "3"}},      # strings, not counts
    {"quota": {"remaining": None, "limit": None}},
])
def test_unusable_payloads_render_nothing_at_all(s, bad):
    # None means "draw no line". A placeholder row reads as a rendering bug,
    # and a guessed number reads as fact.
    assert strings.quota_line(s, bad) is None


def test_booleans_are_not_accepted_as_counts(s):
    # isinstance(True, int) is True in Python, so a bool would sail through a
    # naive check and render as "restam 1 de 3" — wrong, and plausible enough
    # that nobody would question it.
    assert strings.quota_line(s, info(remaining=True, limit=3)) is None


def test_missing_user_block_still_reports_the_numbers(s):
    line = strings.quota_line(s, {"quota": {"allowed": True, "remaining": 2,
                                            "limit": 3}})
    assert line is not None
    assert "2" in line and "3" in line


def test_absent_plan_name_does_not_print_an_empty_slot(s):
    line = strings.quota_line(s, info(plan=""))
    assert line is not None
    assert "  " not in line
    assert not line.startswith("Plano ·")


# ------------------------------------------------------------- exhausted
def test_exhausted_when_remaining_is_zero():
    assert strings.quota_exhausted(info(remaining=0, limit=3)) is True


def test_exhausted_when_the_server_says_not_allowed():
    assert strings.quota_exhausted(info(allowed=False, remaining=3)) is True


def test_not_exhausted_with_allowance_left():
    assert strings.quota_exhausted(info(remaining=1, limit=3)) is False


@pytest.mark.parametrize("unknown", [
    None, {}, "nope", 42,
    {"quota": None},
    {"quota": {}},
    {"quota": {"limit": 3}},                       # no remaining
    {"quota": {"remaining": None}},
    {"quota": {"remaining": "0"}},                 # a string, not a count
])
def test_an_unknown_quota_is_never_treated_as_exhausted(unknown):
    """
    The distinction the whole gate rests on.

    `quota_line` returning None means the lookup failed and nothing is known;
    exhausted means it succeeded and the answer was no. Conflating them would
    let a timed-out status call stop a send the user is entitled to make —
    a worse failure than the one being prevented.
    """
    assert strings.quota_exhausted(unknown) is False


def test_a_blocked_quota_both_reads_blocked_and_gates(s):
    # The line the user sees and the decision to warn must not disagree.
    payload = info(allowed=False, remaining=0, limit=3)
    assert strings.quota_line(s, payload) == s("quota_blocked")
    assert strings.quota_exhausted(payload) is True


def test_credits_are_not_exhausted_while_any_remain():
    assert strings.quota_exhausted(
        info(source="credits", remaining=7, limit=7)) is False


# ---------------------------------------------------------------- locale
@pytest.mark.parametrize("lang", ["pt", "en", "es"])
def test_every_language_renders_each_branch(lang):
    s = strings.Strings(lang)
    cases = [
        info(plan="Iniciante 80", source="paid_plan", remaining=68, limit=80),
        info(source="credits", remaining=7, limit=7),
        info(remaining=0, limit=3),
        info(plan=""),
    ]
    for case in cases:
        line = strings.quota_line(s, case)
        assert line and "%" not in line, (lang, case)


def test_quota_keys_exist_in_all_three_languages():
    for key in ("plan", "quota_line", "quota_line_noplan", "quota_credits",
                "quota_blocked", "quota_unknown", "quota_shared",
                "quota_confirm"):
        for lang in ("pt", "en", "es"):
            value = strings.Strings(lang)(key)
            assert value and value != key, (key, lang)
