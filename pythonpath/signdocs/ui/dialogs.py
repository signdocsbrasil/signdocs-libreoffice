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
def signer_dialog(ctx, frame, s, signer=None):
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
        classified = validators.classify(fiscal)
        if classified.kind is None or not classified.valid:
            dialog.model.getByName("err").Label = s("fiscal")
            return
        dialog.finish({"name": name, "email": email, "fiscal": fiscal})

    dialog.button("cancel", width - 2 * BUTTON_W - 2 * MARGIN, 68, BUTTON_W,
                  BUTTON_H, s("cancel"), lambda: dialog.finish(None))
    dialog.button("ok", width - BUTTON_W - MARGIN, 68, BUTTON_W, BUTTON_H,
                  s("ok"), accept)
    return dialog.show(parent_window(frame))


def _signer_line(index, signer):
    label = "%d. %s" % (index + 1, signer.get("name") or "")
    if signer.get("email"):
        label += " — " + signer["email"]
    fiscal = validators.format_cpf_cnpj(signer.get("fiscal"))
    if fiscal:
        label += " — " + fiscal
    return label


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
    dialog.label("l0", MARGIN, top + 2, 70, 10, s("sender"))
    dialog.edit("sender", 80, top, inner - 72, 12, state.get("sender", ""))
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

    y += ROW + 6
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
                  s("remove"), lambda: _remove_signer(dialog, state))

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
        state["sender"] = dialog.get("sender").strip()
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

    # The order selector is meaningless with a single signer.
    dialog.enable("order", len(state["signers"]) > 1)
    return dialog.show(parent_window(frame))


def _refresh_signers(dialog, state):
    dialog.set_items(
        "signers",
        [_signer_line(i, sg) for i, sg in enumerate(state["signers"])],
        keep_selection=False,
    )
    dialog.enable("order", len(state["signers"]) > 1)


def _add_signer(ctx, frame, s, dialog, state):
    if len(state["signers"]) >= api.MAX_SIGNERS:
        msgbox.error(ctx, frame,
                     s("max_signers") % api.MAX_SIGNERS, s("app"))
        return
    signer = signer_dialog(ctx, frame, s)
    if signer:
        state["signers"].append(signer)
        _refresh_signers(dialog, state)


def _edit_signer(ctx, frame, s, dialog, state):
    index = dialog.selected_index("signers")
    if index < 0 or index >= len(state["signers"]):
        return
    signer = signer_dialog(ctx, frame, s, state["signers"][index])
    if signer:
        state["signers"][index] = signer
        _refresh_signers(dialog, state)


def _remove_signer(dialog, state):
    index = dialog.selected_index("signers")
    if 0 <= index < len(state["signers"]):
        del state["signers"][index]
        _refresh_signers(dialog, state)


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
    if not state["sender"]:
        lines.append(s("sender_hint"))

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
def result_dialog(ctx, frame, s, sent):
    width = 320
    height = 150
    dialog = Dialog(ctx, s("result_title"), width, height)
    inner = width - 2 * MARGIN

    entries = []
    for link in sent["links"]:
        note = s("invite_sent") if link.get("inviteSent") else s("invite_not_sent")
        entries.append("%s — %s (%s)" % (link.get("signerName") or "",
                                         link.get("url") or "—", note))

    dialog.label("t", MARGIN, MARGIN, inner, 10, s("sent_ok"))
    dialog.listctl("links", MARGIN, MARGIN + 12, inner, height - 60, entries)

    def copy_selected():
        index = dialog.selected_index("links")
        if index < 0 or index >= len(sent["links"]):
            return
        url = sent["links"][index].get("url")
        if url and copy_to_clipboard(ctx, url):
            msgbox.info(ctx, frame, s("copied"), s("app"))
        elif url:
            # No clipboard on this session; show the link so it can be
            # selected by hand rather than claiming a copy that did not happen.
            msgbox.info(ctx, frame, url, s("app"))

    y = height - BUTTON_H - MARGIN
    dialog.button("copy", MARGIN, y, BUTTON_W, BUTTON_H, s("copy"), copy_selected)
    dialog.button("track", MARGIN + BUTTON_W + 4, y, BUTTON_W + 8, BUTTON_H,
                  s("track_title"), lambda: dialog.finish("track"))
    dialog.button("close", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("close"), lambda: dialog.finish(True))
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


def track_dialog(ctx, frame, store, s, entry, document_model=None):
    """
    Follow a send to completion and bring the signed PDF back.

    Polls in the background with a widening interval and stops the moment the
    status is terminal — leaving a fixed-rate poller running against a
    finished envelope would be rude to the API and pointless. The poller is
    also stopped when the dialog closes, so closing the window really does end
    the work.
    """
    stage = config.current_stage(store)
    width = 300
    height = 120
    dialog = Dialog(ctx, s("track_title"), width, height)
    inner = width - 2 * MARGIN
    stop = threading.Event()
    latest = {}

    dialog.label("doc", MARGIN, MARGIN, inner, 10,
                 "%s: %s" % (s("document"), entry.get("filename") or ""))
    dialog.label("status", MARGIN, MARGIN + 14, inner, 10, s("busy_status"))
    dialog.label("progress", MARGIN, MARGIN + 28, inner, 10, "")

    def render(status):
        """Main thread only — called through on_main_thread by the poller."""
        latest["status"] = status
        try:
            dialog.set_label("status", strings.api_status(s, status.get("status")))
            total = status.get("total") or 0
            if total:
                dialog.model.getByName("progress").Label = "%s: %d/%d" % (
                    s("signers"), status.get("completed") or 0, total)
            dialog.enable("download", bool(status.get("signed_available")))
            dialog.enable("cancel_send", status.get("status") == "ACTIVE")
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

    y = height - BUTTON_H - MARGIN
    dialog.button("refresh", MARGIN, y, BUTTON_W, BUTTON_H, s("refresh"),
                  lambda: async_work.run(
                      ctx,
                      lambda: api.status_of(store, entry["kind"], entry["id"],
                                            stage=stage),
                      lambda r: render(r.value) if r.ok else None))
    dialog.button("download", MARGIN + BUTTON_W + 4, y, BUTTON_W + 12, BUTTON_H,
                  s("download"), download)
    dialog.button("cancel_send", MARGIN + 2 * BUTTON_W + 20, y, BUTTON_W + 12,
                  BUTTON_H, s("cancel_send"), cancel_send)
    dialog.button("close", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("close"), lambda: dialog.finish(True))
    dialog.enable("download", False)
    dialog.enable("cancel_send", False)

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
    state = {
        "sender": store.get(config.STORAGE["sender_email"]) or "",
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
            store.set(config.STORAGE["sender_email"], state["sender"])
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
            order=state["order"], owner_email=state["sender"] or None,
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

        if result_dialog(ctx, frame, s, result) == "track":
            track_dialog(ctx, frame, store, s, entry, document_model)
        return


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _history_line(s, entry):
    return "%s — %s (%s)" % (
        entry.get("filename") or "",
        entry.get("kind") or "",
        s("status_" + (entry.get("status") or history.PENDING)),
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

    width = 320
    height = 176
    dialog = Dialog(ctx, s("history_title"), width, height)
    inner = width - 2 * MARGIN

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
        track_dialog(ctx, frame, store, s, entry)
        redraw()

    def refresh_clicked():
        again = refresh()
        redraw(keep_selection=True)
        if again and again[2]:
            msgbox.info(ctx, frame, s("refresh_failed") % again[2], s("app"))

    y = height - BUTTON_H - MARGIN
    dialog.button("track", MARGIN, y, BUTTON_W + 8, BUTTON_H,
                  s("track_title"), track_selected)
    dialog.button("cancel_send", MARGIN + BUTTON_W + 12, y, BUTTON_W + 20,
                  BUTTON_H, s("cancel_send"), cancel_selected)
    dialog.button("refresh", MARGIN + 2 * BUTTON_W + 36, y, BUTTON_W, BUTTON_H,
                  s("refresh"), refresh_clicked)
    dialog.button("close", width - BUTTON_W - MARGIN, y, BUTTON_W, BUTTON_H,
                  s("close"), lambda: dialog.finish(True))

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

    dialog.label("l1", MARGIN, MARGIN + ROW + 2, 70, 10, s("sender"))
    dialog.edit("sender", 80, MARGIN + ROW, inner - 72, 12,
                store.get(config.STORAGE["sender_email"]) or "")

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
        try:
            store.set(config.STORAGE["sender_email"], dialog.get("sender").strip())
        except Exception:
            pass
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
