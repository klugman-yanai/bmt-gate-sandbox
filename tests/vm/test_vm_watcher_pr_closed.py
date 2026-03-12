"""PR closure behavior tests for vm_watcher._process_run_trigger."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import gcp.code.vm_watcher as watcher  # type: ignore[import-not-found]


class _StatusStore:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None
        self.writes: list[dict[str, Any]] = []

    def write(self, _bucket: str, _runtime_prefix: str, _run_id: str, payload: dict[str, Any]) -> None:
        cloned = json.loads(json.dumps(payload))
        self.payload = cloned
        self.writes.append(cloned)

    def read(self, _bucket: str, _runtime_prefix: str, _run_id: str) -> dict[str, Any] | None:
        if self.payload is None:
            return None
        return json.loads(json.dumps(self.payload))


def _run_payload(*, run_context: str = "pr", include_pr: bool = True, leg_count: int = 2) -> dict[str, Any]:
    legs = [{"project": "sk", "bmt_id": f"bmt_{idx}", "run_id": f"run-{idx}"} for idx in range(leg_count)]
    payload: dict[str, Any] = {
        "workflow_run_id": "123",
        "repository": "owner/repo",
        "sha": "abc123",
        "run_context": run_context,
        "bucket": "bucket-a",
        "status_context": "BMT Gate",
        "description_pending": "BMT running on VM; status will update when complete.",
        "legs": legs,
    }
    if include_pr:
        payload["pull_request_number"] = 99
    return payload


def _accepted_requested_legs(legs_raw: list[Any]) -> list[dict[str, Any]]:
    """Return requested_legs with all legs accepted (for tests that mock GCS resolution)."""
    result: list[dict[str, Any]] = []
    for idx, leg in enumerate(legs_raw):
        if not isinstance(leg, dict):
            continue
        result.append(
            {
                "index": idx,
                "project": str(leg.get("project", "?")),
                "bmt_id": str(leg.get("bmt_id", "?")),
                "run_id": str(leg.get("run_id", f"run-{idx}")),
                "decision": "accepted",
                "reason": None,
            }
        )
    return result


def test_closed_before_pickup_skips_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    status_store = _StatusStore()
    handshake_payload: dict[str, Any] = {}
    post_status_calls: list[str] = []
    removed: list[tuple[str, bool]] = []

    run_trigger_uri = "gs://bucket-a/runtime/triggers/runs/123.json"

    monkeypatch.setattr(watcher, "_gcloud_download_json", lambda _uri: _run_payload())

    def _capture_ack(_uri: str, payload: dict[str, Any]) -> bool:
        handshake_payload.clear()
        handshake_payload.update(payload)
        return True

    monkeypatch.setattr(watcher, "_gcloud_upload_json", _capture_ack)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda uri, recursive=False: removed.append((uri, recursive)) or True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        watcher.github_pull_request,
        "get_pr_state",
        lambda *_args, **_kwargs: {
            "state": "closed",
            "merged": False,
            "checked_at": "2026-02-26T00:00:00Z",
            "error": None,
        },
    )
    monkeypatch.setattr(watcher, "_post_commit_status", lambda *_args, **_kwargs: post_status_calls.append("x") or True)
    monkeypatch.setattr(
        watcher.github_checks,
        "create_check_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected check run")),
    )
    monkeypatch.setattr(
        watcher,
        "_download_orchestrator",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected orchestrator download")),
    )
    monkeypatch.setattr(watcher.status_file, "write_status", status_store.write)
    monkeypatch.setattr(watcher.status_file, "read_status", status_store.read)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)

    watcher._process_run_trigger(
        run_trigger_uri,
        "gs://bucket-a/code",
        "gs://bucket-a/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert handshake_payload["run_disposition"] == "skipped"
    assert handshake_payload["skip_reason"] == "pr_closed_before_pickup"
    assert handshake_payload["accepted_leg_count"] == 0
    assert handshake_payload["accepted_legs"] == []
    assert len(handshake_payload["rejected_legs"]) == 2
    assert status_store.payload is not None
    assert status_store.payload["vm_state"] == "skipped_pr_closed_before_pickup"
    assert status_store.payload["run_outcome"] == "skipped"
    assert all(leg.get("status") == "skipped" for leg in status_store.payload["legs"])
    assert post_status_calls == []
    assert removed
    assert removed[0][0] == run_trigger_uri


def test_superseded_before_pickup_skips_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    status_store = _StatusStore()
    handshake_payload: dict[str, Any] = {}
    post_status_calls: list[str] = []
    removed: list[tuple[str, bool]] = []

    run_trigger_uri = "gs://bucket-a/runtime/triggers/runs/123.json"

    monkeypatch.setattr(watcher, "_gcloud_download_json", lambda _uri: _run_payload())

    def _capture_ack(_uri: str, payload: dict[str, Any]) -> bool:
        handshake_payload.clear()
        handshake_payload.update(payload)
        return True

    monkeypatch.setattr(watcher, "_gcloud_upload_json", _capture_ack)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda uri, recursive=False: removed.append((uri, recursive)) or True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        watcher.github_pull_request,
        "get_pr_state",
        lambda *_args, **_kwargs: {
            "state": "open",
            "merged": False,
            "head_sha": "newhead999999",
            "checked_at": "2026-02-26T00:00:00Z",
            "error": None,
        },
    )
    monkeypatch.setattr(watcher, "_post_commit_status", lambda *_args, **_kwargs: post_status_calls.append("x") or True)
    monkeypatch.setattr(
        watcher.github_checks,
        "create_check_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected check run")),
    )
    monkeypatch.setattr(
        watcher,
        "_download_orchestrator",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected orchestrator download")),
    )
    monkeypatch.setattr(watcher.status_file, "write_status", status_store.write)
    monkeypatch.setattr(watcher.status_file, "read_status", status_store.read)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)

    watcher._process_run_trigger(
        run_trigger_uri,
        "gs://bucket-a/code",
        "gs://bucket-a/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert handshake_payload["run_disposition"] == "skipped"
    assert handshake_payload["skip_reason"] == "superseded_by_new_commit"
    assert handshake_payload["superseded_by_sha"] == "newhead999999"
    assert handshake_payload["accepted_leg_count"] == 0
    assert len(handshake_payload["rejected_legs"]) == 2
    assert status_store.payload is not None
    assert status_store.payload["run_outcome"] == "skipped"
    assert status_store.payload["cancel_reason"] == "superseded_by_new_commit"
    assert status_store.payload["superseded_by_sha"] == "newhead999999"
    assert all(leg.get("status") == "skipped" for leg in status_store.payload["legs"])
    assert post_status_calls == []
    assert removed
    assert removed[0][0] == run_trigger_uri


def test_closed_mid_run_cancels_remaining_and_no_pointer_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status_store = _StatusStore()
    run_trigger_uri = "gs://bucket-a/runtime/triggers/runs/123.json"
    orchestrator_runs: list[dict[str, Any]] = []
    update_pointer_calls: list[dict[str, Any]] = []
    check_updates: list[dict[str, Any]] = []
    post_status_states: list[str] = []
    pr_comment_calls: list[int] = []

    pr_states = iter(
        [
            {"state": "open", "merged": False, "checked_at": "2026-02-26T00:00:00Z", "error": None},
            {"state": "open", "merged": False, "checked_at": "2026-02-26T00:00:05Z", "error": None},
            {"state": "closed", "merged": False, "checked_at": "2026-02-26T00:00:10Z", "error": None},
        ]
    )

    monkeypatch.setattr(watcher, "_gcloud_download_json", lambda _uri: _run_payload())
    monkeypatch.setattr(
        watcher,
        "_resolve_requested_legs",
        lambda *, legs_raw, code_bucket_root: _accepted_requested_legs(legs_raw),
    )
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda _uri, _payload: True)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_download_orchestrator", lambda *_args, **_kwargs: tmp_path / "orchestrator.py")
    monkeypatch.setattr(
        watcher, "_run_orchestrator", lambda _path, trigger, _workspace: orchestrator_runs.append(trigger) or 0
    )
    monkeypatch.setattr(watcher, "_latest_run_root", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        watcher,
        "_load_manager_summary",
        lambda _run_root: {
            "status": "pass",
            "project_id": "sk",
            "bmt_id": "bmt_0",
            "run_id": "run-0",
            "passed": True,
            "ci_verdict_uri": "gs://bucket-a/runtime/sk/results/false_rejects/snapshots/run-0/ci_verdict.json",
            "bmt_results": {"results": []},
            "orchestration_timing": {"duration_sec": 1},
        },
    )
    monkeypatch.setattr(
        watcher, "_update_pointer_and_cleanup", lambda _root, summary: update_pointer_calls.append(summary)
    )
    monkeypatch.setattr(watcher.status_file, "write_status", status_store.write)
    monkeypatch.setattr(watcher.status_file, "read_status", status_store.read)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.github_checks, "create_check_run", lambda *_args, **_kwargs: 88)
    monkeypatch.setattr(
        watcher.github_checks,
        "update_check_run",
        lambda *_args, **kwargs: check_updates.append(kwargs),
    )
    monkeypatch.setattr(
        watcher.github_pull_request,
        "get_pr_state",
        lambda *_args, **_kwargs: next(pr_states),
    )
    monkeypatch.setattr(
        watcher,
        "_post_commit_status",
        lambda _repo, _sha, state, *_args, **_kwargs: post_status_states.append(state) or True,
    )
    monkeypatch.setattr(
        watcher.github_pr_comment,
        "upsert_pr_comment_by_marker",
        lambda _token, _repo, issue, _marker, _body: pr_comment_calls.append(issue) or True,
    )

    watcher._process_run_trigger(
        run_trigger_uri,
        "gs://bucket-a/code",
        "gs://bucket-a/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert len(orchestrator_runs) == 1
    assert status_store.payload is not None
    assert status_store.payload["run_outcome"] == "cancelled"
    assert status_store.payload["cancel_reason"] == "pr_closed_during_run"
    assert status_store.payload["legs"][1]["status"] == "skipped"
    assert status_store.payload["legs"][1]["skip_reason"] == "pr_closed_during_run"
    assert update_pointer_calls == []
    assert any(call.get("conclusion") == "neutral" for call in check_updates)
    assert "error" in post_status_states
    assert pr_comment_calls == []


def test_superseded_mid_run_cancels_between_legs_and_upserts_commit_comment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status_store = _StatusStore()
    run_trigger_uri = "gs://bucket-a/runtime/triggers/runs/123.json"
    orchestrator_runs: list[dict[str, Any]] = []
    update_pointer_calls: list[dict[str, Any]] = []
    check_updates: list[dict[str, Any]] = []
    post_status_states: list[str] = []
    pr_comment_calls: list[tuple[int, str, str]] = []

    pr_states = iter(
        [
            {
                "state": "open",
                "merged": False,
                "head_sha": "abc123",
                "checked_at": "2026-02-26T00:00:00Z",
                "error": None,
            },
            {
                "state": "open",
                "merged": False,
                "head_sha": "abc123",
                "checked_at": "2026-02-26T00:00:05Z",
                "error": None,
            },
            {
                "state": "open",
                "merged": False,
                "head_sha": "def789",
                "checked_at": "2026-02-26T00:00:10Z",
                "error": None,
            },
        ]
    )

    monkeypatch.setattr(watcher, "_gcloud_download_json", lambda _uri: _run_payload())
    monkeypatch.setattr(
        watcher,
        "_resolve_requested_legs",
        lambda *, legs_raw, code_bucket_root: _accepted_requested_legs(legs_raw),
    )
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda _uri, _payload: True)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_download_orchestrator", lambda *_args, **_kwargs: tmp_path / "orchestrator.py")
    monkeypatch.setattr(
        watcher, "_run_orchestrator", lambda _path, trigger, _workspace: orchestrator_runs.append(trigger) or 0
    )
    monkeypatch.setattr(watcher, "_latest_run_root", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        watcher,
        "_load_manager_summary",
        lambda _run_root: {
            "status": "pass",
            "project_id": "sk",
            "bmt_id": "bmt_0",
            "run_id": "run-0",
            "passed": True,
            "ci_verdict_uri": "gs://bucket-a/runtime/sk/results/false_rejects/snapshots/run-0/ci_verdict.json",
            "bmt_results": {"results": []},
            "orchestration_timing": {"duration_sec": 1},
        },
    )
    monkeypatch.setattr(
        watcher, "_update_pointer_and_cleanup", lambda _root, summary: update_pointer_calls.append(summary)
    )
    monkeypatch.setattr(watcher.status_file, "write_status", status_store.write)
    monkeypatch.setattr(watcher.status_file, "read_status", status_store.read)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.github_checks, "create_check_run", lambda *_args, **_kwargs: 88)
    monkeypatch.setattr(
        watcher.github_checks, "update_check_run", lambda *_args, **kwargs: check_updates.append(kwargs)
    )
    monkeypatch.setattr(watcher.github_pull_request, "get_pr_state", lambda *_args, **_kwargs: next(pr_states))
    monkeypatch.setattr(
        watcher,
        "_post_commit_status",
        lambda _repo, _sha, state, *_args, **_kwargs: post_status_states.append(state) or True,
    )
    monkeypatch.setattr(
        watcher.github_pr_comment,
        "upsert_pr_comment_by_marker",
        lambda _token, _repo, issue, marker, body: pr_comment_calls.append((issue, marker, body)) or True,
    )

    watcher._process_run_trigger(
        run_trigger_uri,
        "gs://bucket-a/code",
        "gs://bucket-a/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert len(orchestrator_runs) == 1
    assert status_store.payload is not None
    assert status_store.payload["run_outcome"] == "cancelled"
    assert status_store.payload["cancel_reason"] == "superseded_by_new_commit"
    assert status_store.payload["superseded_by_sha"] == "def789"
    assert status_store.payload["legs"][1]["status"] == "skipped"
    assert status_store.payload["legs"][1]["skip_reason"] == "superseded_by_new_commit"
    assert update_pointer_calls == []
    assert any(call.get("conclusion") == "neutral" for call in check_updates)
    assert "error" in post_status_states
    assert len(pr_comment_calls) == 1
    _, marker, body = pr_comment_calls[0]
    assert "bmt-vm-comment-sha:abc123" in marker
    assert "BMT superseded" in body
    assert "Superseded by" in body
    assert "/commit/abc123" in body
    assert "/commit/def789" in body


def test_closed_mid_run_posts_terminal_error_when_first_status_post_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_store = _StatusStore()
    post_status_states: list[str] = []

    pr_states = iter(
        [
            {"state": "open", "merged": False, "checked_at": "2026-02-26T00:00:00Z", "error": None},
            {"state": "open", "merged": False, "checked_at": "2026-02-26T00:00:05Z", "error": None},
            {"state": "closed", "merged": False, "checked_at": "2026-02-26T00:00:10Z", "error": None},
        ]
    )

    monkeypatch.setattr(watcher, "_gcloud_download_json", lambda _uri: _run_payload())
    monkeypatch.setattr(
        watcher,
        "_resolve_requested_legs",
        lambda *, legs_raw, code_bucket_root: _accepted_requested_legs(legs_raw),
    )
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda _uri, _payload: True)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_download_orchestrator", lambda *_args, **_kwargs: tmp_path / "orchestrator.py")
    monkeypatch.setattr(watcher, "_run_orchestrator", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(watcher, "_latest_run_root", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        watcher,
        "_load_manager_summary",
        lambda _run_root: {
            "status": "pass",
            "project_id": "sk",
            "bmt_id": "bmt_0",
            "run_id": "run-0",
            "passed": True,
            "ci_verdict_uri": "gs://bucket-a/runtime/sk/results/false_rejects/snapshots/run-0/ci_verdict.json",
            "bmt_results": {"results": []},
            "orchestration_timing": {"duration_sec": 1},
        },
    )
    monkeypatch.setattr(watcher, "_update_pointer_and_cleanup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.status_file, "write_status", status_store.write)
    monkeypatch.setattr(watcher.status_file, "read_status", status_store.read)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.github_checks, "create_check_run", lambda *_args, **_kwargs: 88)
    monkeypatch.setattr(watcher.github_checks, "update_check_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.github_pull_request, "get_pr_state", lambda *_args, **_kwargs: next(pr_states))

    error_post_attempts = {"count": 0}

    def _post_status(_repo: str, _sha: str, state: str, *_args: Any, **_kwargs: Any) -> bool:
        post_status_states.append(state)
        if state == "error":
            error_post_attempts["count"] += 1
            return error_post_attempts["count"] > 1
        return True

    monkeypatch.setattr(watcher, "_post_commit_status", _post_status)
    monkeypatch.setattr(watcher.github_pr_comment, "upsert_pr_comment_by_marker", lambda *_args, **_kwargs: True)

    watcher._process_run_trigger(
        "gs://bucket-a/runtime/triggers/runs/123.json",
        "gs://bucket-a/code",
        "gs://bucket-a/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert status_store.payload is not None
    assert status_store.payload["run_outcome"] == "cancelled"
    assert error_post_attempts["count"] >= 2
    assert "error" in post_status_states


def test_final_check_run_is_created_at_completion_if_startup_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_store = _StatusStore()
    create_calls: list[int] = []
    update_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        watcher, "_gcloud_download_json", lambda _uri: _run_payload(run_context="dev", include_pr=False, leg_count=1)
    )
    monkeypatch.setattr(
        watcher,
        "_resolve_requested_legs",
        lambda *, legs_raw, code_bucket_root: _accepted_requested_legs(legs_raw),
    )
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda _uri, _payload: True)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_download_orchestrator", lambda *_args, **_kwargs: tmp_path / "orchestrator.py")
    monkeypatch.setattr(watcher, "_run_orchestrator", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(watcher, "_latest_run_root", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        watcher,
        "_load_manager_summary",
        lambda _run_root: {
            "status": "pass",
            "project_id": "sk",
            "bmt_id": "bmt_0",
            "run_id": "run-0",
            "passed": True,
            "ci_verdict_uri": "gs://bucket-a/runtime/sk/results/false_rejects/snapshots/run-0/ci_verdict.json",
            "bmt_results": {"results": []},
            "orchestration_timing": {"duration_sec": 1},
        },
    )
    monkeypatch.setattr(watcher, "_update_pointer_and_cleanup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.status_file, "write_status", status_store.write)
    monkeypatch.setattr(watcher.status_file, "read_status", status_store.read)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)

    def _create_check_run(*_args: Any, **_kwargs: Any) -> int:
        create_calls.append(1)
        if len(create_calls) <= 3:
            raise RuntimeError("simulated create failure")
        return 321

    monkeypatch.setattr(watcher.github_checks, "create_check_run", _create_check_run)
    monkeypatch.setattr(
        watcher.github_checks,
        "update_check_run",
        lambda _token, _repo, _check_run_id, **kwargs: update_calls.append(kwargs),
    )
    monkeypatch.setattr(watcher, "_post_commit_status", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        watcher.github_pull_request,
        "get_pr_state",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected PR state check")),
    )
    monkeypatch.setattr(watcher.github_pr_comment, "upsert_pr_comment_by_marker", lambda *_args, **_kwargs: True)

    watcher._process_run_trigger(
        "gs://bucket-a/runtime/triggers/runs/123.json",
        "gs://bucket-a/code",
        "gs://bucket-a/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert status_store.payload is not None
    assert status_store.payload["run_outcome"] == "completed"
    assert len(create_calls) >= 4
    assert any(call.get("status") == "completed" and call.get("conclusion") == "success" for call in update_calls)


def test_pr_state_api_failure_fails_open_and_completes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_store = _StatusStore()
    orchestrator_runs: list[dict[str, Any]] = []
    update_pointer_calls: list[dict[str, Any]] = []
    post_status_states: list[str] = []

    monkeypatch.setattr(watcher, "_gcloud_download_json", lambda _uri: _run_payload())
    monkeypatch.setattr(
        watcher,
        "_resolve_requested_legs",
        lambda *, legs_raw, code_bucket_root: _accepted_requested_legs(legs_raw),
    )
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda _uri, _payload: True)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_download_orchestrator", lambda *_args, **_kwargs: tmp_path / "orchestrator.py")
    monkeypatch.setattr(
        watcher, "_run_orchestrator", lambda _path, trigger, _workspace: orchestrator_runs.append(trigger) or 0
    )
    monkeypatch.setattr(watcher, "_latest_run_root", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        watcher,
        "_load_manager_summary",
        lambda _run_root: {
            "status": "pass",
            "project_id": "sk",
            "bmt_id": "bmt_x",
            "run_id": "run-x",
            "passed": True,
            "ci_verdict_uri": "gs://bucket-a/runtime/sk/results/false_rejects/snapshots/run-x/ci_verdict.json",
            "bmt_results": {"results": []},
            "orchestration_timing": {"duration_sec": 1},
        },
    )
    monkeypatch.setattr(
        watcher, "_update_pointer_and_cleanup", lambda _root, summary: update_pointer_calls.append(summary)
    )
    monkeypatch.setattr(watcher.status_file, "write_status", status_store.write)
    monkeypatch.setattr(watcher.status_file, "read_status", status_store.read)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.github_checks, "create_check_run", lambda *_args, **_kwargs: 42)
    monkeypatch.setattr(watcher.github_checks, "update_check_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        watcher.github_pull_request,
        "get_pr_state",
        lambda *_args, **_kwargs: {
            "state": "unknown",
            "merged": None,
            "checked_at": "2026-02-26T00:00:00Z",
            "error": "network_error",
        },
    )
    monkeypatch.setattr(
        watcher,
        "_post_commit_status",
        lambda _repo, _sha, state, *_args, **_kwargs: post_status_states.append(state) or True,
    )
    monkeypatch.setattr(watcher.github_pr_comment, "upsert_pr_comment_by_marker", lambda *_args, **_kwargs: True)

    watcher._process_run_trigger(
        "gs://bucket-a/runtime/triggers/runs/123.json",
        "gs://bucket-a/code",
        "gs://bucket-a/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert len(orchestrator_runs) == 2
    assert status_store.payload is not None
    assert status_store.payload["run_outcome"] == "completed"
    assert len(update_pointer_calls) == 2
    assert "success" in post_status_states


def test_non_pr_run_does_not_check_pr_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    status_store = _StatusStore()
    orchestrator_runs: list[dict[str, Any]] = []
    update_pointer_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        watcher, "_gcloud_download_json", lambda _uri: _run_payload(run_context="dev", include_pr=False, leg_count=1)
    )
    monkeypatch.setattr(
        watcher,
        "_resolve_requested_legs",
        lambda *, legs_raw, code_bucket_root: _accepted_requested_legs(legs_raw),
    )
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda _uri, _payload: True)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_download_orchestrator", lambda *_args, **_kwargs: tmp_path / "orchestrator.py")
    monkeypatch.setattr(
        watcher, "_run_orchestrator", lambda _path, trigger, _workspace: orchestrator_runs.append(trigger) or 0
    )
    monkeypatch.setattr(watcher, "_latest_run_root", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        watcher,
        "_load_manager_summary",
        lambda _run_root: {
            "status": "pass",
            "project_id": "sk",
            "bmt_id": "bmt_0",
            "run_id": "run-0",
            "passed": True,
            "ci_verdict_uri": "gs://bucket-a/runtime/sk/results/false_rejects/snapshots/run-0/ci_verdict.json",
            "bmt_results": {"results": []},
            "orchestration_timing": {"duration_sec": 1},
        },
    )
    monkeypatch.setattr(
        watcher, "_update_pointer_and_cleanup", lambda _root, summary: update_pointer_calls.append(summary)
    )
    monkeypatch.setattr(watcher.status_file, "write_status", status_store.write)
    monkeypatch.setattr(watcher.status_file, "read_status", status_store.read)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.github_checks, "create_check_run", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(watcher.github_checks, "update_check_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        watcher.github_pull_request,
        "get_pr_state",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected PR state check")),
    )
    monkeypatch.setattr(watcher, "_post_commit_status", lambda *_args, **_kwargs: True)

    watcher._process_run_trigger(
        "gs://bucket-a/runtime/triggers/runs/123.json",
        "gs://bucket-a/code",
        "gs://bucket-a/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert len(orchestrator_runs) == 1
    assert len(update_pointer_calls) == 1
    assert status_store.payload is not None
    assert status_store.payload["run_outcome"] == "completed"


def test_completed_status_wins_against_late_heartbeat_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    status_store = _StatusStore()

    monkeypatch.setattr(
        watcher, "_gcloud_download_json", lambda _uri: _run_payload(run_context="dev", include_pr=False, leg_count=1)
    )
    monkeypatch.setattr(
        watcher,
        "_resolve_requested_legs",
        lambda *, legs_raw, code_bucket_root: _accepted_requested_legs(legs_raw),
    )
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda _uri, _payload: True)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_download_orchestrator", lambda *_args, **_kwargs: tmp_path / "orchestrator.py")
    monkeypatch.setattr(watcher, "_run_orchestrator", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(watcher, "_latest_run_root", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        watcher,
        "_load_manager_summary",
        lambda _run_root: {
            "status": "pass",
            "project_id": "sk",
            "bmt_id": "bmt_0",
            "run_id": "run-0",
            "passed": True,
            "ci_verdict_uri": "gs://bucket-a/runtime/sk/results/false_rejects/snapshots/run-0/ci_verdict.json",
            "bmt_results": {"results": []},
            "orchestration_timing": {"duration_sec": 1},
        },
    )
    monkeypatch.setattr(watcher, "_update_pointer_and_cleanup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.status_file, "write_status", status_store.write)
    monkeypatch.setattr(watcher.status_file, "read_status", status_store.read)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.github_checks, "create_check_run", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(watcher.github_checks, "update_check_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_post_commit_status", lambda *_args, **_kwargs: True)

    def _late_heartbeat(_bucket: str, _runtime_prefix: str, _run_id: str, stop_event: Any) -> None:
        stop_event.wait()
        payload = status_store.read("", "", "")
        if payload is None:
            return
        payload["vm_state"] = "acknowledged"
        payload["run_outcome"] = "running"
        payload["last_heartbeat"] = "2099-01-01T00:00:00Z"
        status_store.write("", "", "", payload)

    monkeypatch.setattr(watcher, "_heartbeat_loop", _late_heartbeat)

    watcher._process_run_trigger(
        "gs://bucket-a/runtime/triggers/runs/123.json",
        "gs://bucket-a/code",
        "gs://bucket-a/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert status_store.payload is not None
    assert status_store.payload["vm_state"] == "completed"
    assert status_store.payload["run_outcome"] == "completed"


def test_orchestrator_download_failure_marks_status_failed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    status_store = _StatusStore()

    monkeypatch.setattr(
        watcher, "_gcloud_download_json", lambda _uri: _run_payload(run_context="dev", include_pr=False, leg_count=1)
    )
    monkeypatch.setattr(
        watcher,
        "_resolve_requested_legs",
        lambda *, legs_raw, code_bucket_root: _accepted_requested_legs(legs_raw),
    )
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda _uri, _payload: True)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        watcher,
        "_download_orchestrator",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(returncode=1, cmd="gcloud storage cp")
        ),
    )
    monkeypatch.setattr(watcher.status_file, "write_status", status_store.write)
    monkeypatch.setattr(watcher.status_file, "read_status", status_store.read)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_post_commit_status", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher.github_checks, "create_check_run", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(watcher.github_checks, "update_check_run", lambda *_args, **_kwargs: None)

    watcher._process_run_trigger(
        "gs://bucket-a/runtime/triggers/runs/123.json",
        "gs://bucket-a/code",
        "gs://bucket-a/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert status_store.payload is not None
    assert status_store.payload["vm_state"] == "failed"
    assert status_store.payload["run_outcome"] == "failed"
