# SPDX-License-Identifier: MPL-2.0
"""
End-to-end run against the HML API.

Everything up to the consent screen can be verified without credentials, and
is, by the smoke test. This covers the half that cannot be: the
authorization-code exchange, refresh-token rotation, and every API call the
extension makes.

    export SIGNDOCS_CLIENT_ID=...        # HML API credentials, SANDBOX
    export SIGNDOCS_CLIENT_SECRET=...
    python3 bin/e2e_hml.py

The consent screen is driven by a scripted "browser" that posts the
credentials the way a human would. That is deliberate: the point is to
exercise the real broker flow, not to shortcut it with a client_credentials
token the extension would never use.

**No e-mail is sent.** The single-signer run sets `owner.email` equal to the
signer's, which the API treats as "the sender is the signer" and dispatches no
invite; the envelope run omits `owner` entirely, which dispatches none either.
Everything created is cancelled before the script exits.
"""

import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pythonpath"))

from signdocs import api, config, intake, oauth  # noqa: E402
from signdocs.httpclient import HttpError, ssl_context  # noqa: E402
from signdocs.store import JsonStore  # noqa: E402

STAGE = "hml"
SIGNER_CPF = "529.982.247-25"
SECOND_CPF = "12345678909"

failures = []
created = []


def check(label, condition, detail=""):
    print("  %s %s%s" % ("ok  " if condition else "FAIL", label,
                         ("  -- " + str(detail)) if detail else ""))
    if not condition:
        failures.append(label)


def section(title):
    print("\n== %s" % title)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def scripted_browser(email, secret):
    """
    Stand in for the human at the consent screen.

    Fetches the form, posts the SignDocs API credentials into it, and follows
    the 302 back to the loopback listener — exactly the sequence a real
    browser performs.
    """
    def open_url(authorize_url):
        def go():
            try:
                ctx = ssl_context()
                page = urllib.request.urlopen(
                    urllib.request.Request(authorize_url, headers={"User-Agent": "e2e"}),
                    timeout=30, context=ctx,
                ).read().decode()

                fields = {}
                for tag in re.findall(r"<input[^>]*>", page):
                    name = re.search(r'name="([^"]*)"', tag)
                    value = re.search(r'value="([^"]*)"', tag)
                    if name:
                        fields[name.group(1)] = value.group(1) if value else ""
                fields["signdocs_client_id"] = email
                fields["signdocs_client_secret"] = secret

                opener = urllib.request.build_opener(
                    _NoRedirect, urllib.request.HTTPSHandler(context=ctx))
                post = urllib.request.Request(
                    config.STAGES[STAGE]["auth"] + "/oauth2/authorize",
                    data=urllib.parse.urlencode(fields).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "User-Agent": "e2e"},
                )
                try:
                    resp = opener.open(post, timeout=30)
                    location = resp.headers.get("Location")
                except urllib.error.HTTPError as exc:
                    location = exc.headers.get("Location")
                    if not location:
                        print("     consent POST failed: %s\n%s"
                              % (exc.code, exc.read()[:400].decode("utf-8", "replace")))
                        return

                urllib.request.urlopen(
                    urllib.request.Request(location, headers={"User-Agent": "e2e"}),
                    timeout=30,
                ).read()
            except Exception as exc:  # pragma: no cover - diagnostic only
                print("     scripted browser error: %r" % (exc,))

        threading.Thread(target=go, daemon=True).start()

    return open_url


def make_pdf():
    """A genuinely valid PDF, produced by LibreOffice itself."""
    tmpdir = tempfile.mkdtemp(prefix="signdocs-e2e-")
    src = os.path.join(tmpdir, "contrato.txt")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write("Contrato de teste da extensao SignDocs para LibreOffice.\n"
                 "Documento gerado automaticamente para verificacao de integracao.\n")
    subprocess.run(
        ["soffice", "--headless", "--norestore", "--convert-to", "pdf",
         "--outdir", tmpdir, src],
        check=True, capture_output=True, timeout=180,
    )
    pdf = os.path.join(tmpdir, "contrato.pdf")
    with open(pdf, "rb") as fh:
        raw = fh.read()
    return {"content": intake.encode(raw), "filename": "contrato.pdf",
            "module": "writer"}, len(raw)


def main():
    client_id = os.environ.get("SIGNDOCS_CLIENT_ID")
    client_secret = os.environ.get("SIGNDOCS_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("SIGNDOCS_CLIENT_ID and SIGNDOCS_CLIENT_SECRET must be set")
        return 2

    store = JsonStore()
    config.set_stage(store, STAGE)

    section("authorization code flow through the real broker")
    token = oauth.connect(store, STAGE,
                          open_browser=scripted_browser(client_id, client_secret),
                          timeout=90)
    check("connect returned an access token", bool(token))
    first_refresh = store.get(config.stage_key("refresh_token", STAGE))
    check("refresh token persisted", bool(first_refresh))
    check("client registered", bool(store.get(config.stage_key("client_id", STAGE))))

    section("refresh rotation")
    oauth._access_tokens.pop(STAGE, None)
    second_token = oauth.refresh(store, STAGE)
    second_refresh = store.get(config.stage_key("refresh_token", STAGE))
    check("refresh returned a new access token", bool(second_token))
    check("refresh token was rotated", second_refresh != first_refresh,
          "old and new differ")
    check("the rotated token is the one on disk", bool(second_refresh))

    section("document")
    document, raw_len = make_pdf()
    check("PDF built by LibreOffice", raw_len > 500, "%d bytes" % raw_len)

    section("single signer -> signing session")
    # owner.email == signer.email, so the API sends no invite.
    sent = api.send(
        store, document,
        [{"name": "Teste E2E", "email": "administrativo@signdocs.com.br",
          "fiscal": SIGNER_CPF}],
        profile="click_only", owner_email="administrativo@signdocs.com.br",
        stage=STAGE,
    )
    created.append(("session", sent["id"]))
    check("session created", bool(sent["id"]), sent["id"])
    check("kind is session", sent["kind"] == "session")
    link = sent["links"][0]["url"]
    check("link carries both url and cs", bool(link) and "?cs=ss_secret_" in (link or ""),
          (link or "")[:70] + "...")
    check("no invite dispatched to self", sent["links"][0]["inviteSent"] is False)

    section("status")
    status = api.status_of(store, "session", sent["id"], stage=STAGE)
    check("status is ACTIVE", status["status"] == "ACTIVE", status["status"])
    check("total is 1", status["total"] == 1)
    check("transactionId present", bool(status["transactionId"]), status["transactionId"])

    section("two signers -> envelope")
    # No owner, so no invites at all.
    env = api.send(
        store, document,
        [{"name": "Signatario Um", "email": "e2e-um@example.invalid",
          "fiscal": SIGNER_CPF},
         {"name": "Signatario Dois", "email": "e2e-dois@example.invalid",
          "fiscal": SECOND_CPF}],
        profile="click_only", order="SEQUENTIAL", stage=STAGE,
    )
    created.append(("envelope", env["id"]))
    check("envelope created", bool(env["id"]), env["id"])
    check("one link per signer", len(env["links"]) == 2)
    check("both links complete", all("?cs=" in (link["url"] or "") for link in env["links"]))

    env_status = api.status_of(store, "envelope", env["id"], stage=STAGE)
    check("envelope reports 2 signers", env_status["total"] == 2, env_status["total"])
    check("nothing signed yet", env_status["completed"] == 0)
    check("no combined PDF before completion", env_status["signed_available"] is False)

    section("cleanup: cancel everything created")
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
