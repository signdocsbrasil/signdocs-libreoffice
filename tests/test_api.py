# SPDX-License-Identifier: MPL-2.0
"""
The add-on API client.

The assertions worth having are the ones that encode a rule the server will
otherwise enforce with an opaque 4xx, or — worse — accept and get wrong.

Two are specific to the add-on model and easy to regress when porting from
the direct-API version:

* **`owner` is never sent.** The server sets it from the verified Cognito
  identity, which is what makes the ownership checks downstream meaningful.
  Transmitting one from the client would at best be ignored and at worst
  invite somebody to try.
* **an idempotency key always is.** The server rejects a create without one
  rather than silently double-billing a retry, so a client that omits it
  fails every send.
"""

import hashlib
import json

import pytest

from signdocs import api, oauth
from signdocs.httpclient import HttpError
from signdocs.store import JsonStore

DOC = {"content": "QkFTRTY0", "filename": "contrato.pdf", "module": "writer"}


def signer(name="Ana", email="ana@ex.com.br", fiscal="529.982.247-25"):
    return {"name": name, "email": email, "fiscal": fiscal}


class Recorder(object):
    """Stands in for httpclient.request, recording every call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None):
        self.calls.append({
            "url": url,
            "method": method,
            "payload": json.loads(body.decode("utf-8")) if body else None,
            "headers": headers or {},
        })
        if not self._responses:
            raise AssertionError("unexpected call: %s %s" % (method, url))
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@pytest.fixture
def store():
    s = JsonStore()
    # Pretend we are already signed in; oauth has its own tests.
    oauth._tokens["prod"] = ("id-token-test", 1 << 40)
    yield s
    oauth._tokens.clear()


@pytest.fixture
def recorder(monkeypatch):
    def install(*responses):
        rec = Recorder(responses)
        monkeypatch.setattr(api, "request", rec)
        return rec

    return install


# ------------------------------------------------------------- validation
def test_rejects_an_empty_signer_list():
    with pytest.raises(api.ValidationError):
        api.validate_signers([])


def test_rejects_more_than_the_api_bound():
    with pytest.raises(api.ValidationError):
        api.validate_signers([signer(email="a%d@b.cc" % i)
                              for i in range(api.MAX_SIGNERS + 1)])


def test_rejects_a_duplicate_email():
    with pytest.raises(api.ValidationError) as excinfo:
        api.validate_signers([signer(), signer(name="Outro")])
    assert "mais de uma vez" in str(excinfo.value)


def test_rejects_a_bad_check_digit():
    with pytest.raises(api.ValidationError) as excinfo:
        api.validate_signers([signer(fiscal="52998224726")])
    assert "CPF" in str(excinfo.value)


def test_rejects_a_missing_fiscal_id_blank_name_or_bad_email():
    with pytest.raises(api.ValidationError):
        api.validate_signers([signer(fiscal="")])
    with pytest.raises(api.ValidationError):
        api.validate_signers([signer(name="  ")])
    with pytest.raises(api.ValidationError):
        api.validate_signers([signer(email="nope")])


# ---------------------------------------------------------------- signers
def test_signer_carries_exactly_one_fiscal_field():
    built = api.build_signer(signer(fiscal="529.982.247-25"), 0)
    assert built["cpf"] == "52998224725"
    assert "cnpj" not in built

    built = api.build_signer(signer(fiscal="11.222.333/0001-81"), 0)
    assert built["cnpj"] == "11222333000181"
    assert "cpf" not in built


def test_external_id_is_a_stable_hash_of_the_email():
    expected = "lo:" + hashlib.sha256(b"ana@ex.com.br").hexdigest()
    assert api.build_signer(signer(), 0)["userExternalId"] == expected
    # Case must not mint a second identity for the same person.
    assert api.build_signer(signer(email="ANA@Ex.com.BR"), 0)["userExternalId"] == expected


# ------------------------------------------------------------------ link
def test_link_joins_url_and_client_secret():
    assert api.signing_link("https://s/x", "ss_secret_a") == "https://s/x?cs=ss_secret_a"
    # The envelope path returns a ready link with no separate secret.
    assert api.signing_link("https://s/x", None) == "https://s/x"
    assert api.signing_link(None, "ss_secret_a") is None


def test_link_percent_encodes_the_secret():
    assert api.signing_link("https://s/x", "a/b+c=d") == "https://s/x?cs=a%2Fb%2Bc%3Dd"


# ------------------------------------------------------ single signer send
def test_one_signer_posts_to_the_add_on_tier(store, recorder):
    rec = recorder({
        "sessionId": "sess-1", "transactionId": "tx-1",
        "url": "https://sign/s/sess-1", "clientSecret": "ss_secret_x",
        "inviteSent": True,
    })

    result = api.send(store, DOC, [signer()], profile="click_plus_otp",
                      idempotency_key="idem-1")

    call = rec.calls[0]
    assert call["method"] == "POST"
    # The stable hostname, not an execute-api one, and under /libreoffice.
    assert call["url"] == (
        "https://libreoffice-api.signdocs.com.br/libreoffice/create-signing-session"
    )
    # The Cognito ID token, presented as a bearer.
    assert call["headers"]["Authorization"] == "Bearer id-token-test"

    payload = call["payload"]
    assert payload["policy"] == {"profile": "CLICK_PLUS_OTP"}
    assert payload["__idempotencyKey"] == "idem-1"
    assert payload["document"]["module"] == "writer"
    # The server sets owner from the verified identity; sending one would be
    # meaningless and is deliberately not done.
    assert "owner" not in payload
    # No owner of any shape leaves the client: the server sets it from the
    # verified identity, and a client-supplied one would be silently ignored
    # while looking authoritative in the request log.
    assert "owner_email" not in payload
    assert "owner" not in payload

    assert result["kind"] == "session"
    assert result["id"] == "sess-1"
    assert result["links"][0]["url"] == "https://sign/s/sess-1?cs=ss_secret_x"
    assert result["links"][0]["inviteSent"] is True


def test_a_generated_idempotency_key_is_still_sent(store, recorder):
    rec = recorder({"sessionId": "s", "url": "u", "clientSecret": "c"})
    api.send(store, DOC, [signer()])
    assert rec.calls[0]["payload"]["__idempotencyKey"]


def test_digital_certificate_is_the_profile_for_a1_and_a3(store, recorder):
    rec = recorder({"sessionId": "s", "url": "u", "clientSecret": "c"})
    api.send(store, DOC, [signer()], profile="digital_certificate")
    # DIGITAL_SIGN_A1 is a step type and 400s as a policy profile.
    assert rec.calls[0]["payload"]["policy"]["profile"] == "DIGITAL_CERTIFICATE"


def test_an_unknown_profile_is_refused_before_any_request(store, recorder):
    recorder()
    with pytest.raises(api.ValidationError):
        api.send(store, DOC, [signer()], profile="DIGITAL_SIGN_A1")


def test_stage_selects_the_host(store, recorder):
    oauth._tokens["hml"] = ("id-hml", 1 << 40)
    rec = recorder({"sessionId": "s", "url": "u", "clientSecret": "c"})
    api.send(store, DOC, [signer()], stage="hml")
    assert rec.calls[0]["url"].startswith(
        "https://libreoffice-api-hml.signdocs.com.br/libreoffice/")


# ---------------------------------------------------------- envelope send
def test_two_signers_post_one_envelope_call(store, recorder):
    # Unlike the direct API — which needed a create plus one add-session per
    # signer — the add-on tier does the whole envelope in one request.
    rec = recorder({
        "envelopeId": "env-1",
        "signingMode": "SEQUENTIAL",
        "signers": [
            {"email": "ana@ex.com.br", "url": "https://sign/s/a", "sessionId": "a"},
            {"email": "bruno@ex.com.br", "url": "https://sign/s/b",
             "sessionId": "b", "inviteSent": True},
        ],
    })

    result = api.send(
        store, DOC,
        [signer(), signer(name="Bruno", email="bruno@ex.com.br", fiscal="12345678909")],
        order="SEQUENTIAL", idempotency_key="idem-9",
    )

    assert len(rec.calls) == 1
    payload = rec.calls[0]["payload"]
    assert rec.calls[0]["url"].endswith("/libreoffice/create-envelope")
    assert payload["signingMode"] == "SEQUENTIAL"
    assert [s["name"] for s in payload["signers"]] == ["Ana", "Bruno"]
    assert all(s["profile"] == "CLICK_ONLY" for s in payload["signers"])

    assert result["kind"] == "envelope"
    assert result["id"] == "env-1"
    # Links are matched back to signers by e-mail, not by list position, so a
    # server that reorders them cannot mislabel somebody's link.
    assert [link["url"] for link in result["links"]] == [
        "https://sign/s/a", "https://sign/s/b",
    ]
    assert result["links"][1]["inviteSent"] is True


def test_a_forced_signing_mode_is_surfaced(store, recorder):
    # The server forces SEQUENTIAL when a certificate profile is present,
    # because the A1 path loads the previous signer's output. The UI must be
    # able to say so rather than let the user believe PARALLEL was honoured.
    recorder({
        "envelopeId": "env-1", "signingMode": "SEQUENTIAL",
        "signingModeForced": True, "signers": [],
    })
    result = api.send(
        store, DOC,
        [signer(), signer(email="b@ex.com.br", fiscal="12345678909")],
        profile="digital_certificate", order="PARALLEL",
    )
    assert result["signingModeForced"] is True
    assert result["signingMode"] == "SEQUENTIAL"


# --------------------------------------------------------------- status
def test_session_status_is_normalised(store, recorder):
    recorder({"status": "COMPLETED", "transactionId": "tx-7"})
    status = api.status_of(store, "session", "sess-1")
    assert status["status"] == "COMPLETED"
    assert (status["completed"], status["total"]) == (1, 1)
    assert status["signed_available"] is True


def test_envelope_status_is_normalised(store, recorder):
    recorder({"status": "PENDING", "completedSessions": 1, "totalSigners": 3})
    status = api.status_of(store, "envelope", "env-1")
    assert (status["completed"], status["total"]) == (1, 3)
    assert status["signed_available"] is False


# ------------------------------------------------------------- download
def test_download_fetches_the_presigned_url_without_auth(store, recorder, monkeypatch):
    recorder({"transactionId": "tx-7", "signedUrl": "https://s3/signed"})
    fetched = {}

    def fake_get_bytes(url, timeout=None):
        fetched["url"] = url
        return b"%PDF-signed"

    monkeypatch.setattr(api, "get_bytes", fake_get_bytes)
    assert api.signed_pdf(store, "session", "sess-1") == b"%PDF-signed"
    assert fetched["url"] == "https://s3/signed"


def test_download_before_completion_says_so(store, recorder):
    # The server answers 409 rather than handing back the unsigned original,
    # so this distinction can be trusted.
    recorder(HttpError(409, "not signed yet", {"error": "NOT_SIGNED_YET"}))
    with pytest.raises(api.NotSignedYet):
        api.signed_pdf(store, "session", "sess-1")


def test_envelope_download_uses_the_envelope_route(store, recorder, monkeypatch):
    rec = recorder({"signedUrl": "https://s3/combined"})
    monkeypatch.setattr(api, "get_bytes", lambda url, timeout=None: b"%PDF-x")
    api.signed_pdf(store, "envelope", "env-1")
    assert rec.calls[0]["url"].endswith("/libreoffice/signed-document/envelope/env-1")


def test_signed_filename_matches_the_nextcloud_convention():
    assert api.signed_filename("contrato.pdf") == "contrato-assinado.pdf"
    assert api.signed_filename("contrato.PDF") == "contrato-assinado.pdf"
    assert api.signed_filename(None) == "documento-assinado.pdf"


# --------------------------------------------------------------- cancel
def test_envelope_cancel_uses_its_own_route_and_reports_preserved(store, recorder):
    rec = recorder({"alreadyCancelled": False, "cancelledCount": 2,
                    "preservedSignedCount": 1})
    result = api.cancel(store, "envelope", "env-1")
    assert rec.calls[0]["url"].endswith("/libreoffice/cancel-envelope/env-1")
    # Already-collected signatures survive a cancel; the UI must be able to
    # say so rather than implying everything was destroyed.
    assert result["preservedSignedCount"] == 1


def test_session_cancel_treats_409_and_404_as_already_cancelled(store, recorder):
    recorder(HttpError(409, "not active"))
    assert api.cancel(store, "session", "s-1")["alreadyCancelled"] is True
    recorder(HttpError(404, "gone"))
    assert api.cancel(store, "session", "s-1")["alreadyCancelled"] is True


def test_cancel_still_raises_on_a_real_error(store, recorder):
    recorder(HttpError(500, "boom"))
    with pytest.raises(HttpError):
        api.cancel(store, "session", "sess-1")


# ------------------------------------------------------- withdrawn profile
def test_biometric_is_not_offered(store):
    """
    The API accepts BIOMETRIC, but it is provisioned per tenant by an
    administrator and has no live clients. Offering it in a desktop dropdown
    hands the user a choice that fails at send time for a reason they can
    neither see nor fix.
    """
    from signdocs.ui import strings

    assert "biometric" not in api.PROFILES
    assert "biometric" not in strings.PROFILE_ORDER
    assert "BIOMETRIC" not in api.PROFILES.values()


def test_sending_biometric_is_refused_before_any_request(store, recorder):
    # Named explicitly rather than relying on the generic unknown-profile
    # guard: this is the regression that matters if someone reinstates it in
    # the dropdown without first granting it on the tenant.
    rec = recorder()
    with pytest.raises(api.ValidationError):
        api.send(store, DOC, [signer()], profile="biometric")
    assert rec.calls == []


@pytest.mark.parametrize("key,wire", [
    ("click_only", "CLICK_ONLY"),
    ("click_plus_otp", "CLICK_PLUS_OTP"),
    ("digital_certificate", "DIGITAL_CERTIFICATE"),
])
def test_the_remaining_profiles_still_map(store, recorder, key, wire):
    rec = recorder({"sessionId": "s", "url": "u", "clientSecret": "c"})
    api.send(store, DOC, [signer()], profile=key)
    assert rec.calls[0]["payload"]["policy"]["profile"] == wire


# ------------------------------------------------- per-signer status rows
#
# "Signatários: 1/3" says a document is stuck without saying who on. The
# add-on tier already passes the envelope's `sessions` through whole, so the
# names were arriving and being discarded.

def test_envelope_status_lists_each_signer(store, recorder):
    recorder({
        "status": "PENDING", "completedSessions": 1, "totalSigners": 2,
        "sessions": [
            {"sessionId": "ss-2", "signerName": "Bruno",
             "signerEmail": "bruno@ex.com", "status": "ACTIVE", "signerIndex": 2},
            {"sessionId": "ss-1", "signerName": "Ana",
             "signerEmail": "ana@ex.com", "status": "COMPLETED", "signerIndex": 1},
        ],
    })
    signers = api.status_of(store, "envelope", "env-1")["signers"]

    # Sorted by signing order: on a SEQUENTIAL envelope the order says who is
    # being waited on, so returning them as they arrived would mislead.
    assert [row["name"] for row in signers] == ["Ana", "Bruno"]
    assert [row["status"] for row in signers] == ["COMPLETED", "ACTIVE"]
    assert signers[0]["email"] == "ana@ex.com"


def test_envelope_status_without_sessions_yields_no_rows(store, recorder):
    # An envelope that has aged out of the API still has to render.
    recorder({"status": "PENDING", "completedSessions": 0, "totalSigners": 2})
    assert api.status_of(store, "envelope", "env-1")["signers"] == []


def test_session_status_yields_one_row_carrying_the_session_state(store, recorder):
    recorder({"status": "ACTIVE", "transactionId": "tx-7",
              "signerEmail": "ana@ex.com"})
    signers = api.status_of(store, "session", "sess-1")["signers"]

    assert len(signers) == 1
    # No name on this payload — the tracker fills it from what it recorded at
    # send time, so None here is expected rather than a gap.
    assert signers[0] == {"name": None, "email": "ana@ex.com",
                          "status": "ACTIVE", "index": 1}
