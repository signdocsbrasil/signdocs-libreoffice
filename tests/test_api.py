# SPDX-License-Identifier: MPL-2.0
"""
The API client.

The assertions worth having here are the ones that encode a rule the API will
otherwise enforce with an opaque 4xx, or — worse — accept and get wrong:
1-based `signerIndex`, exactly one of cpf/cnpj, `DIGITAL_CERTIFICATE` rather
than `DIGITAL_SIGN_A1`, sessions added one at a time in order, and an
idempotency key on every create.
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
    # Pretend we are already connected; oauth is covered by its own tests.
    oauth._access_tokens["prod"] = ("at-test", 1 << 40)
    yield s
    oauth._access_tokens.clear()


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
        api.validate_signers([signer(email="a%d@b.cc" % i) for i in range(api.MAX_SIGNERS + 1)])


def test_rejects_a_duplicate_email():
    # Two sessions for one person on one document is never what was meant.
    with pytest.raises(api.ValidationError) as excinfo:
        api.validate_signers([signer(), signer(name="Outro")])
    assert "mais de uma vez" in str(excinfo.value)


def test_rejects_a_bad_check_digit():
    with pytest.raises(api.ValidationError) as excinfo:
        api.validate_signers([signer(fiscal="52998224726")])
    assert "CPF" in str(excinfo.value)


def test_rejects_a_missing_fiscal_id():
    with pytest.raises(api.ValidationError):
        api.validate_signers([signer(fiscal="")])


def test_rejects_a_malformed_email_and_a_blank_name():
    with pytest.raises(api.ValidationError):
        api.validate_signers([signer(email="nope")])
    with pytest.raises(api.ValidationError):
        api.validate_signers([signer(name="  ")])


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


def test_external_id_falls_back_to_the_index_without_an_email():
    assert api.build_signer({"name": "Ana"}, 3)["userExternalId"] == "lo:idx:3"


# ------------------------------------------------------------------ link
def test_link_needs_both_halves():
    assert api.signing_link({"url": "https://s/x", "clientSecret": "ss_secret_a"}) == \
        "https://s/x?cs=ss_secret_a"
    # `url` alone is not a link — this is the exact gap that stops the
    # Nextcloud app showing single-signer links.
    assert api.signing_link({"url": "https://s/x"}) is None
    assert api.signing_link({"clientSecret": "ss_secret_a"}) is None
    assert api.signing_link(None) is None


def test_link_percent_encodes_the_secret():
    link = api.signing_link({"url": "https://s/x", "clientSecret": "a/b+c=d"})
    assert link == "https://s/x?cs=a%2Fb%2Bc%3Dd"


# ------------------------------------------------------ single signer send
def test_one_signer_creates_a_signing_session(store, recorder):
    rec = recorder({
        "sessionId": "sess-1", "transactionId": "tx-1",
        "url": "https://sign/s/sess-1", "clientSecret": "ss_secret_x",
        "inviteSent": True,
    })

    result = api.send(store, DOC, [signer()], profile="click_plus_otp",
                      owner_email="dono@ex.com.br", idempotency_key="idem-1")

    assert len(rec.calls) == 1
    call = rec.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/v1/signing-sessions")
    assert call["headers"]["Authorization"] == "Bearer at-test"
    assert call["headers"]["X-Idempotency-Key"] == "idem-1"

    payload = call["payload"]
    assert payload["policy"] == {"profile": "CLICK_PLUS_OTP"}
    assert payload["purpose"] == "DOCUMENT_SIGNATURE"
    assert payload["locale"] == "pt-BR"
    assert payload["document"] == {"content": "QkFTRTY0", "filename": "contrato.pdf"}
    # metadata.source is how a send is attributed to this channel.
    assert payload["metadata"] == {"source": "libreoffice", "lo_module": "writer"}
    assert payload["owner"] == {"email": "dono@ex.com.br"}

    assert result["kind"] == "session"
    assert result["id"] == "sess-1"
    assert result["links"][0]["url"] == "https://sign/s/sess-1?cs=ss_secret_x"
    assert result["links"][0]["inviteSent"] is True


def test_owner_is_omitted_when_there_is_no_sender_email(store, recorder):
    rec = recorder({"sessionId": "s", "url": "u", "clientSecret": "c"})
    api.send(store, DOC, [signer()])
    # Sending owner: {email: None} would be worse than omitting it; without
    # owner the API deliberately sends no invites at all.
    assert "owner" not in rec.calls[0]["payload"]


def test_digital_certificate_is_the_profile_for_a1_and_a3(store, recorder):
    rec = recorder({"sessionId": "s", "url": "u", "clientSecret": "c"})
    api.send(store, DOC, [signer()], profile="digital_certificate")
    # DIGITAL_SIGN_A1 is a step type and 400s as a policy profile.
    assert rec.calls[0]["payload"]["policy"]["profile"] == "DIGITAL_CERTIFICATE"


def test_an_unknown_profile_is_refused_before_any_request(store, recorder):
    recorder()
    with pytest.raises(api.ValidationError):
        api.send(store, DOC, [signer()], profile="DIGITAL_SIGN_A1")


def test_a_generated_idempotency_key_is_still_sent(store, recorder):
    rec = recorder({"sessionId": "s", "url": "u", "clientSecret": "c"})
    api.send(store, DOC, [signer()])
    assert rec.calls[0]["headers"]["X-Idempotency-Key"]


# ---------------------------------------------------------- envelope send
def test_two_signers_create_an_envelope_then_a_session_each(store, recorder):
    rec = recorder(
        {"envelopeId": "env-1"},
        {"url": "https://sign/s/a", "clientSecret": "ss_secret_a"},
        {"url": "https://sign/s/b", "clientSecret": "ss_secret_b", "inviteSent": True},
    )

    result = api.send(
        store, DOC,
        [signer(), signer(name="Bruno", email="bruno@ex.com.br", fiscal="12345678909")],
        order="SEQUENTIAL", idempotency_key="idem-9",
    )

    assert [c["url"].rsplit("/v1", 1)[1] for c in rec.calls] == [
        "/envelopes", "/envelopes/env-1/sessions", "/envelopes/env-1/sessions",
    ]
    assert rec.calls[0]["payload"]["signingMode"] == "SEQUENTIAL"
    assert rec.calls[0]["payload"]["totalSigners"] == 2

    # 1-based, and in order: in SEQUENTIAL mode this *is* the signing order.
    assert rec.calls[1]["payload"]["signerIndex"] == 1
    assert rec.calls[2]["payload"]["signerIndex"] == 2
    assert rec.calls[1]["payload"]["signer"]["name"] == "Ana"
    assert rec.calls[2]["payload"]["signer"]["name"] == "Bruno"

    # Distinct keys, so one retried send cannot collapse two sessions into one.
    assert rec.calls[1]["headers"]["X-Idempotency-Key"] == "idem-9:1"
    assert rec.calls[2]["headers"]["X-Idempotency-Key"] == "idem-9:2"

    assert result["kind"] == "envelope"
    assert result["id"] == "env-1"
    assert [link["url"] for link in result["links"]] == [
        "https://sign/s/a?cs=ss_secret_a", "https://sign/s/b?cs=ss_secret_b",
    ]


def test_a_missing_envelope_id_stops_before_adding_sessions(store, recorder):
    rec = recorder({})
    with pytest.raises(HttpError):
        api.send(store, DOC, [signer(), signer(email="b@ex.com.br", fiscal="12345678909")])
    assert len(rec.calls) == 1


# --------------------------------------------------------------- status
def test_session_status_is_normalised(store, recorder):
    recorder({"status": "COMPLETED", "transactionId": "tx-7"})
    status = api.status_of(store, "session", "sess-1")
    assert status["status"] == "COMPLETED"
    assert (status["completed"], status["total"]) == (1, 1)
    assert status["signed_available"] is True
    assert status["transactionId"] == "tx-7"


def test_envelope_status_is_normalised(store, recorder):
    recorder({"status": "PENDING", "completedSessions": 1, "totalSigners": 3})
    status = api.status_of(store, "envelope", "env-1")
    assert (status["completed"], status["total"]) == (1, 3)
    # The combined PDF only exists once the envelope completes.
    assert status["signed_available"] is False


# ------------------------------------------------------------- download
def test_envelope_download_uses_the_presigned_combined_url(store, recorder, monkeypatch):
    recorder({"status": "COMPLETED", "combinedSignedPdfUrl": "https://s3/combined"})
    fetched = {}

    def fake_get_bytes(url, timeout=None):
        fetched["url"] = url
        return b"%PDF-signed"

    monkeypatch.setattr(api, "get_bytes", fake_get_bytes)

    assert api.signed_pdf(store, "envelope", "env-1") == b"%PDF-signed"
    assert fetched["url"] == "https://s3/combined"


def test_download_before_completion_says_so(store, recorder):
    recorder({"status": "PENDING"})
    with pytest.raises(api.NotSignedYet):
        api.signed_pdf(store, "envelope", "env-1")


def test_session_download_resolves_the_transaction_then_the_signed_url(
    store, recorder, monkeypatch
):
    recorder(
        {"status": "COMPLETED", "transactionId": "tx-7"},
        {"transactionId": "tx-7", "signedUrl": "https://s3/signed", "expiresIn": 3600},
    )
    monkeypatch.setattr(api, "get_bytes", lambda url, timeout=None: b"%PDF-x")
    assert api.signed_pdf(store, "session", "sess-1") == b"%PDF-x"


def test_signed_filename_matches_the_nextcloud_convention():
    assert api.signed_filename("contrato.pdf") == "contrato-assinado.pdf"
    assert api.signed_filename("contrato.PDF") == "contrato-assinado.pdf"
    assert api.signed_filename("sem-extensao") == "sem-extensao-assinado.pdf"
    assert api.signed_filename(None) == "documento-assinado.pdf"


# --------------------------------------------------------------- cancel
def test_envelope_cancel_reports_preserved_signatures(store, recorder):
    rec = recorder({"alreadyCancelled": False, "cancelledCount": 2,
                    "preservedSignedCount": 1})
    result = api.cancel(store, "envelope", "env-1")
    assert rec.calls[0]["payload"] == {"reason": "cancelled_via_libreoffice"}
    # Already-collected signatures survive a cancel; the UI must be able to
    # say so rather than implying everything was destroyed.
    assert result["preservedSignedCount"] == 1
    assert result["cancelledCount"] == 2


def test_session_cancel_treats_409_as_already_cancelled(store, recorder):
    recorder(HttpError(409, "not active"))
    result = api.cancel(store, "session", "sess-1")
    # 409 means the session is not ACTIVE, which is the outcome the user
    # asked for. The envelope endpoint says the same thing with a 200.
    assert result["alreadyCancelled"] is True


def test_session_cancel_still_raises_on_a_real_error(store, recorder):
    recorder(HttpError(500, "boom"))
    with pytest.raises(HttpError):
        api.cancel(store, "session", "sess-1")


def test_stage_selects_the_host(store, recorder):
    oauth._access_tokens["hml"] = ("at-hml", 1 << 40)
    rec = recorder({"sessionId": "s", "url": "u", "clientSecret": "c"})
    api.send(store, DOC, [signer()], stage="hml")
    assert rec.calls[0]["url"].startswith("https://api-hml.signdocs.com.br/")
