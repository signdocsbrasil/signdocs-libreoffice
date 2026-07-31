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

import json
import os
import sys

import uno
import unohelper
from com.sun.star.beans import PropertyValue

PORT = sys.argv[1] if len(sys.argv) > 1 else "2103"
PROTOCOL = "br.com.signdocs.libreoffice"
COMMANDS = ("Enviar", "Historico", "Configurar")

failures = []


def check(label, condition):
    print("  %s %s" % ("ok " if condition else "FAIL", label))
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
            if report.get("auth_reachable"):
                print("      auth:          reachable, issuer %s"
                      % report.get("auth_issuer"))
            else:
                print("      auth:          UNREACHABLE (%s)"
                      % report.get("auth_error"))
    finally:
        doc.close(False)

    print("")
    if failures:
        print("FAILED: %d check(s)" % len(failures))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
