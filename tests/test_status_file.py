"""Tests for gcp/code/lib/status_file.py."""

from __future__ import annotations

import status_file  # type: ignore[import-not-found]


def test_status_uri_with_runtime_prefix() -> None:
    uri = status_file.status_uri("my-bucket", "team/runtime", "123")
    assert uri == "gs://my-bucket/team/runtime/triggers/status/123.json"


def test_status_uri_without_runtime_prefix() -> None:
    uri = status_file.status_uri("my-bucket", "", "123")
    assert uri == "gs://my-bucket/triggers/status/123.json"


def test_update_leg_progress_updates_current_leg(monkeypatch) -> None:
    state = {
        "legs": [
            {"index": 0, "files_completed": 0, "files_total": None},
            {"index": 1, "files_completed": 0, "files_total": None},
        ],
        "current_leg": {"index": 1, "files_completed": 0, "files_total": None},
    }
    writes: list[dict] = []
    monkeypatch.setattr(status_file, "read_status", lambda *_args, **_kwargs: state.copy())
    monkeypatch.setattr(
        status_file,
        "write_status",
        lambda _bucket, _runtime_prefix, _run_id, payload: writes.append(payload),
    )

    status_file.update_leg_progress("b", "runtime", "run-1", 1, 4, 8)

    assert writes
    written = writes[0]
    assert written["legs"][1]["files_completed"] == 4
    assert written["legs"][1]["files_total"] == 8
    assert written["current_leg"]["files_completed"] == 4
    assert written["current_leg"]["files_total"] == 8


def test_update_heartbeat_skips_terminal_run(monkeypatch) -> None:
    state = {
        "run_outcome": "completed",
        "last_heartbeat": "2026-03-02T00:00:00Z",
    }
    monkeypatch.setattr(status_file, "read_status", lambda *_args, **_kwargs: state.copy())
    monkeypatch.setattr(
        status_file,
        "write_status",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("write_status should not be called")),
    )

    status_file.update_heartbeat("b", "runtime", "run-1")


def test_update_leg_progress_skips_terminal_run(monkeypatch) -> None:
    state = {
        "run_outcome": "failed",
        "legs": [{"index": 0, "files_completed": 0, "files_total": None}],
        "current_leg": {"index": 0, "files_completed": 0, "files_total": None},
    }
    monkeypatch.setattr(status_file, "read_status", lambda *_args, **_kwargs: state.copy())
    monkeypatch.setattr(
        status_file,
        "write_status",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("write_status should not be called")),
    )

    status_file.update_leg_progress("b", "runtime", "run-1", 0, 1, 1)
