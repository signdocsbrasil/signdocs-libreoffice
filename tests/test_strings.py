# SPDX-License-Identifier: MPL-2.0
"""
The string table.

`strings.py` is the only module under `ui/` that touches no UNO at import
time, which is deliberate: the language mapping and the fallback behaviour are
the parts that can silently show a Brazilian user an English dialog, and they
should be testable without an office.
"""

import pytest

from signdocs.ui import strings


def test_every_key_exists_in_every_language():
    # A missing translation degrades to pt-BR at runtime, which is survivable
    # but invisible. Catch it here instead.
    missing = []
    for key, entry in strings._STRINGS.items():
        for lang in ("pt", "en", "es"):
            if not entry.get(lang):
                missing.append("%s/%s" % (key, lang))
    assert missing == []


def test_format_placeholders_match_across_languages():
    """
    A key used with `%` must take the same arguments in every language.

    Get this wrong and the mismatch raises TypeError at format time, inside a
    dialog builder, in whichever locale nobody happened to test — so pt-BR
    looks fine and the extension breaks for the Spanish half of its audience.
    The completeness test above cannot see it: both strings are present, they
    just disagree about their arguments.
    """
    import re

    spec = re.compile(r"%[-#0 +]*\d*(?:\.\d+)?[a-zA-Z]")
    for key, entry in strings._STRINGS.items():
        shapes = {lang: tuple(spec.findall((entry.get(lang) or "").replace("%%", "")))
                  for lang in ("pt", "en", "es")}
        assert len(set(shapes.values())) == 1, (key, shapes)


def test_lookup_returns_the_requested_language():
    assert strings.Strings("pt")("cancel") == "Cancelar"
    assert strings.Strings("en")("cancel") == "Cancel"
    assert strings.Strings("es")("close") == "Cerrar"


def test_unknown_language_falls_back_to_pt_br():
    # pt-BR is the fallback, not English: this is an ICP-Brasil product, and a
    # Brazilian user seeing English because locale detection hiccuped is worse
    # than the reverse.
    assert strings.Strings("de")("cancel") == "Cancelar"
    assert strings.Strings(None).lang == "pt"


def test_unknown_key_returns_the_key_rather_than_raising():
    # Raising inside a dialog builder would take the whole dialog down over a
    # cosmetic bug.
    assert strings.Strings("pt")("no_such_key_at_all") == "no_such_key_at_all"


@pytest.mark.parametrize("locale,expected", [
    ("pt-BR", "pt"),
    ("pt_BR", "pt"),
    ("pt", "pt"),
    ("en-US", "en"),
    ("es-ES", "es"),
    ("de-DE", "pt"),
    ("", "pt"),
    (None, "pt"),
])
def test_locale_reduces_to_a_supported_language(locale, expected):
    assert strings._lang_from_locale(locale) == expected


def test_profile_order_matches_the_api_profile_map():
    from signdocs import api

    # The dropdown is built by indexing PROFILE_ORDER, so a key here that the
    # API client does not know would send an unknown profile.
    for key in strings.PROFILE_ORDER:
        assert key in api.PROFILES
    assert len(strings.PROFILE_ORDER) == len(api.PROFILES)


def test_every_profile_has_a_label():
    for key in strings.PROFILE_ORDER:
        assert strings.Strings("pt")(key) != key


# ------------------------------------------------------------ api status
def test_every_wire_status_has_a_readable_label():
    """
    Sessions report ACTIVE/COMPLETED/CANCELLED/EXPIRED/FAILED; envelopes add
    CREATED. Any of these reaching a dialog verbatim is a bug the user sees.
    """
    s = strings.Strings("pt")
    for raw in ("CREATED", "ACTIVE", "COMPLETED", "CANCELLED", "EXPIRED",
                "FAILED"):
        label = strings.api_status(s, raw)
        assert label and label != raw
        assert label.upper() != raw


def test_active_is_named_for_what_is_being_waited_on():
    # "ACTIVE" is the API's word for "nobody has signed yet" and says nothing
    # to the person reading it.
    assert strings.api_status(strings.Strings("pt"), "ACTIVE") == "Aguardando assinatura"
    assert strings.api_status(strings.Strings("en"), "ACTIVE") == "Awaiting signature"


def test_unknown_status_shows_the_raw_value_rather_than_blank():
    # If the API grows a status, "SUSPENDED" is unhelpful but an empty field
    # looks like the dialog failed to load.
    assert strings.api_status(strings.Strings("pt"), "SUSPENDED") == "SUSPENDED"


def test_absent_status_renders_empty():
    s = strings.Strings("pt")
    assert strings.api_status(s, None) == ""
    assert strings.api_status(s, "") == ""


def test_lookup_is_case_and_space_insensitive():
    s = strings.Strings("pt")
    assert strings.api_status(s, " active ") == strings.api_status(s, "ACTIVE")


@pytest.mark.parametrize("lang", ["pt", "en", "es"])
def test_every_wire_status_is_translated_in_every_language(lang):
    s = strings.Strings(lang)
    for raw in strings.API_STATUS:
        assert strings.api_status(s, raw) not in ("", raw)


# ------------------------------------------------------------ signer_line
def test_signer_line_shows_name_and_translated_state():
    s = strings.Strings("pt")
    line = strings.signer_line(s, {"name": "Ana", "email": "ana@ex.com",
                                   "status": "COMPLETED"})
    assert line.startswith("Ana — ")
    # Translated, never the raw wire value.
    assert "COMPLETED" not in line


def test_signer_line_falls_back_to_the_email_when_unnamed():
    s = strings.Strings("pt")
    line = strings.signer_line(s, {"name": "", "email": "ana@ex.com",
                                   "status": "ACTIVE"})
    assert line.startswith("ana@ex.com — ")


def test_signer_line_never_renders_a_blank_row():
    # A row with neither name nor e-mail would otherwise look like a bug.
    s = strings.Strings("pt")
    assert strings.signer_line(s, {}).strip() == "—"


def test_signer_line_marks_your_own_row():
    s = strings.Strings("pt")
    mine = strings.signer_line(s, {"name": "Ana", "status": "ACTIVE"},
                               is_you=True)
    theirs = strings.signer_line(s, {"name": "Ana", "status": "ACTIVE"})
    assert s("signer_you") in mine
    assert s("signer_you") not in theirs


def test_signer_line_omits_the_dash_when_there_is_no_status():
    s = strings.Strings("pt")
    assert strings.signer_line(s, {"name": "Ana"}) == "Ana"


def test_signer_line_shows_email_and_fiscal():
    # Name alone does not identify a signer: two people share one, and the
    # fiscal number is the field a typo makes legally wrong rather than merely
    # undeliverable.
    s = strings.Strings("pt")
    line = strings.signer_line(s, {
        "name": "Ana", "email": "ana@ex.com", "fiscal": "52998224725",
        "status": "ACTIVE",
    })
    assert "Ana" in line
    assert "ana@ex.com" in line
    # Punctuated for reading, not echoed as raw digits.
    assert "529.982.247-25" in line


def test_signer_line_punctuates_a_cnpj_too():
    s = strings.Strings("pt")
    line = strings.signer_line(s, {"name": "WE", "fiscal": "11222333000181"})
    assert "11.222.333/0001-81" in line


def test_signer_line_omits_parts_that_are_missing():
    # No empty separators when a signer has only some of the fields.
    s = strings.Strings("pt")
    assert strings.signer_line(s, {"name": "Ana"}) == "Ana"
    assert "—" not in strings.signer_line(s, {"name": "Ana"})


def test_signer_line_does_not_repeat_the_email_standing_in_for_a_name():
    s = strings.Strings("pt")
    line = strings.signer_line(s, {"email": "ana@ex.com", "status": "ACTIVE"})
    assert line.count("ana@ex.com") == 1


def test_subuser_not_signer_uses_the_apps_wording():
    # Same rule, same sentence, wherever somebody meets it. The Flutter app
    # says exactly this in signatario_fields.dart.
    s = strings.Strings("pt")
    assert s("subuser_not_signer") == "Subusuários não podem ser signatários."
    assert strings.Strings("en")("subuser_not_signer") != "subuser_not_signer"
    assert strings.Strings("es")("subuser_not_signer") != "subuser_not_signer"
