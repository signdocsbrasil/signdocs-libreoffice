# SPDX-License-Identifier: MPL-2.0
"""
Reconciling the local send list with the server.

The dangerous failure here is not a crash, it is a row moved off `pending` on
no evidence. A terminal row stops offering to cancel, so wrongly retiring one
takes away the user's only route to stop a signature they did not mean to
request — from inside the extension, at least.
"""

import pytest

from signdocs import history, sync
from signdocs.httpclient import HttpError, NetworkError
from signdocs.store import JsonStore

STAGE = "hml"


@pytest.fixture
def store():
    return JsonStore()


@pytest.fixture
def log(store):
    log = history.History(store, STAGE)
    log.add({"id": "ss_1", "kind": "session", "filename": "a.pdf"})
    log.add({"id": "env_2", "kind": "envelope", "filename": "b.pdf"})
    return log


def status(value):
    return lambda store_, kind, ident, stage=None: {"status": value}


def test_new_rows_start_pending(log):
    assert len(log.pending()) == 2


# ------------------------------------------------------------- resolution
def test_completed_rows_are_retired(store, log):
    entries, checked, failed = sync.refresh_pending(
        store, STAGE, status_fn=status("COMPLETED"))
    assert (checked, failed) == (2, 0)
    assert [e["status"] for e in entries] == [history.COMPLETED] * 2
    assert log.pending() == []


@pytest.mark.parametrize("api_status,expected", [
    ("COMPLETED", history.COMPLETED),
    ("CANCELLED", history.CANCELLED),
    ("EXPIRED", history.EXPIRED),
    ("FAILED", history.FAILED),
])
def test_every_terminal_status_maps(store, log, api_status, expected):
    entries, _, _ = sync.refresh_pending(
        store, STAGE, status_fn=status(api_status))
    assert all(e["status"] == expected for e in entries)


def test_active_rows_stay_pending(store, log):
    entries, checked, failed = sync.refresh_pending(
        store, STAGE, status_fn=status("ACTIVE"))
    assert (checked, failed) == (2, 0)
    assert len(log.pending()) == 2


def test_unknown_status_leaves_the_row_alone(store, log):
    # A status the API grows later must not be guessed at.
    sync.refresh_pending(store, STAGE, status_fn=status("SOMETHING_NEW"))
    assert len(log.pending()) == 2


# ----------------------------------------------------------- no evidence
def test_network_failure_never_retires_a_row(store, log):
    def offline(*a, **k):
        raise NetworkError("no route to host")

    entries, checked, failed = sync.refresh_pending(store, STAGE,
                                                    status_fn=offline)
    assert (checked, failed) == (0, 2)
    # Still cancellable. This is the whole point.
    assert len(log.pending()) == 2
    assert all(e["status"] == history.PENDING for e in entries)


def test_server_error_never_retires_a_row(store, log):
    def boom(*a, **k):
        raise HttpError(500, "upstream exploded")

    _, checked, failed = sync.refresh_pending(store, STAGE, status_fn=boom)
    assert (checked, failed) == (0, 2)
    assert len(log.pending()) == 2


def test_404_marks_expired_rather_than_deleting(store, log):
    """
    The add-on tier translates an upstream 404 into a structured one so a
    channel can forget the row. Expired, not removed: a row vanishing with no
    explanation reads as data loss, and in HML a 404 is routine because those
    records carry a 7-day TTL.
    """
    def gone(*a, **k):
        raise HttpError(404, "Signing session not found")

    entries, checked, failed = sync.refresh_pending(store, STAGE,
                                                    status_fn=gone)
    assert (checked, failed) == (2, 0)
    assert [e["status"] for e in entries] == [history.EXPIRED] * 2
    assert len(entries) == 2  # nothing silently dropped


def test_one_bad_row_does_not_abort_the_others(store, log):
    def mixed(store_, kind, ident, stage=None):
        if ident == "ss_1":
            raise NetworkError("flaky")
        return {"status": "COMPLETED"}

    entries, checked, failed = sync.refresh_pending(store, STAGE,
                                                    status_fn=mixed)
    assert (checked, failed) == (1, 1)
    by_id = {e["id"]: e["status"] for e in entries}
    assert by_id["ss_1"] == history.PENDING
    assert by_id["env_2"] == history.COMPLETED


# ------------------------------------------------------------------ scope
def test_only_pending_rows_are_queried(store, log):
    log.set_status("ss_1", history.COMPLETED)
    asked = []

    def record(store_, kind, ident, stage=None):
        asked.append(ident)
        return {"status": "ACTIVE"}

    sync.refresh_pending(store, STAGE, status_fn=record)
    assert asked == ["env_2"]


def test_no_pending_rows_makes_no_calls(store, log):
    log.set_status("ss_1", history.COMPLETED)
    log.set_status("env_2", history.CANCELLED)

    def explode(*a, **k):
        raise AssertionError("should not have been called")

    _, checked, failed = sync.refresh_pending(store, STAGE, status_fn=explode)
    assert (checked, failed) == (0, 0)


def test_rows_missing_an_id_or_kind_are_skipped_not_fatal(store):
    log = history.History(store, STAGE)
    log.add({"id": "", "kind": "session", "filename": "junk.pdf"})
    log.add({"id": "ss_ok", "kind": "session", "filename": "ok.pdf"})

    _, checked, failed = sync.refresh_pending(
        store, STAGE, status_fn=status("COMPLETED"))
    assert (checked, failed) == (1, 0)


def test_the_kind_is_passed_through_so_envelopes_hit_the_right_route(store, log):
    seen = []

    def record(store_, kind, ident, stage=None):
        seen.append((kind, stage))
        return {"status": "ACTIVE"}

    sync.refresh_pending(store, STAGE, status_fn=record)
    assert sorted(k for k, _ in seen) == ["envelope", "session"]
    assert {stage for _, stage in seen} == {STAGE}


def test_pending_count_touches_no_network(store, log):
    assert sync.pending_count(store, STAGE) == 2
    history.History(store, STAGE).set_status("ss_1", history.COMPLETED)
    assert sync.pending_count(store, STAGE) == 1


def test_stages_do_not_leak_into_each_other(store, log):
    # Sends are namespaced per stage; a refresh in HML must not touch prod.
    assert sync.pending_count(store, "prod") == 0
    sync.refresh_pending(store, STAGE, status_fn=status("COMPLETED"))
    assert sync.pending_count(store, "prod") == 0
