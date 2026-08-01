# SPDX-License-Identifier: MPL-2.0
"""
Getting work off the office's dispatch thread, and results back onto it.

LibreOffice's UI is single-threaded. An HTTP call made from `dispatch()` does
not freeze *our* dialog, it freezes the entire office — every open document,
every window. Exporting a large PDF and uploading it takes seconds, so this is
not a theoretical concern; it is the single most likely way for this extension
to be experienced as broken.

The rule is simple and absolute:

* anything that touches the network or the filesystem runs on a worker thread;
* **no UNO object may be touched from that thread** — results come back
  through `com.sun.star.awt.AsyncCallback`, which runs the callback on the
  main thread.

Modal dialogs run a nested event loop, so a callback posted while a "please
wait" dialog is executing is still delivered. That is what makes the busy
dialog work rather than deadlock.
"""

import threading
import traceback

import unohelper
from com.sun.star.awt import XCallback


class _MainThreadCall(unohelper.Base, XCallback):
    """Invoked by the office on the main thread."""

    def __init__(self, fn):
        self._fn = fn

    def notify(self, data):
        self._fn()


def on_main_thread(ctx, fn):
    """
    Schedule `fn` to run on the office's main thread.

    Keeps a reference to the callback object for the duration of the call:
    UNO holds only a weak reference, and a garbage-collected callback simply
    never fires.
    """
    service = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.AsyncCallback", ctx
    )
    holder = []

    def once():
        try:
            fn()
        finally:
            holder.clear()

    callback = _MainThreadCall(once)
    holder.append(callback)
    service.addCallback(callback, None)


class Result(object):
    """Outcome of a background call: either `value` or `error` is set."""

    def __init__(self, value=None, error=None, traceback_text=None):
        self.value = value
        self.error = error
        self.traceback_text = traceback_text

    @property
    def ok(self):
        return self.error is None


def run(ctx, work, done):
    """
    Run `work()` on a worker thread and hand a `Result` to `done` on the main
    thread.

    `done` is called exactly once, whether the work succeeded or raised. A
    background failure that never reports back would leave a busy dialog up
    forever, which is worse than the error itself.
    """
    def body():
        try:
            result = Result(value=work())
        except Exception as exc:
            result = Result(error=exc, traceback_text=traceback.format_exc())
        try:
            on_main_thread(ctx, lambda: done(result))
        except Exception:
            # The bridge is gone (office shutting down). Nothing left to
            # deliver to, and raising here would only kill a daemon thread.
            pass

    thread = threading.Thread(target=body, name="signdocs-work", daemon=True)
    thread.start()
    return thread
