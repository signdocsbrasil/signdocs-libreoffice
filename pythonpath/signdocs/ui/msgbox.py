# SPDX-License-Identifier: MPL-2.0
"""Message boxes. Main thread only."""

TITLE = "SignDocs Brasil"


def _show(ctx, frame, box_type, text, title, buttons=None):
    from com.sun.star.awt.MessageBoxButtons import BUTTONS_OK

    if buttons is None:
        buttons = BUTTONS_OK
    toolkit = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", ctx
    )
    parent = frame.getContainerWindow() if frame else None
    box = toolkit.createMessageBox(parent, box_type, buttons, title, text)
    try:
        return box.execute()
    finally:
        box.dispose()


def info(ctx, frame, text, title=TITLE):
    from com.sun.star.awt.MessageBoxType import INFOBOX

    return _show(ctx, frame, INFOBOX, text, title)


def error(ctx, frame, text, title=TITLE):
    from com.sun.star.awt.MessageBoxType import ERRORBOX

    return _show(ctx, frame, ERRORBOX, text, title)


def confirm(ctx, frame, text, title=TITLE):
    """
    A Yes/No question. True only on an explicit Yes.

    Everything else — No, the box dismissed with the window control, a result
    we do not recognise — reads as a refusal. A confirmation that defaults to
    yes when it cannot tell is not a confirmation.
    """
    from com.sun.star.awt.MessageBoxButtons import BUTTONS_YES_NO
    from com.sun.star.awt.MessageBoxResults import YES
    from com.sun.star.awt.MessageBoxType import QUERYBOX

    return _show(ctx, frame, QUERYBOX, text, title, BUTTONS_YES_NO) == YES
