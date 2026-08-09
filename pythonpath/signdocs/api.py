# SPDX-License-Identifier: MPL-2.0
"""
Client for the SignDocs LibreOffice add-on tier.

The extension talks to `/libreoffice/*`, never to the public `/v1/*` API. The
add-on Lambdas hold the channel's API credential in Secrets Manager and call
upstream on our behalf; what travels from here is a Cognito ID token that
identifies the user and grants no API access on its own.

That indirection moves several rules server-side, and this module must not
try to reimplement them:

* **`owner` is set by the server** from the verified identity. Sending one
  from here would be ignored, and the sender field exists only to be recorded
  and to decide whether an invite goes out.
* **The signing order can be overridden.** With a certificate profile the
  server forces SEQUENTIAL, because the A1 path loads the previous signer's
  output; it reports `signingModeForced` so we can say so.
* **Idempotency is mandatory.** The server rejects a create without a key
  rather than silently double-billing a retry.

The public surface — `send`, `status_of`, `cancel`, `signed_pdf`,
`signed_filename` — is unchanged from the direct-API version on purpose, so
the whole dialog layer is untouched by this rework.
"""

import hashlib
import json
import urllib.parse
import uuid

from signdocs import config, oauth, validators
from signdocs.httpclient import HttpError, get_bytes, request

#: UI value -> policy profile.
#: Signature profiles this client will send.
#:
#: BIOMETRIC is deliberately absent although the API accepts it. The profile
#: is provisioned per tenant by an administrator and has no live clients, so
#: offering it in a desktop dropdown hands the user a choice that fails at
#: send time for a reason they cannot see or fix. Re-adding it means granting
#: it on the shared libreoffice tenant and validating end to end first, not
#: putting it back in the list and finding out afterwards.
#:
#: Kept in step with strings.PROFILE_ORDER; a test asserts the two agree.
PROFILES = {
    "click_only": "CLICK_ONLY",
    "click_plus_otp": "CLICK_PLUS_OTP",
    "digital_certificate": "DIGITAL_CERTIFICATE",
}

ORDERS = ("PARALLEL", "SEQUENTIAL")

#: The API enforces this with an explicit 400; fail before the upload.
MAX_SIGNERS = 100


class ValidationError(Exception):
    """Caught before anything is sent. Message is user-facing pt-BR."""


class NotSignedYet(Exception):
    """Asked for the signed PDF before there is one."""


# ------------------------------------------------------------- transport
def _call(store, method, path, payload=None, stage=None):
    headers = {"Authorization": "Bearer " + oauth.bearer_token(store, stage)}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return request(config.api_base(store, stage) + path, method, body, headers)


# --------------------------------------------------------------- signers
def build_signer(signer, index):
    """
    Shape one signer for the add-on tier.

    `userExternalId` is a stable hash of the e-mail so a re-send reuses the
    same identity rather than minting a second one.
    """
    name = (signer.get("name") or "").strip()
    email = (signer.get("email") or "").strip()

    if email:
        external_id = "lo:" + hashlib.sha256(email.lower().encode("utf-8")).hexdigest()
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
            raise ValidationError("O e-mail %s aparece mais de uma vez." % email)
        seen.add(email.lower())

        fiscal = validators.classify(signer.get("fiscal"))
        if fiscal.kind is None:
            raise ValidationError("Signatário %d: informe um CPF ou CNPJ." % position)
        if not fiscal.valid:
            raise ValidationError(
                "Signatário %d: %s inválido." % (position, fiscal.kind.upper())
            )


def signing_link(url, secret):
    """
    Assemble the per-signer link.

    Both halves are required — `url` alone is not a working link. The add-on
    tier returns them as separate fields, so the join happens here.
    """
    if not url:
        return None
    if not secret:
        return url
    return url + "?cs=" + urllib.parse.quote(secret, safe="")


def _document(document):
    return {
        "content": document["content"],
        "filename": document.get("filename") or "documento.pdf",
        "module": document.get("module") or "writer",
    }


# ------------------------------------------------------------------ send
def send(store, document, signers, profile="click_only", order="PARALLEL",
         idempotency_key=None, stage=None):
    """
    Send the document for signature.

    Pass the same `idempotency_key` when retrying a failed send: the server
    requires one, and quota is a single pool that is not refunded on cancel,
    so a fresh key on every attempt would turn a network blip into a double
    charge.

    There is deliberately no `owner` parameter. The server sets it from the
    verified Cognito identity and ignores anything sent, which is what makes
    the ownership checks downstream meaningful — so accepting one here would
    only invite a caller to think it did something.

    Blocking — worker thread only.
    """
    validate_signers(signers)
    if profile not in PROFILES:
        raise ValidationError("Tipo de assinatura desconhecido: %r" % profile)
    if order not in ORDERS:
        raise ValidationError("Ordem desconhecida: %r" % order)

    key = idempotency_key or str(uuid.uuid4())
    if len(signers) == 1:
        return _send_session(store, document, signers, profile, key, stage)
    return _send_envelope(store, document, signers, profile, order, key, stage)


def _send_session(store, document, signers, profile, key, stage):
    result = _call(store, "POST", "/create-signing-session", {
        "document": _document(document),
        "signer": build_signer(signers[0], 0),
        "policy": {"profile": PROFILES[profile]},
        "purpose": "DOCUMENT_SIGNATURE",
        "__idempotencyKey": key,
    }, stage) or {}

    return {
        "kind": "session",
        "id": result.get("sessionId"),
        "transactionId": result.get("transactionId"),
        "profile": profile,
        "links": [{
            "signerName": signers[0].get("name"),
            "signerEmail": signers[0].get("email"),
            # None when the server withheld it: a CLICK_ONLY link for someone
            # other than the sender is delivered by e-mail only, because on its
            # own it is enough to sign. Absent, not an error.
            "url": signing_link(result.get("url"), result.get("clientSecret")),
            "inviteSent": bool(result.get("inviteSent")),
        }],
    }


def _send_envelope(store, document, signers, profile, order, key, stage):
    result = _call(store, "POST", "/create-envelope", {
        "document": _document(document),
        "signers": [
            dict(build_signer(s, i), profile=PROFILES[profile])
            for i, s in enumerate(signers)
        ],
        "signingMode": order,
        "__idempotencyKey": key,
    }, stage) or {}

    by_email = {}
    for entry in result.get("signers") or []:
        by_email[(entry.get("email") or "").lower()] = entry

    links = []
    for signer in signers:
        entry = by_email.get((signer.get("email") or "").lower(), {})
        links.append({
            "signerName": signer.get("name"),
            "signerEmail": signer.get("email"),
            # Ready to open: the add-on tier joins the secret for this path,
            # because upstream add-session returns the URL and the secret as
            # two fields and `url` alone loads an error page. Nothing to join
            # here — and nothing that may be assumed either, so a link that
            # arrives without its secret arrives as None.
            "url": entry.get("url"),
            "inviteSent": bool(entry.get("inviteSent")),
        })

    return {
        "kind": "envelope",
        "id": result.get("envelopeId"),
        "transactionId": None,
        "profile": profile,
        "links": links,
        # True when the server overrode PARALLEL because a certificate
        # profile is in play; the UI should say so rather than let the user
        # believe their choice was honoured.
        "signingModeForced": bool(result.get("signingModeForced")),
        "signingMode": result.get("signingMode") or order,
    }


# ---------------------------------------------------------------- status
def status_of(store, kind, ident, stage=None):
    """One shape for both flavours, so the tracking dialog need not care."""
    quoted = urllib.parse.quote(str(ident), safe="")

    if kind == "envelope":
        raw = _call(store, "GET", "/envelope-status/" + quoted, None, stage) or {}
        total = raw.get("totalSigners") or 0
        completed = raw.get("completedSessions") or 0
        return {
            "status": raw.get("status"),
            "completed": completed,
            "total": total,
            # The add-on tier gates the download itself, so availability is
            # simply "everything is done".
            "signed_available": raw.get("status") == "COMPLETED",
            "transactionId": None,
            "signers": _signers_from_envelope(raw),
            "raw": raw,
        }

    raw = _call(store, "GET", "/session-status/" + quoted, None, stage) or {}
    status = raw.get("status")
    return {
        "status": status,
        "completed": 1 if status == "COMPLETED" else 0,
        "total": 1,
        "signed_available": status == "COMPLETED",
        "transactionId": raw.get("transactionId"),
        # One signer, whose state is the session's own. No name on this
        # payload — the caller fills it in from what it recorded at send time.
        "signers": [{
            "name": None,
            "email": raw.get("signerEmail"),
            "status": status,
            "index": 1,
        }],
        "raw": raw,
    }


def _signers_from_envelope(raw):
    """
    One row per signer, in signing order.

    The add-on tier passes the upstream envelope payload through whole, so
    `sessions` is already here — "3 of 5 signed" was being computed from it and
    the rest thrown away, which is why the tracker could say how many had
    signed but never which ones.

    Sorted by `signerIndex` because for a SEQUENTIAL envelope the order *is*
    information: it says who is being waited on and who has not been asked yet.
    """
    rows = []
    for entry in raw.get("sessions") or []:
        rows.append({
            "name": entry.get("signerName"),
            "email": entry.get("signerEmail"),
            "status": entry.get("status"),
            "index": entry.get("signerIndex") or 0,
        })
    rows.sort(key=lambda r: r["index"] or 0)
    return rows


# -------------------------------------------------------------- download
def signed_pdf(store, kind, ident, transaction_id=None, stage=None):
    """
    Fetch the signed PDF as bytes.

    The add-on tier returns a presigned URL rather than the bytes, so a large
    document never travels through Lambda. It refuses to hand back the
    unsigned original, so a 409 here genuinely means "not signed yet" — the
    caller can trust that distinction.
    """
    quoted = urllib.parse.quote(str(ident), safe="")
    path = ("/signed-document/envelope/" + quoted) if kind == "envelope" \
        else ("/signed-document/" + quoted)

    try:
        result = _call(store, "GET", path, None, stage) or {}
    except HttpError as exc:
        if exc.status in (404, 409):
            raise NotSignedYet(
                "O documento assinado ainda não está disponível."
            )
        raise

    url = result.get("signedUrl")
    if not url:
        raise NotSignedYet("O documento assinado ainda não está disponível.")
    # Presigned: fetched with no Authorization header, or S3 rejects it.
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

    Both endpoints are normalised to one shape. Signatures already collected
    are preserved, not destroyed; the count comes back in
    `preservedSignedCount` and the UI should say so.
    """
    quoted = urllib.parse.quote(str(ident), safe="")
    path = ("/cancel-envelope/" + quoted) if kind == "envelope" \
        else ("/cancel-session/" + quoted)

    try:
        result = _call(store, "POST", path, {}, stage) or {}
    except HttpError as exc:
        # Session cancel 409s when the session is not ACTIVE, which is the
        # outcome the user asked for. A 404 means it has already gone.
        if exc.status in (404, 409):
            return {"alreadyCancelled": True, "cancelledCount": 0,
                    "preservedSignedCount": 0}
        raise

    return {
        "alreadyCancelled": bool(result.get("alreadyCancelled")),
        "cancelledCount": result.get("cancelledCount") or 0,
        "preservedSignedCount": result.get("preservedSignedCount") or 0,
    }


# ------------------------------------------------------------- sign link
def sign_link(store, kind, ident, stage=None):
    """
    A fresh signing link for the signed-in account's own signature.

    The link is never stored — not here, not in the profile, not in the
    history. It is a bearer credential, and the history file is plaintext JSON
    on disk. The server mints a new one on each call instead, so "get me back
    to my document" costs a round trip rather than a stored secret.

    The server decides whether the caller is entitled to it, and returns 404
    when they are not. Envelopes are addressed by envelope id: the server picks
    out the caller's own session, so this side never has to enumerate anyone
    else's.

    Returns None when there is nothing to open — already signed, cancelled, or
    not the caller's to sign.
    """
    quoted = urllib.parse.quote(str(ident), safe="")
    path = ("/self-sign-link/envelope/" + quoted) if kind == "envelope" \
        else ("/self-sign-link/" + quoted)

    try:
        result = _call(store, "POST", path, {}, stage) or {}
    except HttpError as exc:
        # 404 is "not yours, or gone"; 409 is "no longer signable". Both are
        # answers rather than faults, and the caller shows a message.
        if exc.status in (404, 409):
            return None
        raise

    return result.get("url") or None


def init_session(store, stage=None):
    """
    Register the user with the channel-quota service and read their plan.

    Called once after sign-in so the UI can show the remaining allowance
    before the user builds a whole send they have no quota for.
    """
    return _call(store, "POST", "/init-session", {}, stage) or {}


#: The add-on tier caps each list per call; sending more is silently truncated
#: server-side, so the client splits instead.
PENDING_BATCH = 25


def pending_statuses(store, session_ids=(), envelope_ids=(), stage=None):
    """
    Status of many sends in one call.

    The per-row alternative is one HTTPS round trip per pending item, which on
    a desktop connection is what stands between opening a list and seeing it.

    Returns `{"sessions": [...], "envelopes": [...], "droppedIds": [...]}`.
    `droppedIds` are ids the server would not answer for — someone else's, or
    aged out — and the caller must not read that as "still pending": it is the
    server declining to say, which is different from saying "active".
    """
    payload = {
        "sessionIds": list(session_ids)[:PENDING_BATCH],
        "envelopeIds": list(envelope_ids)[:PENDING_BATCH],
    }
    result = _call(store, "POST", "/pending-statuses", payload, stage) or {}
    return {
        "sessions": result.get("sessions") or [],
        "envelopes": result.get("envelopes") or [],
        "droppedIds": result.get("droppedIds") or [],
    }


# ---------------------------------------------------------------- upgrade
#: What /create-checkout accepts. Kept in step with VALID_PLANS in
#: external-api/src/handlers/libreoffice/create-checkout.ts — a plan name this
#: side does not match is a 400, not a wrong price.
PLANS = (
    {"name": "Iniciante 20", "docs": 20, "monthly": "R$ 19,90"},
    {"name": "Iniciante 80", "docs": 80, "monthly": "R$ 44,90"},
    {"name": "Avançado 80", "docs": 80, "monthly": "R$ 54,90"},
    {"name": "Avançado 200", "docs": 200, "monthly": "R$ 124,90"},
)


def has_fiscal(store, stage=None):
    """
    Whether the account already carries CPF/CNPJ and name.

    Asked before checkout so the fiscal form is only shown to people who need
    it. Never returns the stored values.
    """
    result = _call(store, "POST", "/prepare-fiscal", {}, stage) or {}
    return bool(result.get("hasFiscal"))


def create_checkout(store, plan, frequency="Mensal", fiscal=None, stage=None):
    """
    A Stripe Checkout URL for `plan`, to be opened in the user's browser.

    The extension cannot host a payment form and must not try: card details
    belong in the browser, on Stripe's own page, never in a UNO dialog.
    """
    payload = {"plan": plan, "frequency": frequency}
    if fiscal:
        payload["fiscal"] = fiscal
    result = _call(store, "POST", "/create-checkout", payload, stage) or {}
    return result.get("checkoutUrl")


# ---------------------------------------------------------------- policies
#: The two policies a user must accept before anything can be sent. DPA is
#: absent on purpose: its click-through was retired across every channel, so
#: asking for it here would reintroduce a gate the business removed.
POLICY_ACTIONS = ("CONSENT_TOS", "CONSENT_PRIVACY")


def policy_status(store, stage=None):
    """
    Which policies the signed-in account still has to accept.

    Returns the server's response, whose `stale` list is the part that
    matters: it names the policies whose accepted version is missing or
    behind. An empty `stale` is the only thing that permits a send.
    """
    result = _call(store, "POST", "/policy-consent/status", {}, stage) or {}
    return {
        "required": result.get("required") or {},
        "urls": result.get("urls") or {},
        "accepted": result.get("accepted") or {},
        "needsAcceptance": bool(result.get("needsAcceptance")),
        "stale": [a for a in (result.get("stale") or [])
                  if a in POLICY_ACTIONS],
    }


def policy_accept(store, action, version, url=None, stage=None):
    """
    Record acceptance of one policy at one version.

    The caller's identity is taken from the ID token server-side and is not
    sent here: this record is the evidence that a named person accepted a
    named version, so the client does not get to nominate who that was.
    """
    if action not in POLICY_ACTIONS:
        raise ValidationError("Política desconhecida: %r" % action)
    if not version:
        raise ValidationError("Versão da política ausente")
    payload = {"action": action, "version": version}
    if url:
        payload["url"] = url
    return _call(store, "POST", "/policy-consent/accept", payload, stage) or {}
