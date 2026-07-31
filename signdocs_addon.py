# SPDX-License-Identifier: MPL-2.0
#
# UNO entry point. Deliberately thin: it resolves a command URL to a handler
# and does nothing else. All real logic lives in pythonpath/signdocs/, which
# LibreOffice puts on sys.path automatically for components in this extension
# — that split is what lets the logic modules be unit-tested without a running
# office.

import traceback

import unohelper
from com.sun.star.frame import XDispatch, XDispatchProvider
from com.sun.star.lang import XInitialization, XServiceInfo

IMPL_NAME = "br.com.signdocs.libreoffice.ProtocolHandler"
SERVICE_NAME = "com.sun.star.frame.ProtocolHandler"
PROTOCOL = "br.com.signdocs.libreoffice"


def _command_of(url):
    """
    Pull the bare command out of a dispatch URL.

    A transformed URL exposes Protocol='br.com.signdocs.libreoffice:' and
    Path='Enviar'. An untransformed one only has Main. Handle both rather than
    trusting the caller to have run the URL through the transformer.
    """
    path = getattr(url, "Path", "") or ""
    if path:
        return path
    main = getattr(url, "Main", "") or getattr(url, "Complete", "") or ""
    prefix = PROTOCOL + ":"
    return main[len(prefix):] if main.startswith(prefix) else ""


class SignDocsProtocolHandler(
    unohelper.Base,
    XDispatchProvider,
    XDispatch,
    XServiceInfo,
    XInitialization,
):
    def __init__(self, ctx):
        self.ctx = ctx
        self.frame = None

    # -- XInitialization ---------------------------------------------------
    def initialize(self, args):
        # Protocol handlers are constructed with the frame they belong to.
        if args:
            self.frame = args[0]

    # -- XDispatchProvider -------------------------------------------------
    def queryDispatch(self, url, target_frame_name, search_flags):
        protocol = getattr(url, "Protocol", "") or ""
        main = getattr(url, "Main", "") or ""
        if protocol == PROTOCOL + ":" or main.startswith(PROTOCOL + ":"):
            return self
        return None

    def queryDispatches(self, requests):
        return tuple(
            self.queryDispatch(r.FeatureURL, r.FrameName, r.SearchFlags)
            for r in requests
        )

    # -- XDispatch ---------------------------------------------------------
    def dispatch(self, url, args):
        command = _command_of(url)
        try:
            from signdocs import commands
            commands.run(self.ctx, self.frame, command)
        except Exception:
            # A raised exception inside dispatch() is swallowed by the office
            # and the click looks like a no-op. Always surface it.
            self._fatal(traceback.format_exc())

    def addStatusListener(self, listener, url):
        pass

    def removeStatusListener(self, listener, url):
        pass

    # -- XServiceInfo ------------------------------------------------------
    def getImplementationName(self):
        return IMPL_NAME

    def supportsService(self, name):
        return name == SERVICE_NAME

    def getSupportedServiceNames(self):
        return (SERVICE_NAME,)

    # -- internals ---------------------------------------------------------
    def _fatal(self, detail):
        try:
            from com.sun.star.awt.MessageBoxButtons import BUTTONS_OK
            from com.sun.star.awt.MessageBoxType import ERRORBOX

            toolkit = self.ctx.ServiceManager.createInstanceWithContext(
                "com.sun.star.awt.Toolkit", self.ctx
            )
            parent = self.frame.getContainerWindow() if self.frame else None
            box = toolkit.createMessageBox(
                parent, ERRORBOX, BUTTONS_OK, "SignDocs Brasil", detail
            )
            box.execute()
            box.dispose()
        except Exception:
            # Last resort: the office log.
            print("SignDocs Brasil: " + detail)


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(
    SignDocsProtocolHandler, IMPL_NAME, (SERVICE_NAME,)
)
