"""Tests for VM watcher pointer and aggregation helpers (Phase 2)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import gcp.image.vm_watcher as watcher  # type: ignore[import-not-found]
from tools.repo.sk_bmt_ids import SK_BMT_FALSE_REJECT_NAMUH


def test_results_prefix_from_ci_verdict_uri_basic():
    """Derive results_prefix from snapshot ci_verdict URI."""
    bucket_root = "gs://my-bucket"
    uri = "gs://my-bucket/sk/results/false_rejects/snapshots/run-123/ci_verdict.json"
    assert watcher._results_prefix_from_ci_verdict_uri(bucket_root, uri) == "sk/results/false_rejects"


def test_results_prefix_from_ci_verdict_uri_with_path_prefix():
    """Derive results_prefix when URI path has a prefix under bucket root."""
    bucket_root = "gs://my-bucket/prefix"
    uri = "gs://my-bucket/prefix/sk/results/false_rejects/snapshots/run-456/ci_verdict.json"
    assert watcher._results_prefix_from_ci_verdict_uri(bucket_root, uri) == "sk/results/false_rejects"


def test_results_prefix_from_ci_verdict_uri_invalid_returns_none():
    """Return None when URI has no snapshots segment or is empty."""
    bucket_root = "gs://my-bucket"
    assert watcher._results_prefix_from_ci_verdict_uri(bucket_root, "") is None
    assert watcher._results_prefix_from_ci_verdict_uri(bucket_root, "gs://other/sk/results/x.json") is None
    assert (
        watcher._results_prefix_from_ci_verdict_uri(bucket_root, "gs://my-bucket/sk/results/false_rejects/latest.json")
        is None
    )


def test_run_handshake_uri_from_trigger_uri():
    trigger_uri = "gs://my-bucket/pfx/triggers/runs/123456.json"
    expected = "gs://my-bucket/pfx/triggers/acks/123456.json"
    assert watcher._run_handshake_uri_from_trigger_uri(trigger_uri) == expected


def test_aggregate_verdicts_from_summaries_all_pass():
    """All pass/warning -> success."""
    summaries = [
        {"status": "pass", "reason_code": "score_gte_last"},
        {"status": "warning", "reason_code": "bootstrap_without_baseline"},
    ]
    state, desc = watcher._aggregate_verdicts_from_summaries(summaries)
    assert state == "success"
    assert "2/2" in desc


def test_aggregate_verdicts_from_summaries_one_fail():
    """One fail -> failure."""
    summaries = [
        {"status": "pass"},
        {"status": "fail", "reason_code": "score_below_last"},
    ]
    state, desc = watcher._aggregate_verdicts_from_summaries(summaries)
    assert state == "failure"
    assert "1" in desc
    assert "failed" in desc


def test_aggregate_verdicts_from_summaries_none_treated_as_fail():
    """None summary (e.g. manager didn't write summary) counts as fail."""
    state, desc = watcher._aggregate_verdicts_from_summaries([None, {"status": "pass"}])
    assert state == "failure"
    assert "1" in desc
    assert "failed" in desc


def test_run_id_from_json_uri():
    assert watcher._run_id_from_json_uri("gs://bucket/pfx/triggers/acks/1234.json") == "1234"
    assert watcher._run_id_from_json_uri("gs://bucket/pfx/triggers/acks/not-json.txt") is None


def test_workflow_run_sort_key_prefers_numeric():
    assert watcher._workflow_run_sort_key("123") > watcher._workflow_run_sort_key("abc")
    assert watcher._workflow_run_sort_key("200") > watcher._workflow_run_sort_key("100")


def test_trim_trigger_family_keeps_recent_and_explicit(monkeypatch):
    listed = [
        "gs://b/p/triggers/acks/100.json",
        "gs://b/p/triggers/acks/101.json",
        "gs://b/p/triggers/acks/102.json",
        "gs://b/p/triggers/acks/xyz.json",
    ]
    deleted: list[str] = []

    # _trim_trigger_family lives in trigger_cleanup and uses gcs_helpers; patch at use site
    from gcp.image import trigger_cleanup

    monkeypatch.setattr(trigger_cleanup, "_gcloud_ls", lambda *_args, **_kwargs: listed)
    monkeypatch.setattr(
        trigger_cleanup,
        "_gcloud_rm",
        lambda uri, recursive=False: deleted.append(f"{uri}|{recursive}") or True,
    )

    watcher._trim_trigger_family(
        "gs://b/p/triggers/acks/",
        keep_ids={"101"},
        keep_recent=2,
    )

    assert deleted == [
        "gs://b/p/triggers/acks/100.json|False",
        "gs://b/p/triggers/acks/xyz.json|False",
    ]


def test_cleanup_workflow_artifacts_targets_prefixed_and_base_status(monkeypatch):
    calls: list[tuple[str, set[str], int]] = []
    uploaded_calls: list[tuple[str, set[str], int]] = []

    def _capture(prefix: str, *, keep_ids: set[str], keep_recent: int) -> None:
        calls.append((prefix, set(keep_ids), keep_recent))

    def _capture_uploaded(prefix: str, *, keep_ids: set[str], keep_recent: int) -> None:
        uploaded_calls.append((prefix, set(keep_ids), keep_recent))

    monkeypatch.setattr(watcher, "_trim_trigger_family", _capture)
    monkeypatch.setattr(watcher, "_trim_uploaded_markers", _capture_uploaded)

    watcher._cleanup_workflow_artifacts(
        runtime_bucket_root="gs://my-bucket/my-prefix/runtime",
        keep_workflow_ids={"222"},
    )

    prefixes = {c[0] for c in calls}
    assert "gs://my-bucket/my-prefix/runtime/triggers/acks/" in prefixes
    assert "gs://my-bucket/my-prefix/runtime/triggers/status/" in prefixes
    assert len(prefixes) == 2
    assert all(c[1] == {"222"} for c in calls)
    assert all(c[2] == watcher._KEEP_RECENT_WORKFLOW_FILES for c in calls)

    assert len(uploaded_calls) == 1
    assert uploaded_calls[0][0] == "gs://my-bucket/my-prefix/runtime/_workflow/uploaded/"
    assert uploaded_calls[0][1] == {"222"}
    assert uploaded_calls[0][2] == watcher._KEEP_RECENT_WORKFLOW_FILES


def test_trim_uploaded_markers_deletes_old_run_dirs(monkeypatch):
    listed = [
        "gs://b/rt/_workflow/uploaded/100/sk.json",
        "gs://b/rt/_workflow/uploaded/100/qa.json",
        "gs://b/rt/_workflow/uploaded/101/sk.json",
        "gs://b/rt/_workflow/uploaded/102/sk.json",
        "gs://b/rt/_workflow/uploaded/103/sk.json",
    ]
    deleted: list[str] = []

    from gcp.image import trigger_cleanup

    monkeypatch.setattr(trigger_cleanup, "_gcloud_ls", lambda *_a, **_kw: listed)
    monkeypatch.setattr(
        trigger_cleanup,
        "_gcloud_rm",
        lambda uri, recursive=False: deleted.append(f"{uri}|{recursive}") or True,
    )

    trigger_cleanup._trim_uploaded_markers(
        "gs://b/rt/_workflow/uploaded/",
        keep_ids={"101"},
        keep_recent=2,
    )

    # keep_recent=2 → keeps 103, 102 (newest two); keep_ids={"101"} → also keeps 101
    # 100 is the only one deleted
    assert deleted == ["gs://b/rt/_workflow/uploaded/100/|True"]


def test_keep_recent_workflow_files_from_env(monkeypatch):
    # keep_recent is now a constant (TRIGGER_METADATA_KEEP_RECENT) in bmt_config; env no longer overrides.
    from gcp.image.config import bmt_config

    reloaded = importlib.reload(watcher)
    assert reloaded._KEEP_RECENT_WORKFLOW_FILES == bmt_config.TRIGGER_METADATA_KEEP_RECENT


def test_cleanup_legacy_result_history_deletes_archive_and_logs(monkeypatch):
    removed: list[tuple[str, bool]] = []

    def _capture(uri: str, *, recursive: bool = False) -> bool:
        removed.append((uri, recursive))
        return True

    from gcp.image import pointer_update

    monkeypatch.setattr(pointer_update, "_gcloud_rm", _capture)

    watcher._cleanup_legacy_result_history("gs://b/p", "sk/results/false_rejects")

    assert removed == [
        ("gs://b/p/sk/results/archive", True),
        ("gs://b/p/sk/results/logs/false_rejects", True),
    ]


def test_process_run_trigger_splits_runtime_and_gate_contexts(monkeypatch, tmp_path: Path):
    status_store: dict[str, object] = {}
    posted_resilient: list[tuple[str, str]] = []
    created_check_names: list[str] = []
    finalized_check_names: list[str] = []
    pointer_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        watcher,
        "_gcloud_download_json",
        lambda _uri: {
            "workflow_run_id": "123",
            "repository": "owner/repo",
            "sha": "abc123",
            "run_context": "dev",
            "bucket": "bucket",
            "status_context": "BMT Gate",
            "runtime_status_context": "BMT Runtime",
            "legs": [{"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH, "run_id": "run-1"}],
        },
    )
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda *_args, **_kwargs: True)

    def _write_status(_bucket: str, _runtime_prefix: str, _run_id: str, payload: dict[str, object]) -> None:
        status_store.clear()
        status_store.update(json.loads(json.dumps(payload)))

    def _read_status(_bucket: str, _runtime_prefix: str, _run_id: str) -> dict[str, object]:
        return json.loads(json.dumps(status_store))

    monkeypatch.setattr(watcher.status_file, "write_status", _write_status)
    monkeypatch.setattr(watcher.status_file, "read_status", _read_status)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_download_orchestrator", lambda *_args, **_kwargs: tmp_path / "orchestrator.py")
    monkeypatch.setattr(watcher, "_run_orchestrator", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(watcher, "_latest_run_root", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        watcher,
        "_resolve_requested_legs",
        lambda **_kwargs: [
            {
                "index": 0,
                "project": "sk",
                "bmt_id": SK_BMT_FALSE_REJECT_NAMUH,
                "run_id": "run-1",
                "decision": "accepted",
                "reason": None,
            }
        ],
    )
    monkeypatch.setattr(
        watcher,
        "_load_manager_summary",
        lambda _run_root: {
            "status": "pass",
            "project_id": "sk",
            "bmt_id": SK_BMT_FALSE_REJECT_NAMUH,
            "run_id": "run-1",
            "passed": True,
            "ci_verdict_uri": "gs://bucket/runtime/sk/results/false_rejects/snapshots/run-1/ci_verdict.json",
            "bmt_results": {"results": []},
            "orchestration_timing": {"duration_sec": 1},
        },
    )
    monkeypatch.setattr(watcher, "_update_pointer_and_cleanup", lambda _root, summary: pointer_calls.append(summary))

    def _create_check(
        token: str,
        repository: str,
        sha: str,
        name: str,
        status: str,
        output: dict[str, object],
        token_resolver,
    ) -> tuple[int | None, str]:
        del token, repository, sha, status, output, token_resolver
        created_check_names.append(name)
        return 42, "token"

    monkeypatch.setattr(watcher, "_create_check_run_resilient", _create_check)
    monkeypatch.setattr(watcher, "_update_check_run_resilient", lambda *_args, **_kwargs: (42, "token"))

    def _finalize_check(
        *,
        token: str,
        repository: str,
        sha: str,
        status_context: str,
        check_run_id: int | None,
        conclusion: str,
        output: dict[str, object],
        token_resolver,
    ) -> tuple[int | None, str, bool]:
        del token, repository, sha, check_run_id, conclusion, output, token_resolver
        finalized_check_names.append(status_context)
        return 42, "token", True

    monkeypatch.setattr(watcher, "_finalize_check_run_resilient", _finalize_check)

    def _post_resilient(
        repository: str,
        sha: str,
        state: str,
        description: str,
        target_url: str | None,
        token: str,
        *,
        context: str,
        token_resolver,
        attempts: int = 2,
    ) -> bool:
        del repository, sha, description, target_url, token, token_resolver, attempts
        posted_resilient.append((state, context))
        return True

    monkeypatch.setattr(watcher, "_post_commit_status_resilient", _post_resilient)
    monkeypatch.setattr(
        watcher,
        "_post_commit_status",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(watcher.github_pr_comment, "upsert_pr_comment_by_marker", lambda *_args, **_kwargs: True)

    watcher._process_run_trigger(
        "gs://bucket/runtime/triggers/runs/123.json",
        "gs://bucket/code",
        "gs://bucket/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    # Runtime context is check-run only.
    assert all(context != "BMT Runtime" for _, context in posted_resilient)
    assert created_check_names == ["BMT Runtime"]
    assert finalized_check_names == ["BMT Runtime"]

    # Gate context receives terminal result only.
    assert ("success", "BMT Gate") in posted_resilient
    assert pointer_calls, "Expected pointer promotion on successful run"


def test_process_run_trigger_rejects_missing_repository(monkeypatch, tmp_path: Path):
    removed: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        watcher,
        "_gcloud_download_json",
        lambda _uri: {
            "workflow_run_id": "123",
            "legs": [{"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH, "run_id": "run-1"}],
        },
    )
    monkeypatch.setattr(
        watcher,
        "_gcloud_rm",
        lambda uri, recursive=False: removed.append((uri, recursive)) or True,
    )

    watcher._process_run_trigger(
        "gs://bucket/runtime/triggers/runs/123.json",
        "gs://bucket/code",
        "gs://bucket/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert removed == [("gs://bucket/runtime/triggers/runs/123.json", False)]


def test_process_run_trigger_rejects_when_auth_unavailable(monkeypatch, tmp_path: Path):
    removed: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        watcher,
        "_gcloud_download_json",
        lambda _uri: {
            "workflow_run_id": "123",
            "repository": "owner/repo",
            "legs": [{"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH, "run_id": "run-1"}],
        },
    )
    monkeypatch.setattr(
        watcher,
        "_gcloud_rm",
        lambda uri, recursive=False: removed.append((uri, recursive)) or True,
    )

    watcher._process_run_trigger(
        "gs://bucket/runtime/triggers/runs/123.json",
        "gs://bucket/code",
        "gs://bucket/runtime",
        tmp_path,
        lambda _repository: None,
    )

    assert removed == []


def test_process_run_trigger_defers_on_transient_download_error(monkeypatch, tmp_path: Path):
    removed: list[tuple[str, bool]] = []
    monkeypatch.setattr(watcher, "_gcloud_download_json", lambda _uri: (None, "download_failed"))
    monkeypatch.setattr(
        watcher,
        "_gcloud_rm",
        lambda uri, recursive=False: removed.append((uri, recursive)) or True,
    )

    watcher._process_run_trigger(
        "gs://bucket/runtime/triggers/runs/123.json",
        "gs://bucket/code",
        "gs://bucket/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert removed == []


def test_process_run_trigger_removes_malformed_trigger(monkeypatch, tmp_path: Path):
    removed: list[tuple[str, bool]] = []
    monkeypatch.setattr(watcher, "_gcloud_download_json", lambda _uri: (None, "invalid_json"))
    monkeypatch.setattr(
        watcher,
        "_gcloud_rm",
        lambda uri, recursive=False: removed.append((uri, recursive)) or True,
    )

    watcher._process_run_trigger(
        "gs://bucket/runtime/triggers/runs/123.json",
        "gs://bucket/code",
        "gs://bucket/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert removed == [("gs://bucket/runtime/triggers/runs/123.json", False)]


def test_process_run_trigger_closed_pr_skips_pointer_promotion(monkeypatch, tmp_path: Path):
    pointer_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        watcher,
        "_gcloud_download_json",
        lambda _uri: {
            "workflow_run_id": "123",
            "repository": "owner/repo",
            "sha": "abc123",
            "run_context": "pr",
            "pull_request_number": 9,
            "bucket": "bucket",
            "legs": [{"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH, "run_id": "run-1"}],
        },
    )
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
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher.status_file, "write_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.status_file, "read_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_gcloud_rm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_cleanup_workflow_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(watcher, "_prune_workspace_runs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_post_commit_status", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_update_pointer_and_cleanup", lambda _root, summary: pointer_calls.append(summary))

    watcher._process_run_trigger(
        "gs://bucket/runtime/triggers/runs/123.json",
        "gs://bucket/code",
        "gs://bucket/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert pointer_calls == []


def test_process_run_trigger_superseded_mid_run_skips_pointer_promotion(monkeypatch, tmp_path: Path):
    pointer_calls: list[dict[str, object]] = []
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
                "head_sha": "newsha456",
                "checked_at": "2026-02-26T00:00:10Z",
                "error": None,
            },
        ]
    )
    monkeypatch.setattr(
        watcher,
        "_gcloud_download_json",
        lambda _uri: {
            "workflow_run_id": "123",
            "repository": "owner/repo",
            "sha": "abc123",
            "run_context": "pr",
            "pull_request_number": 9,
            "bucket": "bucket",
            "legs": [
                {"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH, "run_id": "run-1"},
                {"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH, "run_id": "run-2"},
            ],
        },
    )
    monkeypatch.setattr(watcher.github_pull_request, "get_pr_state", lambda *_args, **_kwargs: next(pr_states))
    monkeypatch.setattr(watcher, "_gcloud_upload_json", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher.status_file, "write_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher.status_file, "read_status", lambda *_args, **_kwargs: {"legs": [{}, {}]})
    monkeypatch.setattr(watcher.status_file, "write_last_run_duration", lambda *_args, **_kwargs: None)
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
            "bmt_id": SK_BMT_FALSE_REJECT_NAMUH,
            "run_id": "run-1",
            "passed": True,
            "ci_verdict_uri": "gs://bucket/runtime/sk/results/false_rejects/snapshots/run-1/ci_verdict.json",
            "bmt_results": {"results": []},
            "orchestration_timing": {"duration_sec": 1},
        },
    )
    monkeypatch.setattr(watcher.github_checks, "create_check_run", lambda *_args, **_kwargs: 42)
    monkeypatch.setattr(watcher.github_checks, "update_check_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(watcher, "_post_commit_status", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher.github_pr_comment, "upsert_pr_comment_by_marker", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(watcher, "_update_pointer_and_cleanup", lambda _root, summary: pointer_calls.append(summary))

    watcher._process_run_trigger(
        "gs://bucket/runtime/triggers/runs/123.json",
        "gs://bucket/code",
        "gs://bucket/runtime",
        tmp_path,
        lambda _repository: "token",
    )

    assert pointer_calls == []
