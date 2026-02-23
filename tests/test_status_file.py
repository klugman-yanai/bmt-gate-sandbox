"""Tests for remote/code/lib/status_file.py."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "remote" / "code" / "lib") not in sys.path:
    sys.path.insert(0, str(_ROOT / "remote" / "code" / "lib"))

import status_file  # type: ignore[import-not-found]  # noqa: E402


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
