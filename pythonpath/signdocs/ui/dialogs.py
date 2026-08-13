# SPDX-License-Identifier: MPL-2.0
"""
The dialogs, and the flow between them.

Signers are managed through a list plus a small add/edit sub-dialog rather
than N inline rows. UNO dialogs have no scrolling container, so inline rows
would either cap the signer count far below the API's 100 or grow the window
off the screen. A list handles 100 signers in the same space as one.

Everything here runs on the main thread. Network and export work goes through
`busy()`, which keeps the office responsive and — just as important — gives
the user something that visibly finishes.
"""

import datetime
import os
import threading
import urllib.parse
import uuid

from signdocs import api, config, history, intake, oauth, sync, validators
from signdocs.ui import async_work, msgbox, strings
from signdocs.ui.widgets import (
    BUTTON_H,
    BUTTON_W,
    MARGIN,
    ROW,
    Dialog,
    copy_to_clipboard,
    parent_window,
)

PROFILE_KEYS = strings.PROFILE_ORDER
ORDER_KEYS = ("PARALLEL", "SEQUENTIAL")


# ------------------------------------------------------------------- busy
def busy(ctx, parent, message, work):
    """
    Run `work()` off the main thread behind a modal "please wait" dialog.

    The worker is started through `on_main_thread` rather than directly, so it
    cannot finish before `execute()` has begun: a callback arriving first
    would call `endExecute` on a dialog that is not yet running, and the
    dialog would then stay up forever. Modal dialogs pump a nested event loop,
    which is what lets the completion callback be delivered at all.
    """
    dialog = Dialog(ctx, strings.Strings()("app"), 190, 46)
    dialog.label("msg", MARGIN, 16, 190 - 2 * MARGIN, 10, message)

    holder = {}

    def done(result):
        holder["result"] = result
        dialog.finish(True)

    async_work.on_main_thread(ctx, lambda: async_work.run(ctx, work, done))
    dialog.show(parent)

    return holder.get("result")


def _report(ctx, frame, result, s):
    """Show a background failure. Returns True when the work succeeded."""
    if result is None:
        # The dialog was dismissed while the job was still running.
        return False
    if result.ok:
        return True
    msgbox.error(ctx, frame, str(result.error) or s("error"), s("app"))
    return False


# ---------------------------------------------------------------- connect
def ensure_connected(ctx, frame, store, s):
    if oauth.is_connected(store):
        return True

    dialog = Dialog(ctx, s("connect_title"), 230, 78)
    dialog.label("t", MARGIN, MARGIN, 230 - 2 * MARGIN, 24, s("not_connected"),
                 MultiLine=True)
    stage = config.current_stage(store)
    dialog.label("e", MARGIN, MARGIN + 26, 230 - 2 * MARGIN, 10,
                 "%s: %s" % (s("stage"), stage))
    dialog.button("cancel", 230 - 2 * BUTTON_W - 2 * MARGIN, 56, BUTTON_W,
                  BUTTON_H, s("cancel"), lambda: dialog.finish(False))
    dialog.button("ok", 230 - BUTTON_W - MARGIN, 56, BUTTON_W, BUTTON_H,
                  s("connect"), lambda: dialog.finish(True))

    if not dialog.show(parent_window(frame)):
        return False

    # Open the login page in the same language as the office UI.
    lang = config.LOGIN_LANG.get(s.lang, config.DEFAULT_LOGIN_LANG)
    result = busy(ctx, parent_window(frame), s("busy_connect"),
                  lambda: oauth.connect(store, stage, lang=lang))
    return _report(ctx, frame, result, s)


# ----------------------------------------------------------- signer dialog
def _blocked_signer_email(state):
    """
    The signed-in address, when it may not be a signer.

    A subuser is not a signatory identity — when a subuser signs, they sign
    against the master's row, never one of their own. The server refuses such a
    send outright; this only saves the user from discovering it after building
    a whole send and uploading a PDF.

    Only the account's own address can be checked here. Whether somebody
    *else's* address belongs to a subuser is a directory question, and the
    answer lives on the server.
    """
    user = ((state or {}).get("quota") or {}).get("user") or {}
    return user.get("email", "") if user.get("isSubuser") else ""


def recent_signers_dialog(ctx, frame, s, recents):
    """
    Pick somebody already sent to. Returns the signer dict, or None.

    Worth the extra window because the alternative is retyping a CPF, and a
    CPF typed from memory is the one field here where a slip is not merely
    undeliverable — it attributes the signature to a different person, and the
    validator cannot tell, because the wrong number checks out too.
    """
    width = 300
    height = 150
    dialog = Dialog(ctx, s("recent_title"), width, height)
    inner = width - 2 * MARGIN

    dialog.listctl("people", MARGIN, MARGIN, inner, height - 46,
                   [_recent_line(r) for r in recents])
    if recents:
        dialog.model.getByName("people").SelectedItems = (0,)

    def use():
        index = dialog.selected_index("people")
        if 0 <= index < len(recents):
            # A copy: the picker seeds the form, and editing the name there
            # must not rewrite the history row it came from.
            dialog.finish(dict(recents[index]))

    y = height - BUTTON_H - MARGIN
    dialog.button("cancel", width - 2 * BUTTON_W - 2 * MARGIN, y, BUTTON_W,
                  BUTTON_H, s("cancel"), lambda: dialog.finish(None))
    dialog.button("use", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("use"), use)
    return dialog.show(parent_window(frame))


def _recent_line(signer):
    parts = [(signer.get("name") or "").strip() or (signer.get("email") or "")]
    email = (signer.get("email") or "").strip()
    if email and email != parts[0]:
        parts.append(email)
    fiscal = validators.format_cpf_cnpj(signer.get("fiscal"))
    if fiscal:
        parts.append(fiscal)
    return " — ".join(parts)


def signer_dialog(ctx, frame, s, signer=None, blocked_email="", recents=(),
                  taken_fiscal=()):
    """Add or edit one signer. Returns the dict, or None if cancelled."""
    width = 220
    dialog = Dialog(ctx, s("signer_title"), width, 88)
    field_w = width - MARGIN - 66

    dialog.label("l1", MARGIN, MARGIN + 2, 60, 10, s("name"))
    dialog.edit("name", 66, MARGIN, field_w, 12, (signer or {}).get("name", ""))
    dialog.label("l2", MARGIN, MARGIN + ROW + 2, 60, 10, s("email"))
    dialog.edit("email", 66, MARGIN + ROW, field_w, 12,
                (signer or {}).get("email", ""))
    dialog.label("l3", MARGIN, MARGIN + 2 * ROW + 2, 60, 10, s("fiscal"))
    dialog.edit("fiscal", 66, MARGIN + 2 * ROW, field_w, 12,
                (signer or {}).get("fiscal", ""))
    dialog.label("err", MARGIN, MARGIN + 3 * ROW + 2, width - 2 * MARGIN, 10, "")

    def accept():
        name = dialog.get("name").strip()
        email = dialog.get("email").strip()
        fiscal = dialog.get("fiscal").strip()

        # Validate here, not at send time: an invalid CPF discovered after the
        # upload is a wasted round trip and a worse message.
        if not name:
            dialog.model.getByName("err").Label = s("name")
            return
        if not validators.is_valid_email(email):
            dialog.model.getByName("err").Label = s("email")
            return
        # Caught here so it costs a keystroke rather than a PDF upload. The
        # server refuses it either way — this is a courtesy, not the gate.
        if oauth.matches_account(email, blocked_email):
            dialog.model.getByName("err").Label = s("subuser_not_signer")
            return
        classified = validators.classify(fiscal)
        if classified.kind is None or not classified.valid:
            dialog.model.getByName("err").Label = s("fiscal")
            return
        # One CPF cannot be two signatories: it is what the evidence
        # attributes the signature to, so a repeat is one person holding two
        # links. Compared on digits, since the same number can be typed with
        # or without punctuation. The server refuses it too.
        if validators.only_digits(fiscal) in taken_fiscal:
            dialog.model.getByName("err").Label = s("duplicate_fiscal")
            return
        dialog.finish({"name": name, "email": email, "fiscal": fiscal})

    def pick_recent():
        chosen = recent_signers_dialog(ctx, frame, s, list(recents))
        if not chosen:
            return
        # Seeds the fields rather than finishing the dialog: the CPF is the
        # value worth not retyping, but the person may well be here to change
        # the name, and they still have to pass the same validation.
        dialog.set("name", chosen.get("name") or "")
        dialog.set("email", chosen.get("email") or "")
        dialog.set("fiscal", chosen.get("fiscal") or "")
        dialog.model.getByName("err").Label = ""

    if recents:
        dialog.button("recent", MARGIN, 68, BUTTON_W + 12, BUTTON_H,
                      s("recent"), pick_recent)

    dialog.button("cancel", width - 2 * BUTTON_W - 2 * MARGIN, 68, BUTTON_W,
                  BUTTON_H, s("cancel"), lambda: dialog.finish(None))
    dialog.button("ok", width - BUTTON_W - MARGIN, 68, BUTTON_W, BUTTON_H,
                  s("ok"), accept)
    return dialog.show(parent_window(frame))


def _taken_fiscal(state, skip=None):
    """
    Fiscal numbers already spoken for, as digits.

    `skip` is the row being edited: re-saving somebody without changing their
    CPF must not collide with themselves.
    """
    return {
        validators.only_digits(sg.get("fiscal"))
        for i, sg in enumerate(state.get("signers") or [])
        if i != skip and validators.only_digits(sg.get("fiscal"))
    }


def _signer_line(index, signer):
    label = "%d. %s" % (index + 1, signer.get("name") or "")
    if signer.get("email"):
        label += " — " + signer["email"]
    fiscal = validators.format_cpf_cnpj(signer.get("fiscal"))
    if fiscal:
        label += " — " + fiscal
    return label


# ------------------------------------------------------------- consent
#: Wire action -> the label and the key naming its URL and version.
POLICY_LABELS = {
    "CONSENT_TOS": ("consent_tos", "tos"),
    "CONSENT_PRIVACY": ("consent_privacy", "privacy"),
}


def consent_dialog(ctx, frame, s, status):
    """
    Ask the user to accept the policies the server reports as stale.

    Each one gets its own Open button, because acceptance has to be of a
    document the person could actually read: a dialog that only says "I
    accept" and offers no way to see what is being accepted is not consent,
    and the record it produces would not be worth much either.

    Returns True only on an explicit click of the accept button.
    """
    stale = status.get("stale") or []
    width = 320
    height = 76 + 16 * len(stale)
    dialog = Dialog(ctx, s("consent_title"), width, height)
    inner = width - 2 * MARGIN

    dialog.label("intro", MARGIN, MARGIN, inner, 20, s("consent_intro"),
                 MultiLine=True)

    y = MARGIN + 26
    for index, action in enumerate(stale):
        label_key, url_key = POLICY_LABELS.get(action, (None, None))
        if label_key is None:
            continue
        version = (status.get("required") or {}).get(url_key) or ""
        url = (status.get("urls") or {}).get(url_key)
        text = s(label_key)
        if version:
            text = "%s (v%s)" % (text, version)
        dialog.label("p%d" % index, MARGIN, y + 2, inner - BUTTON_W - 8, 10, text)
        if url:
            dialog.button(
                "open%d" % index, width - BUTTON_W - MARGIN, y, BUTTON_W,
                BUTTON_H - 2, s("consent_open"),
                lambda u=url: _open_in_browser(ctx, u))
        y += 16

    y = height - BUTTON_H - MARGIN
    dialog.button("cancel", MARGIN, y, BUTTON_W, BUTTON_H, s("cancel"),
                  lambda: dialog.finish(False))
    dialog.button("accept", width - (BUTTON_W + 40) - MARGIN, y, BUTTON_W + 40,
                  BUTTON_H, s("consent_accept"), lambda: dialog.finish(True))
    return bool(dialog.show(parent_window(frame)))


def _open_in_browser(ctx, url):
    """
    Open a URL in the browser, or put it on the clipboard if there is none.

    webbrowser.open returns False rather than raising on a desktop with no
    browser configured, and silently failing would leave the user asked to
    accept a policy they were given no way to read — or, for a signing link,
    stranded on a document they were told they could sign.

    Returns True when the browser actually opened.
    """
    opened = False
    try:
        import webbrowser
        opened = webbrowser.open(url)
    except Exception:
        opened = False
    if not opened:
        copy_to_clipboard(ctx, url)
    return opened


def ensure_policies_accepted(ctx, frame, store, s, stage):
    """
    True when the account may send. Blocks until the policies are accepted.

    Fails **closed**, which is the opposite of how the quota reading behaves,
    and deliberately: the quota is enforced server-side whatever the extension
    believes, whereas nothing server-side refuses a send from someone who has
    not accepted the terms. So if acceptance cannot be confirmed, this is the
    only thing standing in the way, and a network error must not be treated as
    a yes.
    """
    probe = busy(ctx, parent_window(frame), s("busy_consent"),
                 lambda: api.policy_status(store, stage=stage))
    if probe is None or not probe.ok:
        msgbox.error(ctx, frame, s("consent_unavailable"), s("app"))
        return False

    status = probe.value
    stale = status.get("stale") or []
    if not stale:
        return True

    if not consent_dialog(ctx, frame, s, status):
        msgbox.info(ctx, frame, s("consent_declined"), s("app"))
        return False

    def record():
        required = status.get("required") or {}
        urls = status.get("urls") or {}
        for action in stale:
            _, key = POLICY_LABELS.get(action, (None, None))
            if key is None:
                continue
            api.policy_accept(store, action, required.get(key),
                              url=urls.get(key), stage=stage)
        return True

    saved = busy(ctx, parent_window(frame), s("busy_consent_save"), record)
    # A failed write means no record exists, so the gate has not been passed.
    # Reporting success here would let the send proceed on an acceptance that
    # was never stored.
    return _report(ctx, frame, saved, s)


# -------------------------------------------------------------- upgrade
def fiscal_dialog(ctx, frame, s):
    """
    CPF/CNPJ and legal name, asked only when the account carries neither.

    `categoriaPfPj` is derived from the length rather than asked: the document
    already says which it is, and a mismatched pair — a CPF filed as PJ — is a
    billing record nobody would think to check.
    """
    width = 250
    height = 96
    dialog = Dialog(ctx, s("fiscal_title"), width, height)
    inner = width - 2 * MARGIN

    dialog.label("intro", MARGIN, MARGIN, inner, 18, s("fiscal_intro"),
                 MultiLine=True)
    dialog.label("l1", MARGIN, MARGIN + 26, 72, 10, s("fiscal"))
    dialog.edit("fiscal", 86, MARGIN + 24, inner - 78, 12)
    dialog.label("l2", MARGIN, MARGIN + 26 + ROW, 72, 10, s("legal_name"))
    dialog.edit("name", 86, MARGIN + 24 + ROW, inner - 78, 12)
    dialog.label("err", MARGIN, MARGIN + 28 + 2 * ROW, inner, 10, "")

    def accept():
        fiscal = dialog.get("fiscal").strip()
        name = dialog.get("name").strip()
        classified = validators.classify(fiscal)
        if classified.kind is None or not classified.valid:
            dialog.set_label("err", s("fiscal"))
            return
        if not name:
            dialog.set_label("err", s("legal_name"))
            return
        dialog.finish({
            "cpfCnpj": fiscal,
            "nomeRazaoSocial": name,
            "categoriaPfPj": "PF" if classified.kind == "cpf" else "PJ",
        })

    y = height - BUTTON_H - MARGIN
    dialog.button("cancel", width - 2 * BUTTON_W - 2 * MARGIN, y, BUTTON_W,
                  BUTTON_H, s("cancel"), lambda: dialog.finish(None))
    dialog.button("ok", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("ok"), accept)
    return dialog.show(parent_window(frame))


def run_upgrade(ctx, frame, store, s, stage):
    """
    Pick a plan, then hand off to Stripe in the browser.

    A desktop dialog cannot take a card and must not try — those details
    belong on Stripe's own page, over their TLS, inside their PCI scope. So
    the whole job here is choosing a plan and opening a URL.

    Without this, running out of allowance is simply a dead end: the send
    window can say "sem envios disponíveis" and offer nothing further, while a
    Drive user in the same position gets a plan picker.
    """
    width = 300
    height = 156
    dialog = Dialog(ctx, s("upgrade_title"), width, height)
    inner = width - 2 * MARGIN

    dialog.label("intro", MARGIN, MARGIN, inner, 10, s("upgrade_intro"))
    dialog.listctl("plans", MARGIN, MARGIN + 14, inner, 52,
                   [s("plan_row") % (p["name"], p["docs"], p["monthly"])
                    for p in api.PLANS])
    y = MARGIN + 70
    dialog.label("l1", MARGIN, y + 2, 60, 10, s("billing"))
    dialog.listbox("freq", 70, y, inner - 62, 12,
                   [s("monthly"), s("annual")], 0)

    def go():
        index = dialog.selected_index("plans")
        if index < 0:
            msgbox.error(ctx, frame, s("pick_a_plan"), s("app"))
            return
        plan = api.PLANS[index]["name"]
        frequency = ("Mensal", "Anual")[max(0, dialog.selected_index("freq"))]

        # Asked before the form is drawn, so the majority — anyone signing in
        # with an existing SignDocs account — never sees it at all.
        probe = busy(ctx, parent_window(frame), s("busy_checkout"),
                     lambda: api.has_fiscal(store, stage=stage))
        if not _report(ctx, frame, probe, s):
            return

        fiscal = None
        if not probe.value:
            fiscal = fiscal_dialog(ctx, frame, s)
            if fiscal is None:
                return

        result = busy(ctx, parent_window(frame), s("busy_checkout"),
                      lambda: api.create_checkout(store, plan, frequency,
                                                  fiscal, stage=stage))
        if not _report(ctx, frame, result, s):
            return
        url = result.value
        if not url:
            msgbox.error(ctx, frame, s("error"), s("app"))
            return

        dialog.finish(True)
        # webbrowser.open can fail on a minimal desktop with no
        # x-www-browser, and silently: it returns False rather than raising.
        # Left unhandled that strands someone one click from paying, so fall
        # back to handing them the link.
        opened = False
        try:
            import webbrowser
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        if opened:
            msgbox.info(ctx, frame, s("checkout_opened"), s("app"))
        else:
            copy_to_clipboard(ctx, url)
            msgbox.info(ctx, frame, "%s\n\n%s" % (s("checkout_link"), url),
                        s("app"))

    y = height - BUTTON_H - MARGIN
    dialog.button("cancel", width - 2 * BUTTON_W - 2 * MARGIN, y, BUTTON_W,
                  BUTTON_H, s("cancel"), lambda: dialog.finish(False))
    dialog.button("go", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("ok"), go)
    return dialog.show(parent_window(frame))


# ------------------------------------------------------------- send dialog
def send_dialog(ctx, frame, store, s, state):
    """
    Collect sender, signature type, order and signers.

    `state` is mutated in place and reused when the user comes back from the
    review screen, so Voltar restores every typed value. Rebuilding it would
    wipe the form — the same trap the ONLYOFFICE and Nextcloud implementations
    both call out.
    """
    width = 300
    inner = width - 2 * MARGIN

    # Shown before any effort is invested in the form, because that is the
    # only moment the number can still change what the user does. Omitted
    # entirely when the lookup failed: the send is allowed to proceed either
    # way, since the server is the authority on quota, and an empty row would
    # read as a rendering fault.
    quota_text = strings.quota_line(s, state.get("quota"))
    quota_h = 12 if quota_text else 0
    exhausted = strings.quota_exhausted(state.get("quota"))

    height = 190 + quota_h
    dialog = Dialog(ctx, s("send_title"), width, height)

    if quota_text:
        # The upgrade button appears only once the allowance is actually
        # spent. Standing next to a healthy balance it would just be an advert
        # in a tool the user is trying to work in.
        label_w = inner - (BUTTON_W + 12) if exhausted else inner
        dialog.label("quota", MARGIN, MARGIN, label_w, 10, quota_text)
        if exhausted:
            dialog.button(
                "upgrade", width - BUTTON_W - MARGIN, MARGIN - 2, BUTTON_W,
                BUTTON_H - 2, s("upgrade"),
                lambda: run_upgrade(ctx, frame, store, s,
                                    config.current_stage(store)))

    top = MARGIN + quota_h
    # Shown, not editable. The server sets `owner` from the verified identity
    # and ignores anything the client sends, so an editable box here would be
    # a control that changes nothing — and would invite someone to believe
    # they had sent "from" another address.
    dialog.label("l0", MARGIN, top + 2, 70, 10, s("sender"))
    dialog.label("sender", 80, top + 2, inner - 72, 10,
                 state.get("sender") or "—")
    dialog.label("hint", MARGIN, top + 14, inner, 10, s("sender_hint"),
                 MultiLine=True)

    y = top + 28
    dialog.label("l1", MARGIN, y + 2, 70, 10, s("sig_type"))
    dialog.listbox("profile", 80, y, inner - 72, 12,
                   [s(k) for k in PROFILE_KEYS],
                   PROFILE_KEYS.index(state.get("profile", "click_only")))

    y += ROW + 2
    dialog.label("l2", MARGIN, y + 2, 70, 10, s("order"))
    dialog.listbox("order", 80, y, inner - 72, 12,
                   [s("parallel"), s("sequential")],
                   ORDER_KEYS.index(state.get("order", "PARALLEL")))

    dialog.label("order_note", 80, y + ROW, inner - 72, 10, "")

    y += ROW + 14
    dialog.label("l3", MARGIN, y, inner, 10, s("signers"))
    y += 12
    dialog.listctl("signers", MARGIN, y, inner, 58,
                   [_signer_line(i, sg) for i, sg in enumerate(state["signers"])])

    y += 62
    dialog.button("add", MARGIN, y, BUTTON_W, BUTTON_H, s("add"),
                  lambda: _add_signer(ctx, frame, s, dialog, state))
    dialog.button("edit", MARGIN + BUTTON_W + 4, y, BUTTON_W, BUTTON_H,
                  s("edit"), lambda: _edit_signer(ctx, frame, s, dialog, state))
    dialog.button("remove", MARGIN + 2 * (BUTTON_W + 4), y, BUTTON_W, BUTTON_H,
                  s("remove"), lambda: _remove_signer(dialog, state, s))
    # The list order IS the signing order — it becomes signerIndex, 1-based.
    # Getting it wrong on a sequential send means the wrong person is asked
    # first, and the only fix without these was to remove everybody below the
    # mistake and retype them, CPFs included.
    dialog.button("up", MARGIN + 3 * (BUTTON_W + 4), y, 44, BUTTON_H,
                  s("move_up"), lambda: _move_signer(dialog, state, s, -1))
    dialog.button("down", MARGIN + 3 * (BUTTON_W + 4) + 48, y, 44, BUTTON_H,
                  s("move_down"), lambda: _move_signer(dialog, state, s, 1))

    y = height - BUTTON_H - MARGIN
    # Same wording as the menu entry, so the two are recognisably the same
    # place. Opens over this dialog rather than replacing it: `state` is the
    # form the user has already filled in, and losing it to go and look
    # something up would be the same trap as rebuilding on Voltar.
    #
    # Most useful in exactly the state that prompts the question — the
    # allowance is spent, and the reasonable next move is to see what is
    # still outstanding. Note that cancelling one does not give the send
    # back: the pool is not refunded on cancel.
    dialog.button("history", MARGIN, y, BUTTON_W + 30, BUTTON_H,
                  s("history_title"),
                  lambda: run_history(ctx, frame, store))
    dialog.button("cancel", width - 2 * BUTTON_W - 2 * MARGIN, y, BUTTON_W,
                  BUTTON_H, s("cancel"), lambda: dialog.finish(None))

    def go_review():
        state["profile"] = PROFILE_KEYS[max(0, dialog.selected_index("profile"))]
        state["order"] = ORDER_KEYS[max(0, dialog.selected_index("order"))]
        if not state["signers"]:
            msgbox.error(ctx, frame, s("no_signers"), s("app"))
            return

        # Warn, do not block. The server said no, so this send is very likely
        # to be refused — better to say so here than after the signers are
        # typed and the PDF exported. But the read is a snapshot: a plan bought
        # in the browser a minute ago, or a period that has just rolled over,
        # would make it wrong, and a hard block would leave the user with no
        # way past a stale answer. The server remains the authority either way.
        if strings.quota_exhausted(state.get("quota")):
            if not msgbox.confirm(ctx, frame, s("quota_confirm"), s("app")):
                return

        dialog.finish("review")

    dialog.button("review", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("review"), go_review)

    dialog.on_change("profile", lambda: _sync_order(dialog, state, s))
    dialog.on_change("signers", lambda: _sync_move_buttons(dialog, state))
    _sync_order(dialog, state, s)
    _sync_move_buttons(dialog, state)
    return dialog.show(parent_window(frame))


#: Profiles the server refuses to run in parallel. The A1/A3 path loads the
#: previous signer's output, so there is an order whether or not the user picks
#: one — `create-envelope.ts` overrides PARALLEL for these and reports
#: `signingModeForced`.
ORDER_DEPENDENT_PROFILES = ("digital_certificate",)


def _sync_order(dialog, state, s):
    """
    Keep the order selector honest about what the server will actually do.

    Offering "Paralela" next to a certificate profile is offering a choice that
    does not exist: the send goes out sequential regardless, and the user finds
    out afterwards from a note on the result screen. Better to show the real
    answer while they can still see why.

    Also meaningless with a single signer, which is the older reason this
    control gets disabled.
    """
    profile = PROFILE_KEYS[max(0, dialog.selected_index("profile"))]
    forced = profile in ORDER_DEPENDENT_PROFILES

    if forced:
        state["order"] = "SEQUENTIAL"
        dialog.select("order", ORDER_KEYS.index("SEQUENTIAL"))

    dialog.enable("order", not forced and len(state["signers"]) > 1)
    # Say why it is greyed out. A disabled control with no explanation reads as
    # a bug, and this one has a real reason worth knowing.
    dialog.set_label("order_note", s("order_forced_cert") if forced else "")


def _refresh_signers(dialog, state, s):
    dialog.set_items(
        "signers",
        [_signer_line(i, sg) for i, sg in enumerate(state["signers"])],
        keep_selection=False,
    )
    _sync_order(dialog, state, s)
    _sync_move_buttons(dialog, state)


def _add_signer(ctx, frame, s, dialog, state):
    if len(state["signers"]) >= api.MAX_SIGNERS:
        msgbox.error(ctx, frame,
                     s("max_signers") % api.MAX_SIGNERS, s("app"))
        return
    signer = signer_dialog(ctx, frame, s,
                           blocked_email=_blocked_signer_email(state),
                           recents=state.get("recents") or (),
                           taken_fiscal=_taken_fiscal(state))
    if signer:
        state["signers"].append(signer)
        _refresh_signers(dialog, state, s)


def _edit_signer(ctx, frame, s, dialog, state):
    index = dialog.selected_index("signers")
    if index < 0 or index >= len(state["signers"]):
        return
    signer = signer_dialog(ctx, frame, s, state["signers"][index],
                           blocked_email=_blocked_signer_email(state),
                           recents=state.get("recents") or (),
                           taken_fiscal=_taken_fiscal(state, skip=index))
    if signer:
        state["signers"][index] = signer
        _refresh_signers(dialog, state, s)


def _remove_signer(dialog, state, s):
    index = dialog.selected_index("signers")
    if 0 <= index < len(state["signers"]):
        del state["signers"][index]
        _refresh_signers(dialog, state, s)


def _move_signer(dialog, state, s, delta):
    """
    Move the selected signer one place up or down.

    The selection follows the person, not the position: after moving somebody
    down, the highlight stays on them, so a second click moves them again.
    Leaving it on the index would silently start moving whoever swapped into
    that row instead — which is how a reorder turns into a shuffle.
    """
    signers = state["signers"]
    index = dialog.selected_index("signers")
    target = index + delta
    if index < 0 or target < 0 or target >= len(signers):
        return

    signers[index], signers[target] = signers[target], signers[index]
    _refresh_signers(dialog, state, s)
    dialog.select("signers", target)
    _sync_move_buttons(dialog, state)


def _sync_move_buttons(dialog, state):
    """Grey out a move that has nowhere to go, rather than doing nothing."""
    index = dialog.selected_index("signers")
    count = len(state["signers"])
    dialog.enable("up", count > 1 and index > 0)
    dialog.enable("down", count > 1 and 0 <= index < count - 1)


# ----------------------------------------------------------- review dialog
def review_dialog(ctx, frame, s, state, filename):
    width = 300
    lines = [
        "%s: %s" % (s("document"), filename),
        "%s: %s" % (s("sig_type"), s(state["profile"])),
        "%s: %s" % (s("order"),
                    s("sequential") if state["order"] == "SEQUENTIAL"
                    else s("parallel")),
        "%s: %s" % (s("sender"), state["sender"] or "—"),
    ]

    height = 96 + 10 * min(len(state["signers"]), 6)
    dialog = Dialog(ctx, s("review_title"), width, height)
    inner = width - 2 * MARGIN

    dialog.label("summary", MARGIN, MARGIN, inner, 10 * len(lines),
                 "\n".join(lines), MultiLine=True)
    top = MARGIN + 10 * len(lines) + 4
    dialog.listctl("signers", MARGIN, top, inner, height - top - BUTTON_H - 2 * MARGIN,
                   [_signer_line(i, sg) for i, sg in enumerate(state["signers"])])

    y = height - BUTTON_H - MARGIN
    dialog.button("back", width - 2 * BUTTON_W - 2 * MARGIN, y, BUTTON_W,
                  BUTTON_H, s("back"), lambda: dialog.finish("back"))
    dialog.button("send", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("send_now"), lambda: dialog.finish("send"))
    return dialog.show(parent_window(frame))


# ----------------------------------------------------------- result dialog
def result_dialog(ctx, frame, s, sent, account_email=""):
    """
    Show what was created, and let the sender sign their own part right away.

    The sender is very often one of the signers, and that case gets no
    invitation e-mail — the API suppresses it when the owner is the signer,
    correctly, since nobody wants to be mailed a link to their own document.
    Without a button here, signing your own document meant selecting a
    200-character URL out of a list box and pasting it into a browser.

    Two rules shape the buttons, and both are about the same fact: a signing
    link is a bearer credential, so whoever holds it can sign.

      * **Assinar agora** opens only the row belonging to the signed-in
        account. Never any other row, and never on its own — an explicit
        click, never a redirect. An earlier version of this in another product
        auto-opened whatever link it had, and an admin signed a document in
        somebody else's name.
      * **Copiar** is unavailable for another signer's CLICK_ONLY row, because
        for that profile the link is the entire authentication. The server does
        not even send it; the row says so instead of showing a link that is not
        there.

    Both are enforced server-side as well. These only avoid offering something
    that would be refused.
    """
    width = 320
    height = 150
    dialog = Dialog(ctx, s("result_title"), width, height)
    inner = width - 2 * MARGIN

    links = sent["links"]
    profile = sent.get("profile")

    entries = []
    for link in links:
        note = s("invite_sent") if link.get("inviteSent") else s("invite_not_sent")
        # A withheld link has no url at all. Saying so beats an em dash that
        # reads like something went wrong.
        target = link.get("url") or s("link_by_email")
        entries.append("%s — %s (%s)" % (link.get("signerName") or "",
                                         target, note))

    dialog.label("t", MARGIN, MARGIN, inner, 10, s("sent_ok"))
    control = dialog.listctl("links", MARGIN, MARGIN + 12, inner,
                             height - 60, entries)
    # Preselect, so the single-signer case — much the commonest — needs no
    # click before the buttons mean anything.
    if entries:
        control.SelectedItems = (0,)

    def selected_link():
        index = dialog.selected_index("links")
        if index < 0 or index >= len(links):
            return None
        return links[index]

    def is_mine(link):
        return bool(link) and oauth.matches_account(
            link.get("signerEmail"), account_email)

    def copy_selected():
        link = selected_link()
        if link is None:
            return
        url = link.get("url")
        if not url:
            # Withheld, not missing. Explain which, so the answer to "why can't
            # I copy this?" is the honest one.
            if (profile or "") == "click_only" and not is_mine(link):
                msgbox.info(ctx, frame, s("copy_click_only_blocked"), s("app"))
            return
        if copy_to_clipboard(ctx, url):
            msgbox.info(ctx, frame, s("copied"), s("app"))
        else:
            # No clipboard on this session; show the link so it can be
            # selected by hand rather than claiming a copy that did not happen.
            msgbox.info(ctx, frame, url, s("app"))

    def sign_selected():
        link = selected_link()
        if not is_mine(link):
            msgbox.info(ctx, frame, s("sign_now_other"), s("app"))
            return
        url = link.get("url")
        if not url:
            msgbox.info(ctx, frame, s("sign_now_unavailable"), s("app"))
            return
        _open_in_browser(ctx, url)

    def refresh_buttons():
        link = selected_link()
        mine = is_mine(link)
        dialog.enable("sign", mine)
        # Your own row always copies; another signer's only when the link was
        # actually returned.
        dialog.enable("copy", bool(link) and (mine or bool(link.get("url"))))

    y = height - BUTTON_H - MARGIN
    # "Assinar agora" is longer than any existing caption, hence the wider
    # button; the four still fit inside 320 without crowding Fechar.
    dialog.button("sign", MARGIN, y, BUTTON_W + 24, BUTTON_H, s("sign_now"),
                  sign_selected)
    dialog.button("copy", MARGIN + BUTTON_W + 28, y, BUTTON_W, BUTTON_H,
                  s("copy"), copy_selected)
    dialog.button("track", MARGIN + 2 * BUTTON_W + 32, y, BUTTON_W + 8,
                  BUTTON_H, s("track_title"), lambda: dialog.finish("track"))
    dialog.button("close", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("close"), lambda: dialog.finish(True))

    dialog.on_change("links", refresh_buttons)
    refresh_buttons()

    return dialog.show(parent_window(frame))


# ----------------------------------------------------------- track dialog
#: Statuses that will never change again, so polling can stop.
TERMINAL = ("COMPLETED", "CANCELLED", "EXPIRED", "FAILED")

POLL_FIRST = 0
POLL_MIN = 5
POLL_MAX = 60


def _unique_path(path):
    """
    Never silently overwrite. `contrato-assinado.pdf` becomes
    `contrato-assinado (2).pdf` rather than replacing a file the user may
    still need.
    """
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    for n in range(2, 1000):
        candidate = "%s (%d)%s" % (stem, n, ext)
        if not os.path.exists(candidate):
            return candidate
    return path


def track_dialog(ctx, frame, store, s, entry, document_model=None,
                 account_email=None):
    """
    Follow a send to completion and bring the signed PDF back.

    Polls in the background with a widening interval and stops the moment the
    status is terminal — leaving a fixed-rate poller running against a
    finished envelope would be rude to the API and pointless. The poller is
    also stopped when the dialog closes, so closing the window really does end
    the work.

    This is also where somebody sits waiting on a document they themselves have
    to sign, so it offers the same **Assinar agora** as the pending list. The
    link is minted on demand; nothing is stored.
    """
    stage = config.current_stage(store)
    if account_email is None:
        account_email = oauth.account_email(store, stage)
    # 380 rather than 300: five buttons now, one of them wide. Taller too,
    # for the signer list.
    width = 380
    height = 210
    dialog = Dialog(ctx, s("track_title"), width, height)
    inner = width - 2 * MARGIN
    stop = threading.Event()
    latest = {}

    # What was typed at send time, keyed by e-mail. The status payloads carry
    # no fiscal number at all and the session one carries no name either, so
    # the local record is the only source for both — the API is authoritative
    # about who has signed, never about who they are.
    known = {}
    for signer in entry.get("signers") or []:
        email = (signer.get("email") or "").strip().lower()
        if email:
            known[email] = signer

    dialog.label("doc", MARGIN, MARGIN, inner, 10,
                 "%s: %s" % (s("document"), entry.get("filename") or ""))
    dialog.label("status", MARGIN, MARGIN + 14, inner, 10, s("busy_status"))
    dialog.label("progress", MARGIN, MARGIN + 28, inner, 10, "")
    # Drawn from the local record straight away, so the list is populated
    # before the first poll returns rather than sitting empty for a beat.
    dialog.listctl("signers", MARGIN, MARGIN + 42, inner, height - 110,
                   [strings.signer_line(
                       s, signer,
                       oauth.matches_account(signer.get("email"), account_email))
                    for signer in (entry.get("signers") or [])])

    def render(status):
        """Main thread only — called through on_main_thread by the poller."""
        latest["status"] = status
        try:
            dialog.set_label("status", strings.api_status(s, status.get("status")))
            total = status.get("total") or 0
            if total:
                dialog.model.getByName("progress").Label = "%s: %d/%d" % (
                    s("signers"), status.get("completed") or 0, total)
            # Who, not just how many. A count says a document is stuck; the
            # list says who it is stuck on.
            rows = status.get("signers") or []
            if rows:
                dialog.set_items("signers", [
                    strings.signer_line(
                        s, _merge_signer(row, known),
                        oauth.matches_account(row.get("email"), account_email))
                    for row in rows
                ])
            dialog.enable("download", bool(status.get("signed_available")))
            dialog.enable("cancel_send", status.get("status") == "ACTIVE")
            # Only while there is still something to sign, and only if it is
            # the account's own signature that is outstanding.
            dialog.enable("sign", status.get("status") == "ACTIVE"
                          and _entry_is_mine(entry, account_email))
        except Exception:
            # The dialog was disposed between the poll and the callback.
            pass

        local = history.FROM_API.get(status.get("status"))
        if local:
            try:
                history.History(store, stage).set_status(entry["id"], local)
            except Exception:
                pass

    def poller():
        delay = POLL_FIRST
        while True:
            if stop.wait(delay):
                return
            try:
                status = api.status_of(store, entry["kind"], entry["id"], stage=stage)
            except Exception:
                # Transient: back off rather than hammering, and keep the
                # dialog usable.
                delay = min(max(delay, POLL_MIN) * 2, POLL_MAX)
                continue
            if stop.is_set():
                return
            async_work.on_main_thread(ctx, lambda st=status: render(st))
            if status.get("status") in TERMINAL:
                return
            delay = min(int(max(delay, POLL_MIN) * 1.5), POLL_MAX)

    def download():
        result = busy(ctx, parent_window(frame), s("busy_download"),
                      lambda: api.signed_pdf(
                          store, entry["kind"], entry["id"],
                          transaction_id=entry.get("transactionId"), stage=stage))
        if not _report(ctx, frame, result, s):
            return
        target = _unique_path(signed_path_for(
            document_model, api.signed_filename(entry.get("filename"))))
        try:
            with open(target, "wb") as handle:
                handle.write(result.value)
        except OSError as exc:
            msgbox.error(ctx, frame, str(exc), s("app"))
            return
        msgbox.info(ctx, frame, "%s\n%s" % (s("saved_to"), target), s("app"))

    def cancel_send():
        # Irreversible from in here, and it acts on people outside this
        # machine: whoever holds a link finds it dead with no explanation.
        if not msgbox.confirm(ctx, frame, s("confirm_cancel"), s("app")):
            return
        result = busy(ctx, parent_window(frame), s("busy_status"),
                      lambda: api.cancel(store, entry["kind"], entry["id"],
                                         stage=stage))
        if not _report(ctx, frame, result, s):
            return
        history.History(store, stage).mark_cancelled(entry["id"])
        preserved = result.value.get("preservedSignedCount") or 0
        if preserved:
            msgbox.info(ctx, frame, s("preserved_signatures") % preserved,
                        s("app"))
        dialog.finish(True)

    def sign_now():
        result = busy(ctx, parent_window(frame), s("busy_status"),
                      lambda: api.sign_link(store, entry["kind"], entry["id"],
                                            stage=stage))
        if not _report(ctx, frame, result, s):
            return
        if not result.value:
            msgbox.info(ctx, frame, s("sign_now_unavailable"), s("app"))
            return
        _open_in_browser(ctx, result.value)

    y = height - BUTTON_H - MARGIN
    dialog.button("sign", MARGIN, y, BUTTON_W + 24, BUTTON_H, s("sign_now"),
                  sign_now)
    dialog.button("refresh", MARGIN + BUTTON_W + 28, y, BUTTON_W, BUTTON_H,
                  s("refresh"),
                  lambda: async_work.run(
                      ctx,
                      lambda: api.status_of(store, entry["kind"], entry["id"],
                                            stage=stage),
                      lambda r: render(r.value) if r.ok else None))
    dialog.button("download", MARGIN + 2 * BUTTON_W + 32, y, BUTTON_W + 12,
                  BUTTON_H, s("download"), download)
    dialog.button("cancel_send", MARGIN + 3 * BUTTON_W + 48, y, BUTTON_W + 12,
                  BUTTON_H, s("cancel_send"), cancel_send)
    dialog.button("close", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("close"), lambda: dialog.finish(True))
    dialog.enable("download", False)
    dialog.enable("cancel_send", False)
    # Enabled by the first render, once the live status says it is still
    # signable — not on the strength of a stale history row.
    dialog.enable("sign", False)

    threading.Thread(target=poller, name="signdocs-poll", daemon=True).start()
    try:
        dialog.show(parent_window(frame))
    finally:
        # Closing the window ends the polling. Without this the thread would
        # outlive the dialog and keep calling the API for nothing.
        stop.set()
    return latest.get("status")


# ------------------------------------------------------------------ flows
def run_send(ctx, frame, store):
    s = strings.for_office(ctx)
    if frame is None:
        msgbox.error(ctx, frame, "Nenhum documento aberto.", s("app"))
        return
    document_model = frame.getController().getModel()

    if not ensure_connected(ctx, frame, store, s):
        return

    stage = config.current_stage(store)

    # Before anything else, and before the quota read: this is the one gate
    # that stops the flow outright, so asking after the user has filled in a
    # form would waste their work. Nothing here is cached locally — the server
    # owns which versions are current, and a policy can be reissued between
    # two sends.
    if not ensure_policies_accepted(ctx, frame, store, s, stage):
        return
    state = {
        # From our own ID token, which is the same identity the server will
        # attribute the send to. Falls back to the init-session payload if the
        # token cannot be read.
        "sender": oauth.account_email(store, stage),
        "profile": store.get(config.STORAGE["profile"]) or "click_only",
        "order": "PARALLEL",
        "signers": [],
    }
    if state["profile"] not in PROFILE_KEYS:
        state["profile"] = "click_only"

    # Read the plan once and carry it in `state`, so the review→Voltar loop
    # does not re-query on every pass. Off the main thread like every other
    # call: HTTP on the dispatch thread freezes the whole office.
    #
    # Fail-soft deliberately. This is a display, and the server enforces the
    # quota whatever the extension believes; letting a failed lookup block a
    # send the user is entitled to make would turn a convenience into an
    # outage. A `None` here simply omits the line.
    info = busy(ctx, parent_window(frame), s("busy_status"),
                lambda: api.init_session(store, stage=stage))
    state["quota"] = info.value if info is not None and info.ok else None

    # Read once per send rather than per signer: it comes off the local history
    # and nothing writes to that until this send finishes.
    try:
        state["recents"] = history.History(store, stage).recent_signers()
    except Exception:
        # A convenience. If the history is unreadable the picker simply does
        # not appear, which is exactly what happens on a first run anyway.
        state["recents"] = []

    # One key for the whole attempt, reused if the user retries after a
    # failure: quota is a single pool and is not refunded on cancel, so a
    # fresh key per attempt would bill a network blip twice.
    idempotency_key = None

    while True:
        if send_dialog(ctx, frame, store, s, state) != "review":
            return

        try:
            filename = intake.filename_for(document_model)
        except Exception:
            filename = "documento.pdf"

        if review_dialog(ctx, frame, s, state, filename) != "send":
            continue

        try:
            store.set(config.STORAGE["profile"], state["profile"])
        except Exception:
            pass

        exported = busy(ctx, parent_window(frame), s("busy_export"),
                        lambda: intake.export_pdf(document_model))
        if not _report(ctx, frame, exported, s):
            continue
        document = exported.value

        if idempotency_key is None:
            idempotency_key = str(uuid.uuid4())

        sent = busy(ctx, parent_window(frame), s("busy_send"), lambda: api.send(
            store, document, state["signers"], profile=state["profile"],
            order=state["order"],
            idempotency_key=idempotency_key, stage=stage,
        ))
        if not _report(ctx, frame, sent, s):
            continue

        result = sent.value
        entry = {
            "id": result["id"],
            "kind": result["kind"],
            "transactionId": result.get("transactionId"),
            "filename": document["filename"],
            "signers": state["signers"],
            "createdAt": _now(),
        }
        try:
            history.History(store, stage).add(entry)
        except Exception:
            pass

        # The same verified address that fills the sender label, so the button
        # and the label can never disagree about who is signed in.
        if result_dialog(ctx, frame, s, result,
                         state.get("sender") or "") == "track":
            track_dialog(ctx, frame, store, s, entry, document_model,
                         account_email=state.get("sender") or "")
        return


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _history_line(s, entry):
    return "%s — %s (%s)" % (
        entry.get("filename") or "",
        entry.get("kind") or "",
        s("status_" + (entry.get("status") or history.PENDING)),
    )


def _merge_signer(row, known):
    """
    A live status row filled out with what was recorded locally.

    The server is authoritative about *state* — who has signed — and the local
    record about *identity*: the status payloads carry no fiscal number, and
    the single-session one carries no name either. Merging this way round
    means a signer who has since been renamed upstream still shows their
    current name, while the CPF the user typed is never invented.
    """
    local = known.get((row.get("email") or "").strip().lower()) or {}
    return {
        "name": row.get("name") or local.get("name"),
        "email": row.get("email") or local.get("email"),
        "fiscal": row.get("fiscal") or local.get("fiscal"),
        "status": row.get("status"),
    }


def _entry_is_mine(entry, account_email):
    """
    True when this send is still open and the account is one of its signers.

    History stores each signer's name and e-mail — an ordinary record, not a
    credential — which is what lets an old row be judged without a round trip.
    The link itself is deliberately absent and is minted only when the button
    is actually pressed.

    A finished or cancelled send has nothing left to sign, so it is excluded
    here rather than discovered by a server round trip that answers 409.

    A missing status means pending: an entry built by `run_send` has not been
    through `history.add` yet, and it is by definition the send that just
    happened.
    """
    if not entry:
        return False
    if (entry.get("status") or history.PENDING) != history.PENDING:
        return False
    return any(
        oauth.matches_account(signer.get("email"), account_email)
        for signer in (entry.get("signers") or [])
    )


def run_history(ctx, frame, store):
    s = strings.for_office(ctx)
    stage = config.current_stage(store)
    store_history = history.History(store, stage)

    if not store_history.list():
        msgbox.info(ctx, frame, s("no_history"), s("app"))
        return

    # Bring the pending rows up to date before drawing anything. Nothing else
    # ever moves a row off `pending` — the tracking poller only runs while it
    # is open on one row — so without this the list is a record of what was
    # sent, not of what is outstanding, and every row reads pending forever.
    #
    # Costs one call per pending row and nothing at all when none are pending,
    # which is the steady state: each pass retires the rows it resolves.
    def refresh():
        if not store_history.pending():
            return None
        result = busy(ctx, parent_window(frame), s("busy_refresh"),
                      lambda: sync.refresh_pending(store, stage))
        if result is None or not result.ok:
            # Offline is not a reason to refuse to show the list; the rows
            # simply stay as they were.
            return None
        return result.value

    outcome = refresh()

    # 360 rather than 320: five buttons, one of which carries the longest
    # caption in the extension.
    width = 360
    height = 176
    dialog = Dialog(ctx, s("history_title"), width, height)
    inner = width - 2 * MARGIN

    # Whose account this is, so a row can be checked against its signers
    # without asking the server. Read once — it does not change while the
    # dialog is open, and it is only ever used to decide what to offer.
    account = oauth.account_email(store, stage)

    # The listbox shows a filtered view, so a selection index means nothing
    # without the exact rows it was drawn from. Keeping them together is what
    # stops "cancel" from acting on a different document than the highlighted
    # one once anything is hidden.
    view = {"rows": []}

    def redraw(keep_selection=False):
        rows = store_history.list()
        if dialog.get_state("only_pending"):
            rows = [e for e in rows if e.get("status") == history.PENDING]
        view["rows"] = rows
        dialog.set_items("items", [_history_line(s, e) for e in rows],
                         keep_selection=keep_selection)
        total = len(store_history.list())
        pending = len(store_history.pending())
        dialog.set_label("count", s("pending_count") % (pending, total))
        # Redrawing moves the selection, so the button has to follow it.
        # Guarded because redraw runs once from the only_pending listener,
        # which is wired before the buttons exist.
        try:
            dialog.enable("sign", _entry_is_mine(selected(), account))
        except Exception:
            pass

    def selected():
        index = dialog.selected_index("items")
        if index < 0 or index >= len(view["rows"]):
            return None
        return view["rows"][index]

    dialog.check("only_pending", MARGIN, MARGIN, inner - 90, 10,
                 s("only_pending"))
    dialog.label("count", width - 90, MARGIN, 90 - MARGIN, 10, "")
    dialog.listctl("items", MARGIN, MARGIN + 14, inner, height - 56, [])
    dialog.on_change("only_pending", lambda: redraw())

    def cancel_selected():
        entry = selected()
        if entry is None or entry.get("status") != history.PENDING:
            return
        # Confirmed here too, and for a sharper reason than in the tracker:
        # this list is a grid of similar-looking rows, so acting on the wrong
        # one is a plausible slip rather than a hypothetical.
        prompt = s("confirm_cancel")
        if entry.get("filename"):
            # Naming the document is the guard that actually works here.
            prompt = "%s\n\n%s" % (entry["filename"], prompt)
        if not msgbox.confirm(ctx, frame, prompt, s("app")):
            return
        result = busy(ctx, parent_window(frame), s("busy_status"),
                      lambda: api.cancel(store, entry["kind"], entry["id"],
                                         stage=stage))
        if not _report(ctx, frame, result, s):
            return
        store_history.mark_cancelled(entry["id"])
        redraw()
        preserved = result.value.get("preservedSignedCount") or 0
        if preserved:
            # Cancelling does not destroy signatures already collected, and
            # implying otherwise would be alarming and wrong.
            msgbox.info(ctx, frame, s("preserved_signatures") % preserved,
                        s("app"))

    def track_selected():
        entry = selected()
        if entry is None:
            return
        track_dialog(ctx, frame, store, s, entry, account_email=account)
        redraw()

    def sign_selected():
        entry = selected()
        if not _entry_is_mine(entry, account):
            return
        # The link was never stored — see history.add — so it is minted now.
        # That is the whole reason this works at all after the send window has
        # been closed.
        result = busy(ctx, parent_window(frame), s("busy_status"),
                      lambda: api.sign_link(store, entry["kind"], entry["id"],
                                            stage=stage))
        if not _report(ctx, frame, result, s):
            return
        if not result.value:
            # Already signed, cancelled, or not ours to sign. The server does
            # not say which, on purpose.
            msgbox.info(ctx, frame, s("sign_now_unavailable"), s("app"))
            return
        _open_in_browser(ctx, result.value)

    def refresh_clicked():
        again = refresh()
        redraw(keep_selection=True)
        if again and again[2]:
            msgbox.info(ctx, frame, s("refresh_failed") % again[2], s("app"))

    y = height - BUTTON_H - MARGIN
    dialog.button("sign", MARGIN, y, BUTTON_W + 24, BUTTON_H, s("sign_now"),
                  sign_selected)
    dialog.button("track", MARGIN + BUTTON_W + 28, y, BUTTON_W + 8, BUTTON_H,
                  s("track_title"), track_selected)
    dialog.button("cancel_send", MARGIN + 2 * BUTTON_W + 40, y, BUTTON_W + 20,
                  BUTTON_H, s("cancel_send"), cancel_selected)
    dialog.button("refresh", MARGIN + 3 * BUTTON_W + 64, y, BUTTON_W, BUTTON_H,
                  s("refresh"), refresh_clicked)
    dialog.button("close", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("close"), lambda: dialog.finish(True))

    dialog.on_change("items", lambda: dialog.enable(
        "sign", _entry_is_mine(selected(), account)))

    redraw()
    if outcome and outcome[2]:
        msgbox.info(ctx, frame, s("refresh_failed") % outcome[2], s("app"))
    dialog.show(parent_window(frame))


def run_settings(ctx, frame, store):
    s = strings.for_office(ctx)
    connected = oauth.is_connected(store)

    # This is the screen someone opens to ask "what plan am I on", so the
    # answer is fetched rather than remembered — a cached figure here would go
    # stale exactly when it matters, after a send or an upgrade. Only asked
    # when there is an identity to ask about, and never fatal: settings must
    # still open when the network is down, since switching stage is how a user
    # gets themselves out of a broken environment.
    quota_text = None
    if connected:
        info = busy(ctx, parent_window(frame), s("busy_status"),
                    lambda: api.init_session(store))
        if info is not None and info.ok:
            quota_text = strings.quota_line(s, info.value)
        else:
            quota_text = s("quota_unknown")

    width = 260
    quota_h = 30 if quota_text else 0
    height = 110 + quota_h
    dialog = Dialog(ctx, s("settings_title"), width, height)
    inner = width - 2 * MARGIN
    stages = ("prod", "hml")

    dialog.label("l0", MARGIN, MARGIN + 2, 70, 10, s("stage"))
    dialog.listbox("stage", 80, MARGIN, inner - 72, 12,
                   [s("stage_prod"), s("stage_hml")],
                   stages.index(config.current_stage(store)))

    # Read-only for the same reason as the send window: this is who the server
    # will attribute sends to, not a preference.
    dialog.label("l1", MARGIN, MARGIN + ROW + 2, 70, 10, s("sender"))
    dialog.label("sender", 80, MARGIN + ROW + 2, inner - 72, 10,
                 oauth.account_email(store) or "—")

    dialog.label("state", MARGIN, MARGIN + 2 * ROW + 4, inner, 10,
                 s("connected_as") if connected else s("not_connected"))

    if quota_text:
        dialog.label("quota", MARGIN, MARGIN + 3 * ROW + 2, inner, 10,
                     quota_text)
        # Said out loud because the number is not what it looks like: the
        # allowance is one pool across the app and every integration, so a
        # figure shown inside the LibreOffice extension is not a LibreOffice
        # budget.
        dialog.label("quota_note", MARGIN, MARGIN + 4 * ROW, inner, 18,
                     s("quota_shared"), MultiLine=True)

    def do_disconnect():
        oauth.disconnect(store)
        dialog.model.getByName("state").Label = s("not_connected")
        dialog.enable("disconnect", False)

    dialog.button("disconnect", MARGIN, height - BUTTON_H - MARGIN,
                  BUTTON_W + 16, BUTTON_H, s("disconnect"), do_disconnect)
    dialog.enable("disconnect", connected)

    def save():
        config.set_stage(store, stages[max(0, dialog.selected_index("stage"))])
        dialog.finish(True)

    y = height - BUTTON_H - MARGIN
    dialog.button("cancel", width - 2 * BUTTON_W - 2 * MARGIN, y, BUTTON_W,
                  BUTTON_H, s("cancel"), lambda: dialog.finish(False))
    dialog.button("ok", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("ok"), save)
    dialog.show(parent_window(frame))


def store_for(ctx):
    from signdocs import paths
    from signdocs.store import JsonStore

    try:
        return JsonStore(paths.state_file(ctx))
    except Exception:
        return JsonStore()


def signed_path_for(document_model, filename):
    """
    Where a signed PDF goes: beside the original document, or the home
    directory when there is no original to sit beside — which is the case
    whenever tracking is opened from the history list rather than from the
    document that was sent.
    """
    url = ""
    if document_model is not None:
        try:
            url = document_model.getURL() or ""
        except Exception:
            url = ""
    if url:
        directory = os.path.dirname(urllib.parse.unquote(
            urllib.parse.urlparse(url).path))
        if directory and os.path.isdir(directory):
            return os.path.join(directory, filename)
    return os.path.join(os.path.expanduser("~"), filename)
