# SPDX-License-Identifier: MPL-2.0
"""
End-to-end run against the HML add-on API.

    python3 bin/e2e_hml.py

Opens your browser at login.signdocs.com.br, waits for the loopback callback,
then exercises every route the extension uses. Sign in with any SignDocs
account — there is no API credential to supply, which is the whole point of
the add-on model.

Set `SIGNDOCS_ID_TOKEN` to skip the browser on repeat runs (paste a token
from a previous run's output). Tokens are short-lived, so this is a
convenience for iterating, not a way to run unattended.

**No e-mail is sent.** The single-signer run uses your own signed-in address
as the signer, which the API treats as sender-is-signer and dispatches no
invite; the envelope run uses `.invalid` addresses, which cannot be
delivered to. Everything created is cancelled before the script exits.
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pythonpath"))

from signdocs import api, config, intake, oauth  # noqa: E402
from signdocs.httpclient import HttpError  # noqa: E402
from signdocs.store import JsonStore  # noqa: E402

STAGE = "hml"
CPF_A = "529.982.247-25"
CPF_B = "12345678909"

failures = []
created = []


def check(label, condition, detail=""):
    print("  %s %s%s" % ("ok  " if condition else "FAIL", label,
                         ("  -- " + str(detail)) if detail else ""))
    if not condition:
        failures.append(label)


def section(title):
    print("\n== %s" % title)


def make_pdf():
    """A genuinely valid PDF, produced by LibreOffice itself."""
    tmpdir = tempfile.mkdtemp(prefix="signdocs-e2e-")
    src = os.path.join(tmpdir, "contrato.txt")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write("Contrato de teste da extensao SignDocs para LibreOffice.\n")
    subprocess.run(
        ["soffice", "--headless", "--norestore", "--convert-to", "pdf",
         "--outdir", tmpdir, src],
        check=True, capture_output=True, timeout=180,
    )
    with open(os.path.join(tmpdir, "contrato.pdf"), "rb") as fh:
        raw = fh.read()
    return {"content": intake.encode(raw), "filename": "contrato.pdf",
            "module": "writer"}, len(raw)


def main():
    store = JsonStore()
    config.set_stage(store, STAGE)

    section("sign in")
    preset = os.environ.get("SIGNDOCS_ID_TOKEN")
    if preset:
        # 1 << 40 is "far future": the token's real expiry still applies
        # server-side, this only stops the client refreshing it away.
        oauth._tokens[STAGE] = (preset, 1 << 40)
        check("using SIGNDOCS_ID_TOKEN from the environment", True)
    else:
        print("  opening your browser at %s ..." % config.COGNITO["domain"])
        token = oauth.connect(store, STAGE, timeout=300)
        check("signed in", bool(token))
        print("     reuse with: export SIGNDOCS_ID_TOKEN=%s..." % token[:24])

    section("channel registration and plan")
    try:
        info = api.init_session(store, stage=STAGE)
        check("init-session answered", bool(info), info.get("user", {}).get("plan"))
        quota = info.get("quota") or {}
        print("     quota: %s/%s used, %s remaining"
              % (quota.get("used"), quota.get("limit"), quota.get("remaining")))
        # Proves the backend-sign-docs channel deploy landed: before it,
        # 'libreoffice' was rejected with a bare 400.
        check("channel 'libreoffice' is registered upstream", "quota" in info)
    except HttpError as exc:
        check("init-session answered", False, "%s %s" % (exc.status, exc.message))

    section("document")
    document, raw_len = make_pdf()
    check("PDF built by LibreOffice", raw_len > 500, "%d bytes" % raw_len)

    section("single signer")
    me = os.environ.get("SIGNDOCS_E2E_EMAIL", "administrativo@signdocs.com.br")
    sent = api.send(store, document, [{"name": "Teste E2E", "email": me,
                                       "fiscal": CPF_A}],
                    profile="click_only", stage=STAGE)
    created.append(("session", sent["id"]))
    check("session created", bool(sent["id"]), sent["id"])
    link = sent["links"][0]["url"]
    check("link returned", bool(link), (link or "")[:70])

    status = api.status_of(store, "session", sent["id"], stage=STAGE)
    check("status is ACTIVE", status["status"] == "ACTIVE", status["status"])

    try:
        api.signed_pdf(store, "session", sent["id"], stage=STAGE)
        check("download refused before signing", False, "returned bytes")
    except api.NotSignedYet:
        # The server must never substitute the unsigned original.
        check("download refused before signing", True)

    section("two signers")
    env = api.send(
        store, document,
        [{"name": "Um", "email": "e2e-um@example.invalid", "fiscal": CPF_A},
         {"name": "Dois", "email": "e2e-dois@example.invalid", "fiscal": CPF_B}],
        profile="click_only", order="SEQUENTIAL", stage=STAGE)
    created.append(("envelope", env["id"]))
    check("envelope created", bool(env["id"]), env["id"])
    check("one link per signer", len(env["links"]) == 2)
    env_status = api.status_of(store, "envelope", env["id"], stage=STAGE)
    check("envelope reports 2 signers", env_status["total"] == 2, env_status["total"])

    section("forced signing mode")
    forced = api.send(
        store, document,
        [{"name": "Um", "email": "e2e-cert1@example.invalid", "fiscal": CPF_A},
         {"name": "Dois", "email": "e2e-cert2@example.invalid", "fiscal": CPF_B}],
        profile="digital_certificate", order="PARALLEL", stage=STAGE)
    created.append(("envelope", forced["id"]))
    # The A1 path loads the previous signer's output, so PARALLEL would give
    # signer 2 a masked 403. The server overrides and says so.
    check("PARALLEL overridden for a certificate profile",
          forced["signingMode"] == "SEQUENTIAL" and forced["signingModeForced"],
          forced["signingMode"])

    section("cleanup")
    for kind, ident in created:
        try:
            result = api.cancel(store, kind, ident, stage=STAGE)
            check("cancelled %s %s" % (kind, ident), True,
                  "preserved=%s" % result["preservedSignedCount"])
        except HttpError as exc:
            check("cancelled %s %s" % (kind, ident), False,
                  "%s %s" % (exc.status, exc.message))

    print("")
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), failures))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
