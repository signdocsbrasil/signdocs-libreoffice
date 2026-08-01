# SPDX-License-Identifier: MPL-2.0
"""
The recent-sends store is the only thing standing between a mis-sent document
and no way to cancel it, so its ordering, dedup and cap behaviour get real
coverage.

Ported from signdocs-onlyoffice's tests/history.test.js. Two assertions are
stronger here than in the JS original: the leak checks read the file actually
written to disk rather than a fake storage map, because on the desktop that
file is what gets backed up, synced and attached to support tickets.
"""

import json

import pytest

from signdocs import config
from signdocs.history import MAX, History
from signdocs.store import JsonStore


def entry(entry_id, **over):
    base = {
        "id": entry_id,
        "kind": "envelope",
        "filename": entry_id + ".pdf",
        "signers": [{"name": "Ana", "email": "ana@ex.com.br"}],
        "createdAt": "2026-07-30T00:00:00.000Z",
    }
    base.update(over)
    return base


@pytest.fixture
def history():
    return History(JsonStore(), "prod")


def test_starts_empty_and_records_a_send_as_pending(history):
    assert history.list() == []

    history.add(entry("env-1"))
    entries = history.list()
    assert len(entries) == 1
    assert entries[0]["id"] == "env-1"
    assert entries[0]["status"] == "pending"


def test_newest_send_comes_first(history):
    history.add(entry("env-1"))
    history.add(entry("env-2"))
    assert [e["id"] for e in history.list()] == ["env-2", "env-1"]


def test_re_adding_the_same_id_updates_in_place_instead_of_duplicating(history):
    # A retry that partially succeeded must not stack two rows for one send.
    history.add(entry("env-1", filename="first.pdf"))
    history.add(entry("env-1", filename="second.pdf"))
    entries = history.list()
    assert len(entries) == 1
    assert entries[0]["filename"] == "second.pdf"


def test_mark_cancelled_flips_status_and_drops_the_row_from_pending(history):
    history.add(entry("env-1"))
    history.add(entry("env-2"))

    history.mark_cancelled("env-1")
    found = [e for e in history.list() if e["id"] == "env-1"][0]
    assert found["status"] == "cancelled"
    assert [e["id"] for e in history.pending()] == ["env-2"]


def test_mark_cancelled_on_an_unknown_id_leaves_the_store_untouched(history):
    history.add(entry("env-1"))
    history.mark_cancelled("nope")
    assert len(history.list()) == 1
    assert history.list()[0]["status"] == "pending"


def test_remove_and_clear(history):
    history.add(entry("env-1"))
    history.add(entry("env-2"))
    history.remove("env-1")
    assert [e["id"] for e in history.list()] == ["env-2"]
    history.clear()
    assert history.list() == []


def test_store_is_capped_so_it_cannot_grow_without_bound(history):
    for i in range(MAX + 10):
        history.add(entry("env-%d" % i))
    entries = history.list()
    assert len(entries) == MAX
    # The cap drops the oldest, keeping the most recent send reachable.
    assert entries[0]["id"] == "env-%d" % (MAX + 9)


def test_records_carry_no_document_content_or_signing_links(tmp_path):
    path = tmp_path / "signdocs.json"
    history = History(JsonStore(str(path)), "prod")
    history.add(entry(
        "env-1",
        content="BASE64DOCUMENT",
        url="https://sign.example/x?cs=ss_secret_abc",
    ))

    raw = path.read_text(encoding="utf-8")
    assert "BASE64DOCUMENT" not in raw
    assert "ss_secret_" not in raw


def test_signer_records_keep_only_name_and_email(history):
    history.add(entry(
        "env-1",
        signers=[{"name": "Ana", "email": "a@b.com", "fiscalDigits": "52998224725"}],
    ))
    assert history.list()[0]["signers"] == [{"name": "Ana", "email": "a@b.com"}]


def test_stages_keep_separate_stores():
    # Switching to HML for a test must not surface prod sends, or a cancel
    # would be attempted against the wrong environment.
    store = JsonStore()
    prod = History(store, "prod")
    hml = History(store, "hml")

    prod.add(entry("env-prod"))
    hml.add(entry("env-hml"))

    assert [e["id"] for e in prod.list()] == ["env-prod"]
    assert [e["id"] for e in hml.list()] == ["env-hml"]


def test_corrupt_profile_degrades_to_empty_rather_than_throwing(tmp_path):
    path = tmp_path / "signdocs.json"
    path.write_text("{not json", encoding="utf-8")
    history = History(JsonStore(str(path)), "prod")
    assert history.list() == []


def test_unwritable_profile_degrades_rather_than_throwing():
    class Hostile(object):
        def get(self, key, default=None):
            raise IOError("blocked")

        def set(self, key, value):
            raise IOError("blocked")

        def delete(self, key):
            raise IOError("blocked")

    history = History(Hostile(), "prod")
    assert history.list() == []
    # Must not raise: a locked-down profile costs the user their history, not
    # their ability to send.
    history.add(entry("env-1"))


def test_wrong_shape_in_the_profile_is_ignored(tmp_path):
    # A hand-edited file could hold anything under our key.
    path = tmp_path / "signdocs.json"
    path.write_text(json.dumps({config.STORAGE["sends"] + "prod": "nonsense"}),
                    encoding="utf-8")
    history = History(JsonStore(str(path)), "prod")
    assert history.list() == []


def test_set_status_records_a_terminal_outcome(history):
    history.add(entry("env-1"))
    history.set_status("env-1", "completed")
    assert history.list()[0]["status"] == "completed"
    # A completed send is no longer cancellable, so it must leave pending().
    assert history.pending() == []


def test_set_status_on_an_unknown_id_is_a_no_op(history):
    # A send can be dropped from the capped store while a tracking dialog is
    # still open on it.
    history.add(entry("env-1"))
    history.set_status("gone", "completed")
    assert history.list()[0]["status"] == "pending"


def test_api_status_maps_to_a_local_status():
    from signdocs.history import FROM_API
    assert FROM_API["COMPLETED"] == "completed"
    assert FROM_API["CANCELLED"] == "cancelled"
    assert FROM_API["EXPIRED"] == "expired"
    assert FROM_API["FAILED"] == "failed"
    # ACTIVE is deliberately absent: it leaves the row pending.
    assert "ACTIVE" not in FROM_API


def test_transaction_id_is_kept_but_no_link_is(history):
    history.add(entry("ss-1", kind="session", transactionId="tx-9",
                      url="https://s/x?cs=ss_secret_zzz"))
    record = history.list()[0]
    # The transaction id is needed to fetch the signed PDF later; the signing
    # link is a bearer credential and must never be stored.
    assert record["transactionId"] == "tx-9"
    assert "url" not in record
