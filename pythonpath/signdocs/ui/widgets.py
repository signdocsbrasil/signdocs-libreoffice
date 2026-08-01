# SPDX-License-Identifier: MPL-2.0
"""
A thin layer over UNO dialog construction.

Dialogs are built programmatically rather than from static `.xdl` files
because the signer list and the result list both vary at runtime, and a fixed
resource file cannot express that. The cost is verbosity, which is what this
module absorbs.

Coordinates are in map-AppFont units, roughly half a character wide and an
eighth of a line tall — so a 260-wide dialog is a comfortable form width.

Main thread only. Everything here touches UNO.
"""

import unohelper
from com.sun.star.awt import XActionListener, XItemListener

# Layout constants, so dialogs read as intent rather than arithmetic.
MARGIN = 8
ROW = 14
LABEL_W = 62
BUTTON_W = 54
BUTTON_H = 14


class _Action(unohelper.Base, XActionListener):
    def __init__(self, fn):
        self._fn = fn

    def actionPerformed(self, event):  # noqa: N802 - UNO API name
        self._fn()

    def disposing(self, event):
        pass


class _Item(unohelper.Base, XItemListener):
    def __init__(self, fn):
        self._fn = fn

    def itemStateChanged(self, event):  # noqa: N802 - UNO API name
        self._fn()

    def disposing(self, event):
        pass


class Dialog(object):
    """
    One dialog, built control by control.

    Listeners are kept in `self._listeners` for the dialog's lifetime: UNO
    holds them weakly, and a garbage-collected listener silently stops firing,
    which presents as a button that does nothing.
    """

    def __init__(self, ctx, title, width, height):
        self.ctx = ctx
        self._smgr = ctx.ServiceManager
        self._listeners = []
        self._result = None

        self.model = self._smgr.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialogModel", ctx
        )
        self.model.PositionX = 0
        self.model.PositionY = 0
        self.model.Width = width
        self.model.Height = height
        self.model.Title = title

        self.dialog = self._smgr.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialog", ctx
        )
        self.dialog.setModel(self.model)

    # -- construction ------------------------------------------------------
    def _add(self, service, name, x, y, w, h, **props):
        control = self.model.createInstance("com.sun.star.awt." + service)
        control.PositionX = x
        control.PositionY = y
        control.Width = w
        control.Height = h
        for key, value in props.items():
            setattr(control, key, value)
        self.model.insertByName(name, control)
        return control

    def label(self, name, x, y, w, h, text, **props):
        return self._add("UnoControlFixedTextModel", name, x, y, w, h,
                         Label=text, **props)

    def edit(self, name, x, y, w, h, text="", **props):
        return self._add("UnoControlEditModel", name, x, y, w, h,
                         Text=text, **props)

    def listbox(self, name, x, y, w, h, items=(), selected=0, **props):
        control = self._add("UnoControlListBoxModel", name, x, y, w, h,
                            Dropdown=True, **props)
        control.StringItemList = tuple(items)
        if items:
            control.SelectedItems = (selected,)
        return control

    def listctl(self, name, x, y, w, h, items=(), **props):
        """Multi-line, non-dropdown list used for signers and results."""
        control = self._add("UnoControlListBoxModel", name, x, y, w, h,
                            Dropdown=False, **props)
        control.StringItemList = tuple(items)
        return control

    def button(self, name, x, y, w, h, text, on_click=None, **props):
        control = self._add("UnoControlButtonModel", name, x, y, w, h,
                            Label=text, **props)
        if on_click is not None:
            listener = _Action(on_click)
            self._listeners.append(listener)
            self.dialog.getControl(name).addActionListener(listener)
        return control

    def check(self, name, x, y, w, h, text, state=False, **props):
        return self._add("UnoControlCheckBoxModel", name, x, y, w, h,
                         Label=text, State=1 if state else 0, **props)

    def on_change(self, name, fn):
        listener = _Item(fn)
        self._listeners.append(listener)
        self.dialog.getControl(name).addItemListener(listener)

    # -- access ------------------------------------------------------------
    def control(self, name):
        return self.dialog.getControl(name)

    def get(self, name):
        return getattr(self.model.getByName(name), "Text", "")

    def set(self, name, text):
        self.model.getByName(name).Text = text

    def selected_index(self, name):
        items = self.model.getByName(name).SelectedItems
        return items[0] if items else -1

    def set_items(self, name, items, keep_selection=True):
        control = self.model.getByName(name)
        previous = self.selected_index(name)
        control.StringItemList = tuple(items)
        if keep_selection and items:
            index = previous if 0 <= previous < len(items) else 0
            control.SelectedItems = (index,)

    def enable(self, name, enabled=True):
        self.model.getByName(name).Enabled = bool(enabled)

    # -- lifecycle ---------------------------------------------------------
    def finish(self, value):
        """
        Close a modal dialog and hand `value` back to whoever executed it.

        Guarded: a background job can complete after the user has already
        dismissed the dialog with the window close button, and calling
        endExecute on a disposed peer would raise inside a callback where
        there is nobody to catch it.
        """
        self._result = value
        try:
            self.dialog.endExecute()
        except Exception:
            pass

    def show(self, parent=None):
        """
        Run modally. Returns whatever `finish()` was given, or None if the
        dialog was dismissed with the window close button.
        """
        toolkit = self._smgr.createInstanceWithContext(
            "com.sun.star.awt.Toolkit", self.ctx
        )
        self.dialog.createPeer(toolkit, parent)
        try:
            self.dialog.execute()
        finally:
            self.dialog.dispose()
        return self._result

    def dispose(self):
        try:
            self.dialog.dispose()
        except Exception:
            pass


def parent_window(frame):
    try:
        return frame.getContainerWindow() if frame else None
    except Exception:
        return None


def copy_to_clipboard(ctx, text):
    """
    Put text on the system clipboard.

    Returns True on success. The result matters: on a headless or restricted
    session there may be no clipboard, and the caller should say "copy this"
    rather than claim it copied something.
    """
    try:
        import uno
        from com.sun.star.datatransfer import DataFlavor, XTransferable

        class _Text(unohelper.Base, XTransferable):
            def __init__(self, value):
                self._value = value
                flavor = DataFlavor()
                flavor.MimeType = "text/plain;charset=utf-16"
                flavor.HumanPresentableName = "Unicode text"
                flavor.DataType = uno.getTypeByName("string")
                self._flavor = flavor

            def getTransferData(self, flavor):  # noqa: N802 - UNO API name
                return self._value

            def getTransferDataFlavors(self):  # noqa: N802 - UNO API name
                return (self._flavor,)

            def isDataFlavorSupported(self, flavor):  # noqa: N802 - UNO API name
                return flavor.MimeType == self._flavor.MimeType

        clipboard = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.datatransfer.clipboard.SystemClipboard", ctx
        )
        clipboard.setContents(_Text(text), None)
        return True
    except Exception:
        return False
