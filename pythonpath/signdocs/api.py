# SPDX-License-Identifier: MPL-2.0
"""
SignDocs external-API client.

Same contract as the Nextcloud app and the ONLYOFFICE plugin, and the rules
below are the ones those two learned the hard way:

* one signer is a signing session, two or more is an envelope with a session
  added per signer, **sequentially** — the order is meaningful;
* `signerIndex` is 1-based;
* `policy.profile` takes `DIGITAL_CERTIFICATE` for both A1 and A3.
  `DIGITAL_SIGN_A1` is a *step type* and 400s as a profile;
* exactly one of `cpf`/`cnpj` per signer, classified by length, never inferred;
* the link is `{url}?cs={clientSecret}` — `url` alone is not a link;
* without `owner`, the API dispatches **no** invite emails at all.

Every create carries an `X-Idempotency-Key`. Quota is one global pool and is
not refunded on cancel, so a send the user retries after an error must not be
billed twice — which is why `send()` takes the key rather than minting a fresh
one each attempt.
"""

import hashlib
import json
import urllib.parse
import uuid

from signdocs import config, oauth, validators
from signdocs.httpclient import HttpError, get_bytes, request

#: UI value -> policy profile. Kept deliberately small: these are the four the
#: dialog offers, and anything else is a typo rather than a feature.
PROFILES = {
    "click_only": "CLICK_ONLY",
    "click_plus_otp": "CLICK_PLUS_OTP",
    "biometric": "BIOMETRIC",
    "digital_certificate": "DIGITAL_CERTIFICATE",
}

ORDERS = ("PARALLEL", "SEQUENTIAL")

#: The API enforces this with an explicit 400; fail before the upload.
MAX_SIGNERS = 100

SOURCE = "libreoffice"


class ValidationError(Exception):
    """Caught before anything is sent. Message is user-facing pt-BR."""


class NotSignedYet(Exception):
    """Asked for the signed PDF before there is one."""


# ------------------------------------------------------------- transport
def _api(store, stage):
    return config.STAGES[stage or config.current_stage(store)]["api"]


def _call(store, method, path, payload=None, idempotency_key=None, stage=None):
    headers = {"Authorization": "Bearer " + oauth.access_token(store, stage)}
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    return request(_api(store, stage) + path, method, body, headers)


# --------------------------------------------------------------- signers
def build_signer(signer, index):
    """
    Shape one signer for the API.

    `userExternalId` is a stable hash of the e-mail so a re-send reuses the
    same identity instead of minting a second one. The `lo:` prefix marks the
    channel, matching `oo:` in the ONLYOFFICE plugin.
    """
    name = (signer.get("name") or "").strip()
    email = (signer.get("email") or "").strip()

    if email:
        digest = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()
        external_id = "lo:" + digest
    else:
        external_id = "lo:idx:%d" % index

    out = {"name": name, "userExternalId": external_id, "email": email or None}

    fiscal = validators.classify(signer.get("fiscal"))
    # Exactly one field, chosen by length. Inferring would let an 11-digit
    # value go out on the wire as a CNPJ.
    if fiscal.kind == "cpf":
        out["cpf"] = fiscal.digits
    elif fiscal.kind == "cnpj":
        out["cnpj"] = fiscal.digits
    return out


def validate_signers(signers):
    if not signers:
        raise ValidationError("Adicione pelo menos um signatário.")
    if len(signers) > MAX_SIGNERS:
        raise ValidationError(
            "São permitidos no máximo %d signatários por envio." % MAX_SIGNERS
        )

    seen = set()
    for position, signer in enumerate(signers, 1):
        if not (signer.get("name") or "").strip():
            raise ValidationError("Signatário %d: informe o nome." % position)

        email = (signer.get("email") or "").strip()
        if not validators.is_valid_email(email):
            raise ValidationError("Signatário %d: e-mail inválido." % position)
        if email.lower() in seen:
            raise ValidationError(
                "O e-mail %s aparece mais de uma vez." % email
            )
        seen.add(email.lower())

        fiscal = validators.classify(signer.get("fiscal"))
        if fiscal.kind is None:
            raise ValidationError(
                "Signatário %d: informe um CPF ou CNPJ." % position
            )
        if not fiscal.valid:
            raise ValidationError(
                "Signatário %d: %s inválido." % (position, fiscal.kind.upper())
            )


def signing_link(payload):
    """
    Assemble the per-signer link.

    Both halves are required. `url` on its own is not a working link, which is
    exactly why the Nextcloud app cannot show single-signer links: the PHP
    SDK's model drops `clientSecret`. Talking raw HTTP, we have both.
    """
    url = (payload or {}).get("url")
    secret = (payload or {}).get("clientSecret")
    if not url or not secret:
        return None
    return url + "?cs=" + urllib.parse.quote(secret, safe="")


def _metadata(document):
    # metadata is Record<string, string>; there is no first-class channel
    # field on the API, so `source` is how a send is attributed.
    return {"source": SOURCE, "lo_module": str(document.get("module") or "writer")}


def _document(document):
    return {
        "content": document["content"],
        "filename": document.get("filename") or "documento.pdf",
    }


# ------------------------------------------------------------------ send
def send(store, document, signers, profile="click_only", order="PARALLEL",
         owner_email=None, idempotency_key=None, stage=None):
    """
    Send the document for signature.

    Pass the same `idempotency_key` when retrying a failed send: quota is one
    global pool and is not refunded on cancel, so a fresh key on every attempt
    turns a network blip into a double charge.

    Blocking — worker thread only.
    """
    validate_signers(signers)
    if profile not in PROFILES:
        raise ValidationError("Tipo de assinatura desconhecido: %r" % profile)
    if order not in ORDERS:
        raise ValidationError("Ordem desconhecida: %r" % order)

    key = idempotency_key or str(uuid.uuid4())
    if len(signers) == 1:
        return _send_session(store, document, signers, profile, owner_email, key, stage)
    return _send_envelope(
        store, document, signers, profile, order, owner_email, key, stage
    )


def _send_session(store, document, signers, profile, owner_email, key, stage):
    payload = {
        "purpose": "DOCUMENT_SIGNATURE",
        "policy": {"profile": PROFILES[profile]},
        "signer": build_signer(signers[0], 0),
        "document": _document(document),
        "metadata": _metadata(document),
        "locale": "pt-BR",
    }
    if owner_email:
        payload["owner"] = {"email": owner_email}

    result = _call(store, "POST", "/v1/signing-sessions", payload, key, stage) or {}
    return {
        "kind": "session",
        "id": result.get("sessionId"),
        "transactionId": result.get("transactionId"),
        "links": [{
            "signerName": signers[0].get("name"),
            "signerEmail": signers[0].get("email"),
            "url": signing_link(result),
            "inviteSent": bool(result.get("inviteSent")),
        }],
    }


def _send_envelope(store, document, signers, profile, order, owner_email, key, stage):
    payload = {
        "signingMode": order,
        "totalSigners": len(signers),
        "document": _document(document),
        "metadata": _metadata(document),
        "locale": "pt-BR",
    }
    if owner_email:
        payload["owner"] = {"email": owner_email}

    envelope = _call(store, "POST", "/v1/envelopes", payload, key, stage) or {}
    envelope_id = envelope.get("envelopeId")
    if not envelope_id:
        raise HttpError(502, "O servidor não devolveu um envelopeId.")

    links = []
    path = "/v1/envelopes/" + urllib.parse.quote(str(envelope_id), safe="") + "/sessions"
    # One at a time, never concurrently: in SEQUENTIAL mode the order in which
    # sessions are added is the signing order.
    for index, signer in enumerate(signers):
        session = _call(store, "POST", path, {
            "signer": build_signer(signer, index),
            "policy": {"profile": PROFILES[profile]},
            # 1-based: 1..totalSigners.
            "signerIndex": index + 1,
            "purpose": "DOCUMENT_SIGNATURE",
        }, "%s:%d" % (key, index + 1), stage) or {}
        links.append({
            "signerName": signer.get("name"),
            "signerEmail": signer.get("email"),
            "url": signing_link(session),
            "inviteSent": bool(session.get("inviteSent")),
        })

    return {
        "kind": "envelope",
        "id": envelope_id,
        "transactionId": None,
        "links": links,
    }


# ---------------------------------------------------------------- status
def session_status(store, session_id, stage=None):
    return _call(
        store, "GET",
        "/v1/signing-sessions/" + urllib.parse.quote(str(session_id), safe="") + "/status",
        None, None, stage,
    ) or {}


def get_envelope(store, envelope_id, stage=None):
    return _call(
        store, "GET",
        "/v1/envelopes/" + urllib.parse.quote(str(envelope_id), safe=""),
        None, None, stage,
    ) or {}


def status_of(store, kind, ident, stage=None):
    """
    One shape for both flavours, so the tracking dialog does not have to care.

    Returns {status, completed, total, signed_available, transactionId}.
    """
    if kind == "envelope":
        raw = get_envelope(store, ident, stage)
        return {
            "status": raw.get("status"),
            "completed": raw.get("completedSessions") or 0,
            "total": raw.get("totalSigners") or 0,
            # Only present once the envelope is COMPLETED.
            "signed_available": bool(raw.get("combinedSignedPdfUrl")),
            "transactionId": None,
            "raw": raw,
        }

    raw = session_status(store, ident, stage)
    status = raw.get("status")
    return {
        "status": status,
        "completed": 1 if status == "COMPLETED" else 0,
        "total": 1,
        "signed_available": status == "COMPLETED",
        "transactionId": raw.get("transactionId"),
        "raw": raw,
    }


# -------------------------------------------------------------- download
def signed_pdf(store, kind, ident, transaction_id=None, stage=None):
    """
    Fetch the signed PDF as bytes.

    Both paths end at a presigned S3 URL, which is fetched with no
    Authorization header — S3 rejects a request carrying both a query
    signature and an auth header.
    """
    if kind == "envelope":
        raw = get_envelope(store, ident, stage)
        url = raw.get("combinedSignedPdfUrl")
        if not url:
            raise NotSignedYet(
                "O documento combinado ainda não está disponível. "
                "Ele é gerado quando todos os signatários concluem."
            )
        return get_bytes(url)

    tx = transaction_id
    if not tx:
        tx = session_status(store, ident, stage).get("transactionId")
    if not tx:
        raise NotSignedYet("Ainda não há documento assinado para este envio.")

    result = _call(
        store, "GET",
        "/v1/transactions/" + urllib.parse.quote(str(tx), safe="") + "/download",
        None, None, stage,
    ) or {}
    url = result.get("signedUrl")
    if not url:
        raise NotSignedYet("Ainda não há documento assinado para este envio.")
    return get_bytes(url)


def signed_filename(original):
    """`contrato.pdf` -> `contrato-assinado.pdf`, matching the Nextcloud app."""
    name = original or "documento.pdf"
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    return name + "-assinado.pdf"


# ---------------------------------------------------------------- cancel
def cancel(store, kind, ident, stage=None):
    """
    Cancel a send.

    The two endpoints disagree about repeat calls — envelope cancel is
    idempotent and returns `alreadyCancelled`, session cancel raises 409 for
    any status other than ACTIVE — so both are normalised to the same shape.
    A 409 is treated as success because "already cancelled" is the outcome the
    user asked for.

    Signatures already collected are preserved, not destroyed; the count comes
    back in `preservedSignedCount` and the UI should say so.
    """
    if kind == "envelope":
        path = "/v1/envelopes/" + urllib.parse.quote(str(ident), safe="") + "/cancel"
        result = _call(store, "POST", path,
                       {"reason": "cancelled_via_libreoffice"}, None, stage) or {}
        return {
            "alreadyCancelled": bool(result.get("alreadyCancelled")),
            "cancelledCount": result.get("cancelledCount") or 0,
            "preservedSignedCount": result.get("preservedSignedCount") or 0,
        }

    path = "/v1/signing-sessions/" + urllib.parse.quote(str(ident), safe="") + "/cancel"
    try:
        result = _call(store, "POST", path, None, None, stage) or {}
    except HttpError as exc:
        if exc.status == 409:
            return {"alreadyCancelled": True, "cancelledCount": 0,
                    "preservedSignedCount": 0}
        raise
    return {
        "alreadyCancelled": bool(result.get("alreadyCancelled")),
        "cancelledCount": result.get("cancelledCount") or 1,
        "preservedSignedCount": result.get("preservedSignedCount") or 0,
    }
