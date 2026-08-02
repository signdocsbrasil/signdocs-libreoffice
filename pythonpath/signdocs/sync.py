# SPDX-License-Identifier: MPL-2.0
"""
Bringing the local list of sends back in line with the server.

`history` records a send as `pending` and nothing ever moved it on except the
tracking dialog's poller, which only runs while that dialog is open on that
one row. So a send completed or cancelled elsewhere — in the web app, by the
signer, by expiry — stayed `pending` locally forever, and "recent sends" could
not answer the one question worth asking of it: what is still outstanding.

Kept out of `ui/` so it can be tested without an office, and out of `history`
so that module stays a pure store with no network in it.
"""

from signdocs import api, history
from signdocs.httpclient import HttpError


def refresh_pending(store, stage, status_fn=None):
    """
    Re-read every pending row from the server and write terminal outcomes back.

    Returns `(entries, checked, failed)` — the full list after the pass, how
    many rows got a definite answer, and how many could not be reached.

    `status_fn` is injectable so the whole thing is testable without a network.

    Two rules matter more than completeness:

      * **A row is only ever moved on evidence.** A network failure leaves it
        pending. Marking a send `failed` because the office is offline would
        be worse than showing nothing, since the row is what the user cancels
        from, and a terminal row stops offering that.
      * **One unreachable row must not abort the pass.** The rows are
        independent, and the common case for a stale list is exactly that some
        of it has aged out.
    """
    status_fn = status_fn or api.status_of
    log = history.History(store, stage)

    checked = 0
    failed = 0

    for entry in log.pending():
        ident = entry.get("id")
        kind = entry.get("kind")
        if not ident or not kind:
            continue

        try:
            state = status_fn(store, kind, ident, stage=stage) or {}
        except HttpError as exc:
            # The add-on tier turns an upstream 404 into a structured one
            # precisely so a channel can forget the row instead of seeing a
            # 500. Marked expired rather than deleted: a row vanishing with no
            # explanation reads as data loss, and in HML a 404 is routine
            # because those records carry a 7-day TTL.
            if exc.status == 404:
                log.set_status(ident, history.EXPIRED)
                checked += 1
            else:
                failed += 1
            continue
        except Exception:
            # Offline, DNS, TLS, a timeout. No evidence, so no change.
            failed += 1
            continue

        checked += 1
        local = history.FROM_API.get(state.get("status"))
        if local:
            log.set_status(ident, local)

    return log.list(), checked, failed


def pending_count(store, stage):
    """How many rows are outstanding, without touching the network."""
    return len(history.History(store, stage).pending())
