# SPDX-License-Identifier: MPL-2.0
"""
Local record of what this installation has sent.

There is no server side here — unlike the Nextcloud app, which mirrors every
session in `oc_signdocs_sessions`, the only durable state available is the
user's own profile. So "recent sends" is per-profile, which is enough for the
case that actually matters: realising a moment later that you sent the wrong
document and needing to cancel it.

Records hold **no document content and no signing links** — just the ids needed
to cancel and enough labelling to tell two sends apart. That is a security
property, not a size optimisation: the profile is backed up, synced and
support-attached far more casually than a document is, and a `?cs=` link is a
bearer credential.
"""

from signdocs import config

#: Enough to cover "what did I just send", far short of unbounded growth.
MAX = 25

PENDING = "pending"
CANCELLED = "cancelled"


class History(object):
    def __init__(self, store, stage="prod"):
        self._store = store
        self._stage = stage

    def _key(self):
        return config.STORAGE["sends"] + self._stage

    # -- persistence -------------------------------------------------------
    def list(self):
        try:
            entries = self._store.get(self._key())
        except Exception:
            # Corrupt or unavailable storage must not take the dialog down.
            return []
        return list(entries) if isinstance(entries, list) else []

    def _write(self, entries):
        try:
            self._store.set(self._key(), entries[:MAX])
        except Exception:
            # Non-fatal: history is a convenience, not a source of truth.
            pass

    # -- operations --------------------------------------------------------
    def add(self, entry):
        """
        Record a send.

        Only the whitelisted fields are copied. Building the stored record by
        picking fields — rather than copying the caller's dict and deleting the
        dangerous ones — is what guarantees a future caller cannot leak a new
        field into the profile by accident.
        """
        entries = [e for e in self.list() if e.get("id") != entry.get("id")]
        entries.insert(0, {
            "id": entry.get("id"),
            "kind": entry.get("kind"),
            "filename": entry.get("filename"),
            "signers": [
                {"name": s.get("name"), "email": s.get("email")}
                for s in (entry.get("signers") or [])
            ],
            "createdAt": entry.get("createdAt"),
            "status": PENDING,
        })
        self._write(entries)
        return self.list()

    def mark_cancelled(self, entry_id):
        entries = self.list()
        for entry in entries:
            if entry.get("id") == entry_id:
                entry["status"] = CANCELLED
        self._write(entries)
        return self.list()

    def remove(self, entry_id):
        self._write([e for e in self.list() if e.get("id") != entry_id])
        return self.list()

    def clear(self):
        self._write([])
        return self.list()

    def pending(self):
        """Only pending rows can be cancelled; the rest are display-only."""
        return [e for e in self.list() if e.get("status") == PENDING]


def for_store(store):
    """History bound to whichever stage the store currently says."""
    return History(store, config.current_stage(store))
