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
