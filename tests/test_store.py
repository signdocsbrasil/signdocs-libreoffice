# SPDX-License-Identifier: MPL-2.0
"""
The store holds a refresh token, so its file permissions and write atomicity
are security properties, not implementation details.
"""

import json
import os
import stat

import pytest

from signdocs.store import JsonStore


def test_memory_store_round_trips():
    store = JsonStore()
    assert store.get("k") is None
    store.set("k", {"a": 1})
    assert store.get("k") == {"a": 1}
    store.delete("k")
    assert store.get("k") is None


def test_file_store_round_trips(tmp_path):
    path = tmp_path / "signdocs.json"
    store = JsonStore(str(path))
    store.set("k", ["a", "b"])
    assert json.loads(path.read_text(encoding="utf-8"))["k"] == ["a", "b"]
    # A fresh instance reads what the first one wrote.
    assert JsonStore(str(path)).get("k") == ["a", "b"]


def test_file_is_created_private(tmp_path):
    path = tmp_path / "signdocs.json"
    JsonStore(str(path)).set("refresh_token", "secret")
    mode = stat.S_IMODE(os.stat(str(path)).st_mode)
    # 0600 from creation, never chmod'ed afterwards — otherwise the token is
    # briefly world-readable on a shared machine.
    assert mode == 0o600


def test_missing_file_reads_as_empty(tmp_path):
    assert JsonStore(str(tmp_path / "absent.json")).get("k") is None


def test_corrupt_file_raises_for_the_caller_to_handle(tmp_path):
    # The store does not swallow: callers decide whether losing this
    # particular value is survivable. History and settings both say yes.
    path = tmp_path / "signdocs.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        JsonStore(str(path)).get("k")


def test_non_object_json_is_treated_as_absent(tmp_path):
    path = tmp_path / "signdocs.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert JsonStore(str(path)).get("k") is None


def test_keys_do_not_clobber_each_other(tmp_path):
    path = tmp_path / "signdocs.json"
    store = JsonStore(str(path))
    store.set("a", 1)
    store.set("b", 2)
    store.delete("a")
    assert store.get("a") is None
    assert store.get("b") == 2


def test_failed_write_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "signdocs.json"
    store = JsonStore(str(path))
    store.set("ok", 1)
    with pytest.raises(TypeError):
        store.set("bad", {1, 2, 3})  # a set is not JSON-serialisable
    assert not os.path.exists(str(path) + ".tmp")
    # The previous good content survived; a failed write must not truncate.
    assert store.get("ok") == 1


def test_parent_directory_is_created(tmp_path):
    path = tmp_path / "nested" / "signdocs.json"
    JsonStore(str(path)).set("k", "v")
    assert JsonStore(str(path)).get("k") == "v"
