"""
The same CPF cannot appear twice in one envelope.

Client-side courtesy only — the server refuses it regardless — but this is the
half that catches it while the user is still typing, rather than after four
signers and a PDF upload.
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pythonpath"))

from signdocs import validators  # noqa: E402


def taken(state, skip=None):
    """Mirror of dialogs._taken_fiscal, which needs UNO to import."""
    return {
        validators.only_digits(sg.get("fiscal"))
        for i, sg in enumerate(state.get("signers") or [])
        if i != skip and validators.only_digits(sg.get("fiscal"))
    }


def state_of(*fiscals):
    return {"signers": [{"name": "P%d" % i, "fiscal": f}
                        for i, f in enumerate(fiscals)]}


def test_a_repeat_is_detected():
    st = state_of("751.820.411-87")
    assert validators.only_digits("75182041187") in taken(st)


def test_punctuation_does_not_hide_a_repeat():
    # The reported case typed it punctuated once and bare the second time.
    st = state_of("75182041187")
    assert validators.only_digits("751.820.411-87") in taken(st)


def test_a_different_person_is_allowed():
    st = state_of("52998224725")
    assert validators.only_digits("12345678909") not in taken(st)


def test_editing_a_signer_does_not_collide_with_themselves():
    # Re-saving row 1 without touching the CPF must still be allowed.
    st = state_of("52998224725", "12345678909")
    assert validators.only_digits("12345678909") not in taken(st, skip=1)


def test_editing_still_sees_the_other_rows():
    st = state_of("52998224725", "12345678909")
    assert validators.only_digits("52998224725") in taken(st, skip=1)


def test_blank_fiscals_are_not_treated_as_a_shared_value():
    st = {"signers": [{"name": "A", "fiscal": ""}, {"name": "B"}]}
    assert taken(st) == set()


# ---------------------------------------------------------- duplicate email
def taken_email(state, skip=None):
    """Mirror of dialogs._taken_email."""
    return {
        (sg.get("email") or "").strip().lower()
        for i, sg in enumerate(state.get("signers") or [])
        if i != skip and (sg.get("email") or "").strip()
    }


def state_emails(*emails):
    return {"signers": [{"name": "P%d" % i, "email": e}
                        for i, e in enumerate(emails)]}


def test_a_repeated_address_is_detected():
    st = state_emails("ana@x.com")
    assert "ana@x.com" in taken_email(st)


def test_address_matching_ignores_case_and_space():
    st = state_emails(" Ana@X.com ")
    assert "ana@x.com" in taken_email(st)


def test_a_different_address_is_allowed():
    st = state_emails("ana@x.com")
    assert "bruno@x.com" not in taken_email(st)


def test_editing_a_signer_does_not_collide_with_their_own_address():
    st = state_emails("ana@x.com", "bruno@x.com")
    assert "bruno@x.com" not in taken_email(st, skip=1)


def test_blank_addresses_are_not_treated_as_a_shared_value():
    st = {"signers": [{"name": "A", "email": ""}, {"name": "B"}]}
    assert taken_email(st) == set()
