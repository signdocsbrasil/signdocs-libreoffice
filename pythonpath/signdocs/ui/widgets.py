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

    def get_state(self, name):
        """Checkbox state as a bool. UNO models it as 0/1/2 (2 = tristate)."""
        return bool(getattr(self.model.getByName(name), "State", 0))

    def set_label(self, name, text):
        """
        Retext a label or button after construction.

        Distinct from `set`, which writes `Text` on an edit field. Labels carry
        `Label`, and assigning the wrong one fails silently — the control keeps
        its old caption and nothing is raised.
        """
        self.model.getByName(name).Label = text

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
            """
            The same text offered as both UTF-16 and UTF-8.

            Offering only UTF-16 is what LibreOffice's own examples show, and
            it works perfectly for pastes back into the office. But an
            external application asking the system clipboard for text gets
            handed the only flavour on offer and decodes those bytes as UTF-8
            — one NUL after every character. Pasting a signing link into a
            terminal produced pages of `^@` gibberish, and the copy button had
            reported success.

            So the UTF-8 flavour is not a nicety: the entire point of that
            button is pasting the link somewhere *outside* LibreOffice.
            """

            def __init__(self, value):
                self._value = value

                utf16 = DataFlavor()
                utf16.MimeType = "text/plain;charset=utf-16"
                utf16.HumanPresentableName = "Unicode text"
                # `string` lets UNO hand back a Python str and convert.
                utf16.DataType = uno.getTypeByName("string")

                utf8 = DataFlavor()
                utf8.MimeType = "text/plain;charset=utf-8"
                utf8.HumanPresentableName = "Plain text"
                # A byte sequence, because the charset is already encoded.
                utf8.DataType = uno.getTypeByName("[]byte")

                self._flavors = (utf16, utf8)

            def getTransferData(self, flavor):  # noqa: N802 - UNO API name
                mime = (getattr(flavor, "MimeType", "") or "").lower()
                if "utf-8" in mime:
                    return uno.ByteSequence(self._value.encode("utf-8"))
                return self._value

            def getTransferDataFlavors(self):  # noqa: N802 - UNO API name
                return self._flavors

            def isDataFlavorSupported(self, flavor):  # noqa: N802 - UNO API name
                mime = (getattr(flavor, "MimeType", "") or "").lower()
                return any(f.MimeType.lower() == mime for f in self._flavors)

        clipboard = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.datatransfer.clipboard.SystemClipboard", ctx
        )
        clipboard.setContents(_Text(text), None)
        return True
    except Exception:
        return False


def _transferable_for(text):
    """
    The transferable `copy_to_clipboard` would put on the clipboard.

    Exists so the smoke probe can assert both flavours round-trip. A real
    clipboard needs a display, which CI does not have -- and the bug this
    guards against was invisible from inside LibreOffice anyway.
    """
    holder = {}

    def capture(transferable, owner=None):
        holder["t"] = transferable

    class _FakeClipboard(object):
        setContents = staticmethod(capture)

    import types
    ctx = types.SimpleNamespace(
        ServiceManager=types.SimpleNamespace(
            createInstanceWithContext=lambda name, c: _FakeClipboard()))
    copy_to_clipboard(ctx, text)
    return holder.get("t")
