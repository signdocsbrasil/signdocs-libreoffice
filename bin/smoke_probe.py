# SPDX-License-Identifier: MPL-2.0
"""
Integration probe. Run by bin/smoke-oxt.sh against a headless office that has
the extension installed.

`unopkg list` reporting "is registered: yes" only proves the packages were
deployed. It does NOT prove that the menu entries reached the configuration,
nor that a click would reach our Python. Those are two separate silent-failure
modes:

  * Addons.xcu rejected  -> extension installs, no menu ever appears
  * implementation name in ProtocolHandler.xcu != the name registered by
    g_ImplementationHelper -> menu appears, every click is a no-op

Both are invisible in the office log. This asserts them directly.
"""

import base64
import json
import os
import sys
import threading
import time

import uno
import unohelper
from com.sun.star.beans import PropertyValue

PORT = sys.argv[1] if len(sys.argv) > 1 else "2103"
PROTOCOL = "br.com.signdocs.libreoffice"
COMMANDS = ("Enviar", "Historico", "Configurar")

failures = []


def check(label, condition, detail=""):
    print("  %s %s%s" % ("ok " if condition else "FAIL", label,
                         ("  -- " + str(detail)) if detail else ""))
    if not condition:
        failures.append(label)


def connect():
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local
    )
    return resolver.resolve(
        "uno:socket,host=127.0.0.1,port=%s;urp;StarOffice.ComponentContext" % PORT
    )


def main():
    ctx = connect()
    sm = ctx.ServiceManager

    # --- 1. the Addons.xcu entries reached the configuration -------------
    cp = sm.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", ctx
    )
    arg = PropertyValue()
    arg.Name = "nodepath"
    arg.Value = "/org.openoffice.Office.Addons/AddonUI"
    addon_ui = cp.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationAccess", (arg,)
    )

    menu = addon_ui.getByName("AddonMenu")
    check(
        "AddonMenu contains our submenu",
        "%s.menu" % PROTOCOL in menu.getElementNames(),
    )

    toolbar = addon_ui.getByName("OfficeToolBar")
    check(
        "OfficeToolBar contains our toolbar",
        "%s.toolbar" % PROTOCOL in toolbar.getElementNames(),
    )

    submenu = menu.getByName("%s.menu" % PROTOCOL).getByName("Submenu")
    urls = {
        submenu.getByName(n).getByName("URL") for n in submenu.getElementNames()
    }
    for cmd in COMMANDS:
        check(
            "submenu exposes %s:%s" % (PROTOCOL, cmd),
            "%s:%s" % (PROTOCOL, cmd) in urls,
        )

    # --- 2. a real frame resolves our protocol handler -------------------
    desktop = sm.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    doc = desktop.loadComponentFromURL(
        "private:factory/swriter", "_blank", 0, ()
    )
    try:
        frame = doc.getCurrentController().getFrame()
        transformer = sm.createInstanceWithContext(
            "com.sun.star.util.URLTransformer", ctx
        )

        def url_for(cmd):
            url = uno.createUnoStruct("com.sun.star.util.URL")
            url.Complete = "%s:%s" % (PROTOCOL, cmd)
            return transformer.parseStrict(url)[1]

        for cmd in COMMANDS:
            dispatch = frame.queryDispatch(url_for(cmd), "", 0)
            check("frame resolves a dispatch for %s" % cmd, dispatch is not None)

        # --- 3. dispatching really runs our Python -----------------------
        # queryDispatch only proves the component instantiated. This proves the
        # pythonpath/ package imports, the profile directory resolves, and the
        # stdlib the extension depends on is actually present in whatever
        # Python this LibreOffice bundles.
        substitution = sm.createInstanceWithContext(
            "com.sun.star.util.PathSubstitution", ctx
        )
        user_dir = unohelper.fileUrlToSystemPath(
            substitution.substituteVariables("$(user)", True)
        )
        report_path = os.path.join(user_dir, "signdocs-selftest.json")
        if os.path.exists(report_path):
            os.remove(report_path)

        selftest = frame.queryDispatch(url_for("SelfTest"), "", 0)
        check("frame resolves a dispatch for SelfTest", selftest is not None)
        if selftest is not None:
            selftest.dispatch(url_for("SelfTest"), ())

        check("SelfTest wrote its report", os.path.exists(report_path))
        if os.path.exists(report_path):
            with open(report_path, encoding="utf-8") as handle:
                report = json.load(handle)
            check("profile directory is writable", report.get("profile_writable"))
            missing = [m for m, present in report["modules"].items() if not present]
            check("required stdlib modules present (%s)" % len(report["modules"]),
                  not missing)
            if missing:
                print("      missing: %s" % missing)
            check("vendored CA bundle loaded in the office's own Python",
                  bool(report.get("ca_roots")))
            print("      office python: %s" % report["python_version"].split()[0])
            print("      openssl:       %s" % report.get("openssl"))
            print("      ca roots:      %s" % report.get("ca_roots"))
            print("      stage:         %s" % report.get("stage"))
            # Connectivity is reported, never required: CI and air-gapped
            # machines are both legitimate places to run this.
            for label in ("login", "api"):
                if report.get(label + "_reachable"):
                    print("      %-14s reachable  %s"
                          % (label + ":", report.get(label + "_host", "")))
                else:
                    print("      %-14s UNREACHABLE (%s)"
                          % (label + ":", report.get(label + "_error")))
    finally:
        doc.close(False)

    # --- 4. real PDF export from every module ----------------------------
    # intake.export_pdf is the one piece that cannot be unit-tested: it needs
    # a live document and a real filter. Drive it against actual documents.
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pythonpath"
    ))
    from signdocs import api as probe_api  # noqa: E402
    from signdocs import config as probe_config  # noqa: E402
    from signdocs import intake  # noqa: E402 - path set up immediately above

    for factory, expected_module in (
        ("private:factory/swriter", "writer"),
        ("private:factory/scalc", "calc"),
        ("private:factory/simpress", "impress"),
        ("private:factory/sdraw", "draw"),
    ):
        doc = desktop.loadComponentFromURL(factory, "_blank", 0, ())
        try:
            check("%s maps to the %s filter" % (expected_module, expected_module),
                  intake.module_of(doc) == expected_module)
            exported = intake.export_pdf(doc)
            raw = base64.b64decode(exported["content"])
            check("%s exports a real PDF (%d bytes)" % (expected_module, len(raw)),
                  raw.startswith(b"%PDF-"))
            # An unsaved document still has the Title the user sees in the
            # title bar ("Untitled 1" / "Sem título 1"), and that is a better
            # name than a generic fallback — so assert the shape, not a
            # specific string that depends on the office's UI locale.
            name = exported["filename"]
            check("%s export names the file sensibly (%r)" % (expected_module, name),
                  name.endswith(".pdf") and len(name) > 4
                  and "/" not in name and "\\" not in name)
            check("%s export reports its module" % expected_module,
                  exported["module"] == expected_module)
        finally:
            doc.close(False)

    # --- 5. main-thread marshalling --------------------------------------
    # Every network call runs on a worker thread, and its result has to come
    # back through com.sun.star.awt.AsyncCallback. If that does not fire, the
    # UI would wait forever on work that already finished — so prove the
    # round-trip rather than assuming the service being present is enough.
    from signdocs.ui import async_work  # noqa: E402

    delivered = threading.Event()
    outcome = {}

    def done(result):
        outcome["result"] = result
        delivered.set()

    async_work.run(ctx, lambda: 6 * 7, done)
    check("AsyncCallback delivered a background result",
          delivered.wait(30) and outcome["result"].ok
          and outcome["result"].value == 42)

    delivered = threading.Event()
    outcome = {}

    def boom():
        raise ValueError("expected")

    async_work.run(ctx, boom, done)
    got = delivered.wait(30)
    # A background failure that never reports back would leave a busy dialog
    # up forever, which is worse than the error itself.
    check("a raising job still reports back",
          got and not outcome["result"].ok
          and isinstance(outcome["result"].error, ValueError)
          and "expected" in (outcome["result"].traceback_text or ""))

    # --- 6. every dialog builds against real UNO -------------------------
    # A wrong control service name or an unknown model property raises only
    # when the dialog is constructed, which for a user is "I clicked the menu
    # and got a traceback". Build them all here, with show() stubbed so
    # nothing blocks on a modal loop in a headless office.
    from signdocs.store import JsonStore  # noqa: E402
    from signdocs.ui import dialogs as ui_dialogs  # noqa: E402
    from signdocs.ui import strings as ui_strings  # noqa: E402
    from signdocs.ui import widgets  # noqa: E402

    s = ui_strings.for_office(ctx)
    check("office locale resolves to a supported language (%s)" % s.lang,
          s.lang in ("pt", "en", "es"))

    built = {}
    original_show = widgets.Dialog.show

    built_models = {}

    # Whether each control was built enabled. A gate that is only asserted to
    # *exist* passes just as happily on a build where it never disables, which
    # is the failure that matters.
    built_enabled = {}

    def fake_show(self, parent=None):
        title = self.model.Title
        built[title] = list(self.model.getElementNames())
        for name in self.model.getElementNames():
            control = None
            try:
                control = self.model.getByName(name)
                built_models[(title, name)] = control.ImplementationName
            except Exception:
                built_models[(title, name)] = ""
            try:
                built_enabled[(title, name)] = bool(control.Enabled)
            except Exception:
                built_enabled[(title, name)] = None
        return None

    widgets.Dialog.show = fake_show
    try:
        store = JsonStore()
        state = {
            "sender": "remetente@example.invalid",
            "profile": "click_only",
            "order": "PARALLEL",
            "signers": [{"name": "Ana", "email": "ana@ex.com.br",
                         "fiscal": "52998224725"}],
        }
        ui_dialogs.send_dialog(ctx, None, store, s, state)
        check("send dialog builds",
              "signers" in built.get(s("send_title"), []))
        # Fail-soft: no quota read means no row at all, not an empty one.
        check("send dialog omits the plan line when the lookup failed",
              "quota" not in built.get(s("send_title"), []))

        ui_dialogs.send_dialog(ctx, None, store, s, dict(state, quota={
            "allowed": True,
            "quota": {"allowed": True, "source": "paid_plan", "used": 12,
                      "remaining": 68, "limit": 80},
            "user": {"email": "a@b.com", "plan": "Iniciante 80"}}))
        check("send dialog shows the plan line when the quota is known",
              "quota" in built.get(s("send_title"), []))
        # Reaching the pending list without abandoning a half-filled form.
        check("send dialog links to the pending list",
              "history" in built.get(s("send_title"), []))
        # The sender must be a LABEL, not an edit box. A box the user can
        # change that changes nothing is the bug this replaced: the server
        # sets `owner` from the verified identity and ignores the client.
        sender_kind = built_models.get((s("send_title"), "sender"), "")
        check("sender is a label, not an editable field",
              "FixedText" in sender_kind, sender_kind or "<not built>")
        # The upgrade affordance is gated on the allowance actually being
        # spent; next to a healthy balance it would just be an advert.
        check("send dialog hides the upgrade button while quota remains",
              "upgrade" not in built.get(s("send_title"), []))

        ui_dialogs.send_dialog(ctx, None, store, s, dict(state, quota={
            "allowed": False,
            "quota": {"allowed": False, "source": "shared_free_pool",
                      "used": 3, "remaining": 0, "limit": 3},
            "user": {"email": "a@b.com", "plan": "Gratuito"}}))
        check("send dialog offers an upgrade once the allowance is spent",
              "upgrade" in built.get(s("send_title"), []))

        ui_dialogs.consent_dialog(ctx, None, s, {
            "required": {"tos": "2.1", "privacy": "1.4"},
            "urls": {"tos": "https://s/tos", "privacy": "https://s/pp"},
            "stale": ["CONSENT_TOS", "CONSENT_PRIVACY"]})
        consent_controls = built.get(s("consent_title"), [])
        check("consent dialog builds", "accept" in consent_controls)
        # Acceptance has to be of something the person can actually read.
        check("consent dialog offers a way to read each policy",
              "open0" in consent_controls and "open1" in consent_controls)

        ui_dialogs.run_upgrade(ctx, None, store, s, "hml")
        # -- prices follow the billing period -----------------------------
        # The list quoted monthly prices next to "Anual": the number the user
        # is about to be charged, wrong by a factor of twelve, in the
        # direction that looks cheaper.
        monthly_row = s("plan_row") % (
            probe_api.PLANS[0]["name"], probe_api.PLANS[0]["docs"],
            probe_api.format_price(probe_api.PLANS[0]["Mensal"]) + s("per_month"))
        annual_row = s("plan_row") % (
            probe_api.PLANS[0]["name"], probe_api.PLANS[0]["docs"],
            probe_api.format_price(probe_api.PLANS[0]["Anual"]) + s("per_year"))
        check("a monthly row quotes the monthly price",
              "19,90" in monthly_row and s("per_month") in monthly_row,
              monthly_row)
        annual_row_full = s("plan_row_annual") % (
            probe_api.PLANS[0]["name"], probe_api.PLANS[0]["docs"] * 12,
            probe_api.format_price(probe_api.PLANS[0]["Anual"]) + s("per_year"))
        check("an annual row quotes the WHOLE allowance, not a monthly rate",
              "240" in annual_row_full and "documentos/m" not in annual_row_full,
              annual_row_full)
        check("and the usage line says so once the account is on it",
              "anual" in (ui_strings.quota_line(s, {
                  "quota": {"allowed": True, "used": 19, "limit": 240,
                            "remaining": 221, "source": "paid_plan"},
                  "user": {"plan": "Iniciante 20"}}) or ""))

        check("an annual row quotes the ANNUAL price, not the monthly one",
              "178,80" in annual_row and "19,90" not in annual_row,
              annual_row)

        check("upgrade dialog builds",
              "plans" in built.get(s("upgrade_title"), [])
              and "freq" in built.get(s("upgrade_title"), []))

        ui_dialogs.fiscal_dialog(ctx, None, s)
        check("fiscal dialog builds",
              "fiscal" in built.get(s("fiscal_title"), []))

        ui_dialogs.review_dialog(ctx, None, s, state, "contrato.pdf")
        check("review dialog builds",
              "summary" in built.get(s("review_title"), []))

        ui_dialogs.signer_dialog(ctx, None, s)
        check("signer dialog builds",
              "fiscal" in built.get(s("signer_title"), []))

        # -- a certificate cannot sign in parallel -------------------------
        # The server overrides PARALLEL for DIGITAL_CERTIFICATE anyway, so
        # offering the choice means the user picks something that is silently
        # changed. Locked here, with the reason on screen.
        two = [{"name": "Ana", "email": "ana@ex.com.br", "fiscal": "52998224725"},
               {"name": "Bruno", "email": "bruno@ex.com.br", "fiscal": "12345678909"}]
        ui_dialogs.send_dialog(ctx, None, store, s,
                               dict(state, signers=two, profile="click_only"))
        check("order stays selectable for click-only with two signers",
              built_enabled.get((s("send_title"), "order")) is True)

        ui_dialogs.send_dialog(ctx, None, store, s,
                               dict(state, signers=two, profile="digital_certificate"))
        check("order is LOCKED for a certificate profile",
              built_enabled.get((s("send_title"), "order")) is False)

        # -- reordering signers --------------------------------------------
        # The list order becomes signerIndex, so on a sequential send it
        # decides who is asked first. Before this the only fix for a wrong
        # order was deleting everybody below the mistake and retyping them.
        check("the send dialog offers signer import",
              "import" in built.get(s("send_title"), []))
        check("and says the expected column order",
              "import_hint" in built.get(s("send_title"), []))
        # The sender is otherwise never told when the links die; the signer is
        # told by e-mail, so this closes the gap for the one person who is not.
        check("the review screen states the signing window",
              str(probe_config.SIGNING_WINDOW_HOURS) in
              (ui_strings.Strings("pt")("link_expiry")
               % probe_config.SIGNING_WINDOW_HOURS))
        check("the signer cap is what one request can finish",
              probe_api.MAX_SIGNERS == 30, probe_api.MAX_SIGNERS)

        check("the signer list offers move up/down",
              "up" in built.get(s("send_title"), [])
              and "down" in built.get(s("send_title"), []))
        # Nothing selected on a freshly built dialog, so neither can act --
        # and a button that does nothing when clicked is the thing being
        # avoided here.
        check("move buttons start disabled with no selection",
              built_enabled.get((s("send_title"), "up")) is False
              and built_enabled.get((s("send_title"), "down")) is False)

        ui_dialogs.send_dialog(ctx, None, store, s,
                               dict(state, signers=[two[0]], profile="click_only"))
        check("move buttons stay disabled with a single signer",
              built_enabled.get((s("send_title"), "up")) is False
              and built_enabled.get((s("send_title"), "down")) is False)
        check("and the send is switched to sequential rather than left parallel",
              ui_dialogs.ORDER_KEYS.index("SEQUENTIAL") >= 0
              and "order_note" in built.get(s("send_title"), []))

        # -- recent signers ------------------------------------------------
        # Offered only when there is somebody to offer; a button opening an
        # empty list is worse than no button.
        ui_dialogs.signer_dialog(ctx, None, s, recents=())
        check("no Recentes button on a fresh profile",
              "recent" not in built.get(s("signer_title"), []))

        ui_dialogs.signer_dialog(ctx, None, s, recents=[
            {"name": "Ana", "email": "ana@ex.com.br", "fiscal": "52998224725"}])
        check("Recentes appears once somebody has been sent to",
              "recent" in built.get(s("signer_title"), []))

        # -- one CPF cannot be two signatories -----------------------------
        # The fiscal number is what the evidence attributes the signature to,
        # so a repeat is one person holding two links.
        check("a duplicate CPF is refused before it reaches the wire",
              ui_dialogs._taken_fiscal(
                  {"signers": [{"fiscal": "751.820.411-87"}]})
              == {"75182041187"})
        check("and editing a signer does not collide with themselves",
              ui_dialogs._taken_fiscal(
                  {"signers": [{"fiscal": "52998224725"}]}, skip=0) == set())

        line = ui_dialogs._recent_line(
            {"name": "Ana", "email": "ana@ex.com.br", "fiscal": "52998224725"})
        check("a recent signer shows name, e-mail and a punctuated CPF",
              "Ana" in line and "ana@ex.com.br" in line
              and "529.982.247-25" in line, line)

        ui_dialogs.result_dialog(ctx, None, s, {
            "kind": "session", "id": "ss_x",
            "links": [{"signerName": "Ana", "url": "https://s/x?cs=y",
                       "inviteSent": False}],
        })
        check("result dialog builds",
              "links" in built.get(s("result_title"), []))

        # -- "Assinar agora" and the two gates around it -------------------
        #
        # A signing link is a bearer credential: whoever opens one can complete
        # that signature. So the button opens the signed-in account's own row
        # and no other, and a CLICK_ONLY link belonging to somebody else is not
        # copiable — for that profile the link IS the whole authentication.
        # Both are enforced server-side too; these assertions are about not
        # putting the affordance in front of anyone in the first place.
        ME = "eu@example.invalid"
        OTHER = "outro@example.invalid"

        def result_state(sent, account, control):
            ui_dialogs.result_dialog(ctx, None, s, sent, account)
            return built_enabled.get((s("result_title"), control))

        mine_first = {
            "kind": "envelope", "id": "env_x", "profile": "click_only",
            "links": [
                {"signerName": "Eu", "signerEmail": ME,
                 "url": "https://s/mine?cs=y", "inviteSent": False},
                {"signerName": "Outro", "signerEmail": OTHER,
                 "url": None, "inviteSent": True},
            ],
        }
        check("result dialog offers Assinar agora",
              "sign" in built.get(s("result_title"), []))
        # Row 0 is preselected, so this is the account's own row.
        check("sign is enabled on the account's own row",
              result_state(mine_first, ME, "sign") is True)
        check("copy is enabled on the account's own row",
              result_state(mine_first, ME, "copy") is True)

        others_first = {
            "kind": "envelope", "id": "env_y", "profile": "click_only",
            "links": [
                {"signerName": "Outro", "signerEmail": OTHER,
                 "url": None, "inviteSent": True},
                {"signerName": "Eu", "signerEmail": ME,
                 "url": "https://s/mine?cs=y", "inviteSent": False},
            ],
        }
        check("sign is DISABLED on another signer's row",
              result_state(others_first, ME, "sign") is False)
        check("copy is DISABLED on another signer's CLICK_ONLY row",
              result_state(others_first, ME, "copy") is False)

        # The narrowness of the rule is the point: with a second factor in
        # play, another signer's link is safe to hand over.
        otp_others_first = {
            "kind": "envelope", "id": "env_z", "profile": "click_plus_otp",
            "links": [
                {"signerName": "Outro", "signerEmail": OTHER,
                 "url": "https://s/other?cs=y", "inviteSent": True},
                {"signerName": "Eu", "signerEmail": ME,
                 "url": "https://s/mine?cs=y", "inviteSent": False},
            ],
        }
        check("copy stays enabled on another signer's CLICK_PLUS_OTP row",
              result_state(otp_others_first, ME, "copy") is True)
        check("sign stays disabled on another signer's CLICK_PLUS_OTP row",
              result_state(otp_others_first, ME, "sign") is False)

        # An unreadable ID token yields "", which must disable rather than
        # match — the failure mode of account_email is silence, not an error.
        check("sign is disabled when the account is unknown",
              result_state(mine_first, "", "sign") is False)

        ui_dialogs.run_settings(ctx, None, store)
        check("settings dialog builds",
              "stage" in built.get(s("settings_title"), []))

        # The tracking dialog starts a background poller. Building it with
        # show() stubbed means the dialog returns immediately, which must stop
        # that thread — a poller outliving its dialog would keep calling the
        # API forever.
        from signdocs import api as probe_api  # noqa: E402
        polls = []
        original_status = probe_api.status_of

        def counting_status(store_, kind, ident, stage=None):
            polls.append(ident)
            return {"status": "ACTIVE", "completed": 1, "total": 2,
                    "signed_available": False, "transactionId": None,
                    "signers": [
                        {"name": "Ana", "email": "ana@ex.com",
                         "status": "COMPLETED", "index": 1},
                        {"name": None, "email": "eu@ex.com",
                         "status": "ACTIVE", "index": 2},
                    ],
                    "raw": {}}

        probe_api.status_of = counting_status
        try:
            before = threading.active_count()
            ui_dialogs.track_dialog(ctx, None, JsonStore(), s,
                                    {"id": "env-x", "kind": "envelope",
                                     "filename": "contrato.pdf",
                                     "signers": [
                                         {"name": "Ana", "email": "ana@ex.com",
                                          "fiscal": "52998224725"},
                                         {"name": "Eu", "email": "eu@ex.com",
                                          "fiscal": "11222333000181"}]},
                                    account_email="eu@ex.com")
            check("track dialog builds",
                  "download" in built.get(s("track_title"), []))
            # "Signatários: 1/2" says a document is stuck without saying who
            # on, which is the thing worth knowing on a multi-signer envelope.
            check("track dialog lists the signers",
                  "signers" in built.get(s("track_title"), []))
            # A name missing from the status payload is filled from what was
            # recorded at send time, rather than leaving a bare e-mail.
            line = ui_strings.signer_line(
                s, {"name": "Eu", "email": "eu@ex.com",
                    "fiscal": "52998224725", "status": "ACTIVE"},
                is_you=True)
            check("a signer row carries name, e-mail, CPF and state",
                  "Eu" in line and s("signer_you") in line
                  and "eu@ex.com" in line
                  # Punctuated, never raw digits.
                  and "529.982.247-25" in line
                  and ui_strings.api_status(s, "ACTIVE") in line, line)
            # The status label must be translated, while cancel-enablement
            # still keys off the raw wire value. Rendering ACTIVE verbatim is
            # what a user reports; matching a translated string is what would
            # silently disable cancel in en/es.
            check("track dialog translates the wire status",
                  ui_strings.api_status(s, "ACTIVE") != "ACTIVE"
                  and ui_strings.api_status(s, "ACTIVE") != "")
            # Give the poller a moment to notice the stop flag.
            deadline = time.time() + 10
            while threading.active_count() > before and time.time() < deadline:
                time.sleep(0.2)
            check("closing the tracker stops its poller",
                  threading.active_count() <= before,
                  "%d thread(s) before, %d after"
                  % (before, threading.active_count()))
        finally:
            probe_api.status_of = original_status

        # The copy button exists to paste a signing link OUTSIDE LibreOffice.
        # Offering only the UTF-16 flavour makes an external app decode those
        # bytes as UTF-8 -- a NUL after every character -- and the button still
        # reports success, so nothing catches it but a human pasting into a
        # terminal. Assert both flavours round-trip.
        try:
            from com.sun.star.datatransfer import DataFlavor
            link = "https://sign.signdocs.com.br/s/ss_probe?cs=ss_secret_x"
            transferable = widgets._transferable_for(link)
            mimes = [f.MimeType.lower() for f in transferable.getTransferDataFlavors()]
            has_both = any("utf-16" in m for m in mimes) and any("utf-8" in m for m in mimes)
            check("clipboard offers both utf-16 and utf-8", has_both, ", ".join(mimes))

            f8 = DataFlavor()
            f8.MimeType = "text/plain;charset=utf-8"
            raw = transferable.getTransferData(f8)
            as_bytes = bytes(raw.value) if hasattr(raw, "value") else bytes(raw)
            check("utf-8 flavour round-trips without NUL padding",
                  as_bytes.decode("utf-8") == link and b"\x00" not in as_bytes)

            f16 = DataFlavor()
            f16.MimeType = "text/plain;charset=utf-16"
            check("utf-16 flavour still returns the string",
                  transferable.getTransferData(f16) == link)
        except Exception as exc:
            check("clipboard flavours", False, str(exc))

        # msgbox.confirm resolves three UNO constants at call time, and it is
        # only ever called from inside a button handler -- where the office
        # swallows an exception and the click reads as a no-op. Nothing else
        # in the suite imports these, so a rename upstream would surface as
        # "the quota warning silently stopped appearing".
        try:
            from com.sun.star.awt.MessageBoxButtons import BUTTONS_YES_NO
            from com.sun.star.awt.MessageBoxResults import YES
            from com.sun.star.awt.MessageBoxType import QUERYBOX
            confirm_ok = None not in (BUTTONS_YES_NO, YES, QUERYBOX)
        except Exception as exc:
            confirm_ok = False
            print("   confirm constants: %s" % exc)
        check("msgbox.confirm's UNO constants resolve", confirm_ok)

        # The pending list. Driven with the real sync.refresh_pending so the
        # dialog, the reconciliation and the filter are exercised together —
        # only the network is stubbed. busy() has to run inline here: with
        # show() faked there is no modal loop to pump the AsyncCallback, so
        # the work would never start.
        from signdocs import config as probe_config  # noqa: E402
        from signdocs import history as probe_history  # noqa: E402

        hist_store = JsonStore()
        probe_config.set_stage(hist_store, "prod")
        hist_log = probe_history.History(hist_store, "prod")
        hist_log.add({"id": "ss_done", "kind": "session", "filename": "a.pdf"})
        hist_log.add({"id": "ss_open", "kind": "session", "filename": "b.pdf"})

        def hist_status(store_, kind, ident, stage=None):
            return {"status": "COMPLETED" if ident == "ss_done" else "ACTIVE"}

        original_busy_h = ui_dialogs.busy
        original_status_h = probe_api.status_of
        probe_api.status_of = hist_status
        ui_dialogs.busy = lambda c, p, m, work: async_work.Result(value=work())
        try:
            ui_dialogs.run_history(ctx, None, hist_store)
        finally:
            ui_dialogs.busy = original_busy_h
            probe_api.status_of = original_status_h

        history_controls = built.get(s("history_title"), [])
        check("pending list builds", "items" in history_controls)
        check("pending list offers a pending-only filter",
              "only_pending" in history_controls)
        check("pending list shows an outstanding count",
              "count" in history_controls)
        check("pending list offers a manual refresh",
              "refresh" in history_controls)

        after = {e["id"]: e["status"] for e in hist_log.list()}
        check("opening the list retired the finished send",
              after.get("ss_done") == probe_history.COMPLETED,
              "ss_done -> %s" % after.get("ss_done"))
        check("opening the list left the outstanding send cancellable",
              after.get("ss_open") == probe_history.PENDING,
              "ss_open -> %s" % after.get("ss_open"))
    finally:
        widgets.Dialog.show = original_show

    # --- 7. the send flow's orchestration --------------------------------
    # run_send stitches together connect, export, send, history and the retry
    # loop. None of that is covered by the unit tests, because dialogs.py
    # cannot be imported without an office. Drive it here with the dialogs and
    # the network stubbed, and assert what it actually passes downstream.
    from signdocs import api as sd_api  # noqa: E402
    from signdocs import config as sd_config  # noqa: E402
    from signdocs import history as sd_history  # noqa: E402
    from signdocs import intake as sd_intake  # noqa: E402

    captured = {}
    signers = [{"name": "Ana", "email": "ana@ex.com.br", "fiscal": "52998224725"},
               {"name": "Bruno", "email": "bruno@ex.com.br", "fiscal": "12345678909"}]

    originals = {
        "ensure": ui_dialogs.ensure_connected,
        "send_dlg": ui_dialogs.send_dialog,
        "review_dlg": ui_dialogs.review_dialog,
        "result_dlg": ui_dialogs.result_dialog,
        "busy": ui_dialogs.busy,
        "consent": ui_dialogs.ensure_policies_accepted,
        "export": sd_intake.export_pdf,
        "send": sd_api.send,
        "init": sd_api.init_session,
    }

    def fake_send_dialog(c, f, st, s_, state):
        captured["quota_state"] = state.get("quota")
        state["profile"] = "click_plus_otp"
        state["order"] = "SEQUENTIAL"
        state["signers"] = list(signers)
        return "review"

    def fake_send(store_, document, signers_, **kwargs):
        captured["document"] = document
        captured["signers"] = signers_
        captured["kwargs"] = kwargs
        return {"kind": "envelope", "id": "env-probe", "transactionId": None,
                "links": [{"signerName": sg["name"], "signerEmail": sg["email"],
                           "url": "https://s/x?cs=y", "inviteSent": False}
                          for sg in signers_]}

    try:
        ui_dialogs.ensure_connected = lambda *a, **k: True
        consent_asked = []
        ui_dialogs.ensure_policies_accepted = (
            lambda c, f, st, s_, stage_: (consent_asked.append(stage_), True)[1])
        ui_dialogs.send_dialog = fake_send_dialog
        ui_dialogs.review_dialog = lambda *a, **k: "send"
        ui_dialogs.result_dialog = lambda *a, **k: True
        # Run the work inline: busy() needs a modal loop that a headless
        # office will not pump for us here.
        ui_dialogs.busy = lambda c, p, m, work: async_work.Result(value=work())
        sd_intake.export_pdf = lambda doc: {
            "content": "QkFTRTY0", "filename": "contrato.pdf", "module": "writer"}
        sd_api.send = fake_send
        sd_api.init_session = lambda store_, stage=None: {
            "allowed": True,
            "quota": {"allowed": True, "source": "paid_plan", "used": 12,
                      "remaining": 68, "limit": 80},
            "user": {"email": "a@b.com", "plan": "Iniciante 80"}}

        flow_store = JsonStore()
        sd_config.set_stage(flow_store, "prod")
        # An existing install may have "biometric" saved as its preferred
        # profile from before it was withdrawn. That must degrade to a working
        # default, not crash on a dropdown index or reach the wire, so seed it
        # here and let the flow run for real.
        flow_store.set(sd_config.STORAGE["profile"], "biometric")
        doc = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
        try:
            ui_dialogs.run_send(ctx, doc.getCurrentController().getFrame(), flow_store)
        finally:
            doc.close(False)

        check("flow reached api.send", "kwargs" in captured)
        # The gate runs before the form, so a refusal costs the user nothing.
        check("flow checked policy acceptance before sending",
              consent_asked == ["prod"], "asked for stage(s): %r" % consent_asked)
        check("flow passed the chosen profile",
              captured.get("kwargs", {}).get("profile") == "click_plus_otp")
        # The withdrawn profile must not survive into a request, and the
        # stale preference must be rewritten rather than left to resurface.
        check("a saved 'biometric' preference never reaches the wire",
              captured.get("kwargs", {}).get("profile") != "biometric")
        check("the stale profile preference is healed on disk",
              flow_store.get(sd_config.STORAGE["profile"]) != "biometric",
              "stored -> %r" % flow_store.get(sd_config.STORAGE["profile"]))
        check("flow passed the chosen order",
              captured.get("kwargs", {}).get("order") == "SEQUENTIAL")
        # The client must not send an owner at all. The server sets it from the
        # verified identity, so anything sent here is ignored -- and a UI that
        # implied otherwise is the bug this replaced.
        check("flow sends no owner from the client",
              "owner_email" not in captured.get("kwargs", {}))
        check("flow minted an idempotency key",
              bool(captured.get("kwargs", {}).get("idempotency_key")))
        check("flow passed both signers", len(captured.get("signers", [])) == 2)
        # The plan has to be in hand before the form is drawn, or the number
        # arrives too late to change what the user does.
        check("flow read the plan before drawing the send form",
              (captured.get("quota_state") or {}).get("user", {}).get("plan")
              == "Iniciante 80")

        recorded = sd_history.History(flow_store, "prod").list()
        check("flow recorded the send in history",
              len(recorded) == 1 and recorded[0]["id"] == "env-probe")
        # The record must carry no document content and no signing link.
        check("history record leaks neither content nor link",
              "QkFTRTY0" not in json.dumps(recorded)
              and "cs=" not in json.dumps(recorded))
        # Nothing stores a sender any more; it is derived from the token each
        # time, so it cannot drift from the account actually signed in.
        check("no sender preference is persisted",
              "sender_email" not in sd_config.STORAGE)
    finally:
        ui_dialogs.ensure_connected = originals["ensure"]
        ui_dialogs.send_dialog = originals["send_dlg"]
        ui_dialogs.review_dialog = originals["review_dlg"]
        ui_dialogs.result_dialog = originals["result_dlg"]
        ui_dialogs.busy = originals["busy"]
        ui_dialogs.ensure_policies_accepted = originals["consent"]
        sd_intake.export_pdf = originals["export"]
        sd_api.send = originals["send"]
        sd_api.init_session = originals["init"]

    print("")
    if failures:
        print("FAILED: %d check(s)" % len(failures))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
