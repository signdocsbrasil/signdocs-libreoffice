"""
The price shown must be the price charged.

Stripe holds the real amounts behind price IDs, and the Flutter app carries the
same table for display. A number shown here that Stripe then contradicts is the
one kind of drift a user notices immediately — and mistrusts.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pythonpath"))

from signdocs import api  # noqa: E402

APP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "sign-docs", "lib", "utils", "plan_utils.dart")


def _strip(name):
    """The app spells it 'Avancado', this side 'Avançado'."""
    import unicodedata
    n = unicodedata.normalize("NFD", name)
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


def test_prices_match_the_app_table():
    if not os.path.exists(APP):
        return  # sibling checkout absent; the extension still builds alone
    src = open(APP, encoding="utf-8").read()
    app_prices = {
        _strip(n): {"Mensal": int(m), "Anual": int(a)}
        for n, m, a in re.findall(
            r"'([^']+)':\s*\{'Mensal':\s*(\d+),\s*'Anual':\s*(\d+)\}", src)
    }
    assert app_prices, "the app no longer declares kPlanPrices in this shape"

    for plan in api.PLANS:
        key = _strip(plan["name"])
        assert key in app_prices, "%s is not in the app's table" % key
        assert plan["Mensal"] == app_prices[key]["Mensal"], key
        assert plan["Anual"] == app_prices[key]["Anual"], key


def test_every_plan_carries_both_periods():
    for plan in api.PLANS:
        for frequency in api.FREQUENCIES:
            assert isinstance(plan[frequency], int)
            assert plan[frequency] > 0


def test_annual_is_cheaper_than_twelve_months():
    # If this ever inverts, the annual option is a worse deal presented as a
    # discount.
    for plan in api.PLANS:
        assert plan["Anual"] < plan["Mensal"] * 12, plan["name"]


def test_price_formatting_is_pt_br():
    assert api.format_price(1990) == "R$ 19,90"
    assert api.format_price(17880) == "R$ 178,80"
    # Thousands separator is a dot, decimal a comma.
    assert api.format_price(131880) == "R$ 1.318,80"
    assert api.format_price(0) == "R$ 0,00"


def test_frequencies_are_what_the_server_accepts():
    # create-checkout.ts validates against exactly these two strings.
    assert api.FREQUENCIES == ("Mensal", "Anual")
