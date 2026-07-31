# SPDX-License-Identifier: MPL-2.0
"""
Key/value store backing the extension's state.

The browser channels get `localStorage` for free. A desktop extension has to
bring its own, so this is one JSON file in the LibreOffice user profile with
localStorage-shaped semantics: string keys, whole-value get/set/delete.

Two deliberate choices:

* **Reads hit the file every time.** The file is a few kilobytes and the
  alternative — a module-level cache with no invalidation — is exactly the
  bug class that bit the secrets cache in external-api. Correctness over a
  saved syscall.
* **`get`/`set` raise on I/O trouble** instead of swallowing it. Callers decide
  whether losing state is fatal (it never is — history and settings are
  conveniences) and degrade individually, mirroring how the JS modules wrap
  every `localStorage` call in its own try/catch.

Writes are atomic (temp file + `os.replace`) and the file is created 0600: it
holds a refresh token.
"""

import json
import os

FILE_MODE = 0o600


class JsonStore(object):
    """
    Persisted store. `path=None` keeps everything in memory, which is what the
    tests use and what a read-only profile degrades to.
    """

    def __init__(self, path=None):
        self.path = path
        self._memory = {}

    # -- internals ---------------------------------------------------------
    def _read_all(self):
        if self.path is None:
            return dict(self._memory)
        if not os.path.exists(self.path):
            return {}
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        # A hand-edited file could hold anything; anything but an object is
        # not something we can merge into, so treat it as absent.
        return data if isinstance(data, dict) else {}

    def _write_all(self, data):
        if self.path is None:
            self._memory = dict(data)
            return
        directory = os.path.dirname(self.path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        tmp = self.path + ".tmp"
        # Created 0600 from the start rather than chmod'ed afterwards, so the
        # refresh token is never briefly world-readable.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- localStorage-shaped API ------------------------------------------
    def get(self, key, default=None):
        value = self._read_all().get(key, default)
        return value

    def set(self, key, value):
        data = self._read_all()
        data[key] = value
        self._write_all(data)

    def delete(self, key):
        data = self._read_all()
        if key in data:
            del data[key]
            self._write_all(data)
