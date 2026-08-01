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
