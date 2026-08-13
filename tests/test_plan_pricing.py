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


# ------------------------------------------------------- billing period
from signdocs.ui import strings  # noqa: E402


def test_a_monthly_paid_plan_is_recognised():
    assert strings.billing_period("Iniciante 20", 20, "paid_plan") == "Mensal"
    assert strings.billing_period("Avançado 200", 200, "paid_plan") == "Mensal"


def test_an_annual_paid_plan_is_recognised():
    # The server multiplies by twelve; this reads that back.
    assert strings.billing_period("Iniciante 20", 240, "paid_plan") == "Anual"
    assert strings.billing_period("Avançado 200", 2400, "paid_plan") == "Anual"


def test_anything_it_cannot_prove_stays_silent():
    # A label is not worth claiming a period the account may not be on.
    assert strings.billing_period("Gratuito", 3, "shared_free_pool") is None
    assert strings.billing_period("Gratuito", 5, "paid_plan") is None
    assert strings.billing_period("Enterprise", 500, "paid_plan") is None
    assert strings.billing_period("Iniciante 20", 137, "paid_plan") is None
    assert strings.billing_period(None, 20, "paid_plan") is None
    # Credits are a balance, not a period.
    assert strings.billing_period("Iniciante 20", 20, "credits") is None


def test_the_annual_line_says_the_period_and_the_whole_allowance():
    s = strings.Strings("pt")
    info = {"quota": {"allowed": True, "used": 19, "limit": 240,
                      "remaining": 221, "source": "paid_plan"},
            "user": {"plan": "Iniciante 20"}}
    line = strings.quota_line(s, info)
    assert "anual" in line
    assert "19/240" in line
    assert "221" in line


def test_a_monthly_line_is_unchanged():
    s = strings.Strings("pt")
    info = {"quota": {"allowed": True, "used": 19, "limit": 20,
                      "remaining": 1, "source": "paid_plan"},
            "user": {"plan": "Iniciante 20"}}
    line = strings.quota_line(s, info)
    assert "anual" not in line
    assert "19/20" in line


def test_the_limit_still_comes_from_the_server_not_the_plan_name():
    # The standing rule: a planless user's Gratuito record would compute 5,
    # while the enforced shared pool is 3. The period label must not tempt
    # anyone into deriving the number instead of rendering it.
    s = strings.Strings("pt")
    info = {"quota": {"allowed": True, "used": 1, "limit": 3,
                      "remaining": 2, "source": "shared_free_pool"},
            "user": {"plan": "Gratuito"}}
    assert "1/3" in strings.quota_line(s, info)
