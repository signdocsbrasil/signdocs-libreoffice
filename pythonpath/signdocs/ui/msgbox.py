# SPDX-License-Identifier: MPL-2.0
"""Message boxes. Main thread only."""

TITLE = "SignDocs Brasil"


def _show(ctx, frame, box_type, text, title):
    from com.sun.star.awt.MessageBoxButtons import BUTTONS_OK

    toolkit = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", ctx
    )
    parent = frame.getContainerWindow() if frame else None
    box = toolkit.createMessageBox(parent, box_type, BUTTONS_OK, title, text)
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
