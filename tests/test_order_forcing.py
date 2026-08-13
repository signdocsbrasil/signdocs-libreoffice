"""
A certificate profile cannot sign in parallel, and the UI must say so.

The server already overrides it — create-envelope.ts forces SEQUENTIAL for
DIGITAL_CERTIFICATE and reports `signingModeForced`. Offering "Paralela" next
to a certificate is therefore offering a choice that does not exist: the send
goes out sequential regardless and the user finds out afterwards.

The rule is asserted against the server's own list rather than restated, so the
two cannot drift apart quietly.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pythonpath"))

from signdocs import api  # noqa: E402

ORDER_DEPENDENT_PROFILES = ("digital_certificate",)

SERVER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "external-api", "src", "handlers", "libreoffice", "create-envelope.ts")


def test_the_client_forces_the_same_profiles_the_server_does():
    # Skipped rather than failed when the sibling checkout is absent: the
    # extension has to build on its own.
    if not os.path.exists(SERVER):
        return
    src = open(SERVER, encoding="utf-8").read()
    match = re.search(r"ORDER_DEPENDENT_PROFILES\s*=\s*new Set\(\[([^\]]*)\]", src)
    assert match, "the server no longer declares ORDER_DEPENDENT_PROFILES"
    server_profiles = set(re.findall(r"'([^']+)'", match.group(1)))

    # The client speaks in its own keys; map through the same table the wire
    # uses so the comparison is real rather than a coincidence of spelling.
    client_profiles = {api.PROFILES[k] for k in ORDER_DEPENDENT_PROFILES}
    assert client_profiles == server_profiles


def test_every_forced_profile_is_a_real_profile():
    for key in ORDER_DEPENDENT_PROFILES:
        assert key in api.PROFILES


def test_the_other_profiles_are_not_forced():
    # Click-only and OTP have no cross-signer dependency, so parallel is
    # genuinely available and must stay offered.
    assert "click_only" not in ORDER_DEPENDENT_PROFILES
    assert "click_plus_otp" not in ORDER_DEPENDENT_PROFILES


# ------------------------------------------------- signing window parity
def test_the_client_quotes_the_window_the_server_actually_uses():
    """
    The window is told to the sender as a number, and the server owns it. Copy
    it and the two drift — which is exactly what happened to the Telegram
    "24 horas" strings, caught only by a screenshot of the bot.
    """
    if not os.path.exists(SERVER):
        return
    window = os.path.join(os.path.dirname(SERVER), "..", "..",
                          "config", "signing-window.ts")
    window = os.path.normpath(window)
    if not os.path.exists(window):
        return
    src = open(window, encoding="utf-8").read()
    match = re.search(r"DEFAULT_SIGNING_WINDOW_MINUTES\s*=\s*(\d+)", src)
    assert match, "the server no longer declares DEFAULT_SIGNING_WINDOW_MINUTES"

    from signdocs import config
    assert int(match.group(1)) == config.SIGNING_WINDOW_HOURS * 60


def test_the_signer_cap_stays_within_what_one_request_can_finish():
    # 30 signers x ~1s per add-session, inside a 30s API Gateway timeout, with
    # the envelope create (~1.7s) already spent. Raising this without making
    # the send asynchronous puts users back on the 504-but-it-worked path.
    from signdocs import api
    assert api.MAX_SIGNERS <= 30
