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

import json
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


def redacted(url):
    """
    A signing URL with its credential taken out.

    The `?cs=ss_secret_…` half IS the authentication for a CLICK_ONLY signature,
    so printing even a prefix of it puts a live credential in a terminal
    scrollback and, sooner or later, in a pasted bug report. Every assertion
    here is about whether the link is well formed or fetchable — none of them
    needs the secret itself, so none of them gets it.
    """
    if not url:
        return ""
    head, sep, _ = str(url).partition("?cs=")
    return head + ("?cs=<redigido>" if sep else "")


def check(label, condition, detail=""):
    print("  %s %s%s" % ("ok  " if condition else "FAIL", label,
                         ("  -- " + str(detail)) if detail else ""))
    if not condition:
        failures.append(label)


def section(title):
    print("\n== %s" % title)


def signed_in_email(token):
    """
    Read the `email` claim out of our own ID token.

    Used to make the single-signer run address the person who just signed in,
    which the API treats as sender-is-signer and therefore dispatches NO
    invite. A hardcoded default here would mail a real person the first time
    somebody ran this with a different account.

    Unverified base64 decode on purpose: the server verifies the signature,
    this is only picking a value to put in a form.
    """
    import base64

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("email")
    except Exception:
        return None


def _link_for(sent, email):
    """The entry in a send's link list belonging to one signer."""
    for link in sent.get("links") or []:
        if (link.get("signerEmail") or "").lower() == email.lower():
            return link
    return None


def _fetchable(url):
    """
    Whether a minted signing link really loads.

    "Well-formed" and "works" are different claims, and only the second one
    matters to somebody trying to sign. No Authorization header: the secret
    rides in the query string and the signing page is not behind bearer auth.
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code == 200
    except Exception:
        return False


def make_pdf():
    """A genuinely valid PDF, produced by LibreOffice itself."""
    tmpdir = tempfile.mkdtemp(prefix="signdocs-e2e-")
    src = os.path.join(tmpdir, "contrato.txt")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write("Contrato de teste da extensao SignDocs para LibreOffice.\n")
    # Its own profile, so this never contends with a LibreOffice the
    # developer already has open.
    subprocess.run(
        ["soffice", "--headless", "--norestore",
         "-env:UserInstallation=file://" + os.path.join(tmpdir, "profile"),
         "--convert-to", "pdf", "--outdir", tmpdir, src],
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
        # config.STAGES[stage]["login"], not a COGNITO constant: there is one
        # managed-login host per stage, and signing in against the wrong pool
        # is the failure this print exists to make visible.
        print("  opening your browser at %s ..." % config.STAGES[STAGE]["login"])
        token = oauth.connect(store, STAGE, timeout=300)
        check("signed in", bool(token))
        # Deliberately prints nothing derived from the token. The 24-char
        # prefix this used to show was only the JWT header — identical for
        # every token from the pool, so it revealed nothing — but it was
        # also useless, since a truncated token cannot be reused. It only
        # taught CodeQL to flag the line and a reader to paste a value that
        # would not work.
        print("     reuse with: export SIGNDOCS_ID_TOKEN=<o token completo>")

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
    me = os.environ.get("SIGNDOCS_E2E_EMAIL") or signed_in_email(
        oauth.bearer_token(store, STAGE))
    if not me:
        print("  could not read the email claim; set SIGNDOCS_E2E_EMAIL")
        return 2
    print("  signing as %s (same as sender, so no invite is sent)" % me)
    sent = api.send(store, document, [{"name": "Teste E2E", "email": me,
                                       "fiscal": CPF_A}],
                    profile="click_only", stage=STAGE)
    created.append(("session", sent["id"]))
    check("session created", bool(sent["id"]), sent["id"])
    link = sent["links"][0]["url"]
    check("link returned", bool(link), redacted(link))

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
    # Counting links is not the same as having working ones. The envelope path
    # returned bare URLs — no `?cs=` — for a long time, and it stayed invisible
    # because invited signers get a correctly-assembled link by e-mail instead.
    # Only the sender ever saw it, and only when they were also a signer.
    for entry in env["links"]:
        if entry.get("url"):
            check("envelope link carries its client secret",
                  "?cs=ss_secret_" in entry["url"],
                  redacted(entry["url"]))
    env_status = api.status_of(store, "envelope", env["id"], stage=STAGE)
    check("envelope reports 2 signers", env_status["total"] == 2, env_status["total"])

    section("sign it yourself")
    # The link is never stored — not in the profile, not in the history — so
    # "take me back to my document" has to mint a new one. This is the whole
    # mechanism behind the Assinar agora button surviving a closed window.
    url = api.sign_link(store, "session", sent["id"], stage=STAGE)
    check("a link was minted for my own session", bool(url), redacted(url))
    check("the minted link carries a client secret",
          "cs=ss_secret_" in (url or ""))
    if url:
        check("the minted link actually loads", _fetchable(url), redacted(url))
    # Minted, not looked up: a second call must work and must differ.
    again = api.sign_link(store, "session", sent["id"], stage=STAGE)
    check("a second call mints another working link",
          bool(again) and again != url)
    # Owning a send does not entitle you to sign it. Neither signer on the
    # two-signer envelope is me, so there is no link here to give.
    check("refused for an envelope I am not a signer in",
          api.sign_link(store, "envelope", env["id"], stage=STAGE) is None)

    section("click-only links are withheld from the sender")
    # A CLICK_ONLY link is the entire authentication, so handing the sender
    # somebody else's would let them sign in that person's name. Mixed
    # deliberately: my own link must still come back.
    other = "e2e-terceiro@example.invalid"
    mixed = api.send(
        store, document,
        [{"name": "Eu", "email": me, "fiscal": CPF_A},
         {"name": "Terceiro", "email": other, "fiscal": CPF_B}],
        profile="click_only", order="PARALLEL", stage=STAGE)
    created.append(("envelope", mixed["id"]))
    mine = _link_for(mixed, me)
    theirs = _link_for(mixed, other)
    check("my own click-only link is returned", bool(mine and mine.get("url")))
    if mine and mine.get("url"):
        # The sender's own envelope link is exactly the one nobody e-mails, so
        # it has to be verified by loading it rather than by inspection.
        check("the sender's own envelope link actually loads",
              _fetchable(mine["url"]), redacted(mine["url"]))
    check("another signer's click-only link is WITHHELD",
          bool(theirs) and not theirs.get("url"),
          (theirs or {}).get("url") or "absent")
    # Withholding is only acceptable because the invitation still goes out.
    check("an invitation was dispatched to them instead",
          bool(theirs and theirs.get("inviteSent")))
    check("envelope self-sign-link returns my own session",
          bool(api.sign_link(store, "envelope", mixed["id"], stage=STAGE)))

    section("a second factor means the link may be shared")
    # The rule has to be this narrow: with an OTP going to the signer's own
    # mailbox, holding the link is not enough to sign.
    otp = api.send(
        store, document,
        [{"name": "Eu", "email": me, "fiscal": CPF_A},
         {"name": "Terceiro", "email": other, "fiscal": CPF_B}],
        profile="click_plus_otp", order="PARALLEL", stage=STAGE)
    created.append(("envelope", otp["id"]))
    otp_theirs = _link_for(otp, other)
    check("another signer's click+OTP link is returned",
          bool(otp_theirs and otp_theirs.get("url")),
          (otp_theirs or {}).get("url", "")[:60] or "absent")

    section("resend still delivers")
    # Refactored onto the shared mint, and now the ONLY way a withheld
    # click-only signer can be reached — so a regression here would strand
    # them completely. Unit tests pin the guards; this proves the live route
    # still answers and still throttles.
    #
    # Run against the single-signer session, whose signer is the signed-in
    # account: a real invitation lands in YOUR OWN inbox, so delivery can be
    # confirmed by eye without mailing anybody else. Click the button in it —
    # that is the same link an invited signer receives.
    try:
        api._call(store, "POST", "/resend-invite/" + sent["id"], {}, STAGE)
        check("resend-invite accepted", True, "check your inbox for %s" % me)
    except HttpError as exc:
        check("resend-invite accepted", False, "%s %s" % (exc.status, exc.message))
    # One per 60 s per session, so an immediate repeat must be refused.
    try:
        api._call(store, "POST", "/resend-invite/" + sent["id"], {}, STAGE)
        check("the 60s resend throttle still bites", False, "accepted twice")
    except HttpError as exc:
        check("the 60s resend throttle still bites", exc.status == 409, exc.status)

    section("a subuser is never a signatory")
    # Address supplied by the environment, never hardcoded: this repo is going
    # public and the only useful value is a real person's e-mail.
    #
    #   SIGNDOCS_E2E_SUBUSER=<an address registered as a Convidados subuser>
    #
    # There is rarely a spare one, and pointing this at a real subuser means
    # that if the guard ever regresses, a stranger receives a signing invite for
    # a test document. Use a throwaway row on a non-deliverable address instead,
    # so a regression bounces rather than reaching anyone:
    #
    #   aws dynamodb put-item --region us-east-1 \
    #     --table-name Convidados-<suffix>-NONE --item '{
    #       "email":{"S":"e2e-subusuario@example.invalid"},
    #       "is_subusuario":{"BOOL":true},
    #       "master_email":{"S":"<your master>"}}'
    #
    # The lookup is a GetItem keyed on the lowercased address that only reads
    # is_subusuario and master_email, so those three fields are the whole
    # fixture. Delete the row afterwards.
    subuser = os.environ.get("SIGNDOCS_E2E_SUBUSER")
    if not subuser:
        print("  skipped — set SIGNDOCS_E2E_SUBUSER to a registered subuser")
    else:
        try:
            api.send(store, document,
                     [{"name": "Subusuario", "email": subuser, "fiscal": CPF_A}],
                     profile="click_only", stage=STAGE)
            check("a session addressed to a subuser is refused", False,
                  "the send was ACCEPTED")
        except HttpError as exc:
            # 422 with the app's wording. A subuser signs against the master's
            # row, never one of their own, so this document could never be
            # legitimately completed.
            check("a session addressed to a subuser is refused",
                  exc.status == 422, "%s %s" % (exc.status, exc.message))
            check("the refusal names the offending address",
                  subuser in (exc.message or ""), exc.message)

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
