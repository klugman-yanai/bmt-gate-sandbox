#!/usr/bin/env python3
"""VM-side trigger watcher.

Polls GCS (or Pub/Sub) for run trigger files, runs root_orchestrator.py
for each leg, aggregates verdicts, and posts commit status to GitHub so
the PR is gated without blocking the workflow runner.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gcp.image import log_config
from gcp.image.gcs_helpers import (
    _gcloud_download_json,
    _gcloud_exists,
    _gcloud_rm,
    _gcloud_upload_json,
    _get_gcs_client,
    _parse_gcs_uri,
    generate_signed_url,
)
from gcp.image.github_status import (
    DEFAULT_STATUS_CONTEXT,
    _create_check_run_resilient,
    _finalize_check_run_resilient,
    _post_commit_status,
    _post_commit_status_resilient as _post_commit_status_resilient_impl,
    _update_check_run_resilient,
)
from gcp.image.pointer_update import (
    _cleanup_legacy_result_history,  # noqa: F401
    _results_prefix_from_ci_verdict_uri,  # noqa: F401
    _update_pointer_and_cleanup,
)
from gcp.image.trigger_cleanup import (
    _cleanup_workflow_artifacts as _cleanup_workflow_artifacts_impl,
    _run_id_from_json_uri,  # noqa: F401
    _trim_trigger_family,
    _workflow_run_sort_key,  # noqa: F401
)
from gcp.image.trigger_resolution import (
    _discover_run_triggers,
    _load_jobs_config_from_gcs,
    _resolve_requested_legs as _resolve_requested_legs_impl,
    _run_handshake_uri_from_trigger_uri,
)
from gcp.image.verdict_aggregation import (
    _aggregate_verdicts_from_summaries,
    _comment_marker_for_sha,
    _failed_legs_display,
    _format_bmt_comment,
    _load_manager_summary,
    _short_sha,
)


def _post_commit_status_resilient(
    repository: str,
    sha: str,
    state: str,
    description: str,
    target_url: str | None,
    token: str,
    *,
    context: str,
    token_resolver: Callable[[str], str | None],
    attempts: int = 3,
) -> bool:
    """Post commit status with retries; injects _post_commit_status for testability."""
    return _post_commit_status_resilient_impl(
        repository,
        sha,
        state,
        description,
        target_url,
        token,
        context=context,
        token_resolver=token_resolver,
        attempts=attempts,
        _post_func=_post_commit_status,
    )


def _resolve_requested_legs(
    *,
    legs_raw: list[Any],
    code_bucket_root: str,
) -> list[dict[str, Any]]:
    """Resolve requested legs; injects _gcloud_exists and _load_jobs_config for testability."""
    return _resolve_requested_legs_impl(
        legs_raw=legs_raw,
        code_bucket_root=code_bucket_root,
        _exists_func=_gcloud_exists,
        _load_jobs_func=_load_jobs_config_from_gcs,
    )


def _get_bmt_config_defaults() -> tuple[int, int, int]:
    try:
        import config.bmt_config as _m
    except ImportError:
        import gcp.image.config.bmt_config as _m
    return (
        int(_m.IDLE_TIMEOUT_SEC),
        int(_m.STALE_TRIGGER_AGE_HOURS),
        int(_m.TRIGGER_METADATA_KEEP_RECENT),
    )


_idle_sec_val, _stale_hours_val, _keep_recent_val = _get_bmt_config_defaults()
try:
    from config.bmt_config import DEFAULT_RUNTIME_CONTEXT, get_config
    from utils import _bucket_uri, _code_bucket_root, _now_iso, _runtime_bucket_root

    from gcp.image.config.constants import EXECUTABLE_MODE, HTTP_TIMEOUT

    from .github import (
        github_auth,
        github_checks,
        github_pr_comment,
        github_pull_request,
        status_file,
    )
except ImportError:
    from gcp.image.config.bmt_config import DEFAULT_RUNTIME_CONTEXT, get_config
    from gcp.image.config.constants import EXECUTABLE_MODE, HTTP_TIMEOUT
    from gcp.image.github import (
        github_auth,
        github_checks,
        github_pr_comment,
        github_pull_request,
        status_file,
    )
    from gcp.image.utils import _bucket_uri, _code_bucket_root, _now_iso, _runtime_bucket_root

IDLE_TIMEOUT_DEFAULT = _idle_sec_val
STALE_TRIGGER_AGE_HOURS_DEFAULT = _stale_hours_val
KEEP_RECENT_DEFAULT = _keep_recent_val

_shutdown_holder: list[bool] = [False]
_KEEP_RECENT_LOCAL_RUNS = 2

# Fallback when trigger payload omits contexts; single source of truth gcp/image/config/bmt_config.py
DEFAULT_RUNTIME_STATUS_CONTEXT: str = DEFAULT_RUNTIME_CONTEXT


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


# Trigger metadata retention and stale age: fixed behavioral constants (from bmt_config)
_KEEP_RECENT_WORKFLOW_FILES = KEEP_RECENT_DEFAULT
_STALE_TRIGGER_AGE_HOURS = STALE_TRIGGER_AGE_HOURS_DEFAULT


def _cleanup_workflow_artifacts(
    *,
    runtime_bucket_root: str,
    keep_workflow_ids: set[str],
    keep_recent: int = _KEEP_RECENT_WORKFLOW_FILES,
    stale_hours: int = _STALE_TRIGGER_AGE_HOURS,
) -> None:
    """Keep workflow metadata bounded; injects _trim_trigger_family for testability."""
    _cleanup_workflow_artifacts_impl(
        runtime_bucket_root=runtime_bucket_root,
        keep_workflow_ids=keep_workflow_ids,
        keep_recent=keep_recent,
        stale_hours=stale_hours,
        _trim_func=_trim_trigger_family,
    )


def _handle_signal(_signum: int, _frame: Any) -> None:
    _shutdown_holder[0] = True


def parse_args() -> argparse.Namespace:
    cfg = get_config(runtime=os.environ)
    parser = argparse.ArgumentParser(description="Poll GCS or Pub/Sub for BMT trigger files")
    _ = parser.add_argument("--bucket", required=True)
    _ = parser.add_argument("--poll-interval-sec", type=int, default=10)
    _ = parser.add_argument("--workspace-root", default=os.environ.get("BMT_WORKSPACE_ROOT", ""))
    _ = parser.add_argument(
        "--exit-after-run",
        action="store_true",
        help="Exit after processing one run (for on-demand VM: then stop instance).",
    )
    _ = parser.add_argument(
        "--idle-timeout-sec",
        type=int,
        default=IDLE_TIMEOUT_DEFAULT,
        help="With --exit-after-run: idle period after each run with no new trigger before exiting (0=exit immediately after run).",
    )
    _ = parser.add_argument(
        "--subscription",
        default=cfg.effective_pubsub_subscription or "",
        help="Pub/Sub subscription ID (e.g. bmt-vm-myvm). When set, uses Pub/Sub instead of GCS polling.",
    )
    _ = parser.add_argument(
        "--gcp-project",
        default=cfg.gcp_project or "",
        help="GCP project ID (required when --subscription is set).",
    )
    return parser.parse_args()


def _resolve_workspace_root(raw: str) -> Path:
    """Default to ~/bmt_workspace with compatibility fallback to legacy ~/sk_runtime."""
    if raw.strip():
        return Path(raw).expanduser().resolve()
    preferred = Path("~/bmt_workspace").expanduser()
    legacy = Path("~/sk_runtime").expanduser()
    if legacy.exists() and not preferred.exists():
        return legacy.resolve()
    return preferred.resolve()


def _download_orchestrator(code_bucket_root: str, workspace_root: Path) -> Path:
    """Download root_orchestrator.py from the code namespace."""
    orchestrator_uri = _bucket_uri(code_bucket_root, "root_orchestrator.py")
    local_path = workspace_root / "bin" / "root_orchestrator.py"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    bucket_name, blob_name = _parse_gcs_uri(orchestrator_uri)
    _get_gcs_client().bucket(bucket_name).blob(blob_name).download_to_filename(str(local_path))
    local_path.chmod(local_path.stat().st_mode | EXECUTABLE_MODE)
    return local_path


def _run_orchestrator(
    orchestrator_path: Path,
    trigger: dict[str, Any],
    workspace_root: Path,
) -> int:
    """Invoke root_orchestrator.py with parameters from the trigger file."""
    command = [
        sys.executable,
        str(orchestrator_path),
        "--bucket",
        str(trigger["bucket"]),
        "--project",
        str(trigger["project"]),
        "--bmt-id",
        str(trigger["bmt_id"]),
        "--run-context",
        str(trigger.get("run_context", "manual")),
        "--run-id",
        str(trigger["run_id"]),
        "--workspace-root",
        str(workspace_root),
    ]
    # Add progress tracking parameters if available
    if "leg_index" in trigger:
        command.extend(["--leg-index", str(trigger["leg_index"])])
    if "workflow_run_id" in trigger:
        command.extend(["--workflow-run-id", str(trigger["workflow_run_id"])])

    proc = subprocess.run(command, check=False)
    return proc.returncode


def _latest_run_root(workspace_root: Path, project: str, bmt_id: str) -> Path | None:
    """Return the most recently modified run_* directory under workspace_root/project/bmt_id, or None."""
    parent = workspace_root / project / bmt_id
    if not parent.is_dir():
        return None
    run_dirs = sorted(
        [d for d in parent.iterdir() if d.is_dir() and d.name.startswith("run_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return run_dirs[0] if run_dirs else None


def _prune_run_dirs(run_parent: Path, keep_recent: int = _KEEP_RECENT_LOCAL_RUNS) -> None:
    """Keep only the newest ``keep_recent`` run_* directories under one parent."""
    if not run_parent.is_dir():
        return
    keep_recent = max(keep_recent, 1)
    run_dirs: list[tuple[float, Path]] = []
    for candidate in run_parent.iterdir():
        if not candidate.is_dir() or not candidate.name.startswith("run_"):
            continue
        try:
            run_dirs.append((candidate.stat().st_mtime, candidate))
        except OSError:
            continue
    run_dirs.sort(key=lambda item: item[0], reverse=True)
    for _, stale_dir in run_dirs[keep_recent:]:
        shutil.rmtree(stale_dir, ignore_errors=True)


def _prune_workspace_runs(workspace_root: Path, keep_recent_per_bmt: int = _KEEP_RECENT_LOCAL_RUNS) -> None:
    """Prune local workspace so each project/BMT keeps only current + previous run."""
    _prune_run_dirs(workspace_root, keep_recent=keep_recent_per_bmt)
    for project_dir in workspace_root.iterdir():
        if not project_dir.is_dir():
            continue
        for bmt_dir in project_dir.iterdir():
            if bmt_dir.is_dir():
                _prune_run_dirs(bmt_dir, keep_recent=keep_recent_per_bmt)


def _heartbeat_loop(bucket: str, runtime_prefix: str, run_id: str, stop_event: threading.Event) -> None:
    """Background thread to update heartbeat every 15s."""
    while not stop_event.is_set():
        with contextlib.suppress(subprocess.CalledProcessError, OSError, ValueError, RuntimeError):
            status_file.update_heartbeat(bucket, runtime_prefix, run_id)
        stop_event.wait(15)  # Sleep 15s or until stop_event


def _check_run_progress_loop(
    bucket: str,
    runtime_prefix: str,
    run_id: str,
    repository: str,
    check_run_id: int,
    github_token: str,
    token_resolver: Callable[[str], str | None],
    stop_event: threading.Event,
    interval_sec: int = 30,
) -> None:
    """Background thread to update the Check Run every ~30s with GCS status data."""
    stop_event.wait(interval_sec)  # Initial delay — avoid double-update right after creation
    while not stop_event.is_set():
        try:
            current_status = status_file.read_status(bucket, runtime_prefix, run_id)
            if current_status is None:
                break
            vm_state = current_status.get("vm_state", "")
            if vm_state in ("done", "failed", "cancelled", "superseded"):
                break
            legs = current_status.get("legs") or []
            elapsed_sec = int(current_status.get("elapsed_sec") or 0)
            eta_sec = current_status.get("eta_sec")
            summary = github_checks.render_progress_markdown(legs, elapsed_sec, eta_sec)
            current_leg = current_status.get("current_leg") or {}
            files_completed = current_leg.get("files_completed")
            files_total = current_leg.get("files_total")
            if files_completed is not None and files_total is not None:
                title = f"Running — file {files_completed}/{files_total}"
            else:
                legs_done = sum(1 for leg in legs if leg.get("status") not in ("pending", "running"))
                title = f"Running — {legs_done}/{len(legs)} tasks complete"
            _update_check_run_resilient(
                github_token,
                repository,
                check_run_id,
                token_resolver=token_resolver,
                output={"title": title, "summary": summary},
                attempts=2,
            )
        except (subprocess.CalledProcessError, OSError, ValueError, RuntimeError):
            pass
        stop_event.wait(interval_sec)


def _get_pr_state_at_pickup(
    *,
    should_check_pr_state: bool,
    pr_number: int | None,
    github_token: str,
    repository: str,
    sha: str,
) -> tuple[dict[str, str | bool | None] | None, str | None, str | None]:
    """Return (pr_state_at_pickup, skip_before_pickup_reason, superseded_by_sha)."""
    if not should_check_pr_state or pr_number is None:
        return None, None, None
    pr_state_at_pickup = github_pull_request.get_pr_state(github_token, repository, pr_number, attempts=3)
    state_at_pickup = str(pr_state_at_pickup.get("state"))
    if state_at_pickup == "closed":
        return pr_state_at_pickup, "pr_closed_before_pickup", None
    if state_at_pickup != "unknown":
        pr_head_sha = pr_state_at_pickup.get("head_sha")
        pr_head_sha = pr_head_sha.strip() or None if isinstance(pr_head_sha, str) else None
        if sha and pr_head_sha and pr_head_sha != sha:
            return pr_state_at_pickup, "superseded_by_new_commit", pr_head_sha
    return pr_state_at_pickup, None, None


def _build_leg_lists(
    requested_legs: list[dict[str, Any]],
    *,
    skip_before_pickup: bool,
    skip_before_pickup_reason: str | None,
) -> tuple[list[dict[str, str]], list[dict[str, int | str]], list[dict[str, str | int]]]:
    """Build accepted_legs, rejected_legs, accepted_exec_legs from requested_legs. Mutates requested_legs if skip."""
    if skip_before_pickup:
        for leg in requested_legs:
            leg["decision"] = "rejected"
            leg["reason"] = skip_before_pickup_reason or "skipped"
    accepted_legs = [
        {
            "project": str(leg.get("project", "?")),
            "bmt_id": str(leg.get("bmt_id", "?")),
            "run_id": str(leg.get("run_id", "?")),
        }
        for leg in requested_legs
        if leg.get("decision") == "accepted"
    ]
    rejected_legs = [
        {
            "index": int(leg.get("index", -1)),
            "project": str(leg.get("project", "?")),
            "bmt_id": str(leg.get("bmt_id", "?")),
            "run_id": str(leg.get("run_id", "?")),
            "reason": str(leg.get("reason") or "invalid_leg_type"),
        }
        for leg in requested_legs
        if leg.get("decision") != "accepted"
    ]
    accepted_exec_legs = [
        {
            "index": int(leg.get("index", -1)),
            "project": str(leg.get("project", "?")),
            "bmt_id": str(leg.get("bmt_id", "?")),
            "run_id": str(leg.get("run_id", "?")),
        }
        for leg in requested_legs
        if leg.get("decision") == "accepted"
    ]
    return accepted_legs, rejected_legs, accepted_exec_legs


def _download_and_parse_trigger(uri: str) -> dict | None:
    """Download trigger JSON; return parsed payload or None. Deletes uri on invalid_json."""
    downloaded = _gcloud_download_json(uri)
    if (
        isinstance(downloaded, tuple)
        and len(downloaded) == 2
        and (downloaded[0] is None or isinstance(downloaded[0], dict))
    ):
        run_payload, run_payload_error = downloaded
    else:
        run_payload = downloaded if isinstance(downloaded, dict) else None
        run_payload_error = None
    if run_payload is None:
        if run_payload_error == "invalid_json":
            _gcloud_rm(uri)
        return None
    return run_payload


def _process_run_trigger(
    run_trigger_uri: str,
    default_code_bucket_root: str,
    default_runtime_bucket_root: str,
    workspace_root: Path,
    github_token_resolver: Callable[[str], str | None],
) -> bool:
    """Returns True if trigger was consumed (exit-after-run may fire), False if kept for retry."""
    run_payload = _download_and_parse_trigger(run_trigger_uri)
    if run_payload is None:
        return False

    legs_raw = run_payload.get("legs") or []
    if not isinstance(legs_raw, list):
        legs_raw = []

    repository = (run_payload.get("repository") or "").strip()
    sha = (run_payload.get("sha") or "").strip()
    run_context = str(run_payload.get("run_context", "manual"))
    workflow_run_id = run_payload.get("workflow_run_id", "?")
    gate_status_context = (
        run_payload.get("status_context") or DEFAULT_STATUS_CONTEXT
    ).strip() or DEFAULT_STATUS_CONTEXT
    runtime_status_context = (
        run_payload.get("runtime_status_context") or DEFAULT_RUNTIME_STATUS_CONTEXT
    ).strip() or DEFAULT_RUNTIME_STATUS_CONTEXT

    pr_number: int | None = None
    pr_raw = run_payload.get("pull_request_number")
    if pr_raw is not None:
        with contextlib.suppress(TypeError, ValueError):
            pr_number = int(pr_raw)

    if not repository:
        _gcloud_rm(run_trigger_uri)
        return False

    github_token = github_token_resolver(repository)
    if not github_token:
        return False

    if not legs_raw:
        _gcloud_rm(run_trigger_uri)
        return False

    bucket = str(run_payload.get("bucket", "")).strip()
    code_bucket_root = _code_bucket_root(bucket) if bucket else default_code_bucket_root
    runtime_bucket_root = _runtime_bucket_root(bucket) if bucket else default_runtime_bucket_root
    runtime_prefix = ""  # bucket root; no runtime/ prefix

    run_id = str(workflow_run_id)
    workflow_run_id_str = str(workflow_run_id)

    should_check_pr_state = run_context == "pr" and pr_number is not None
    pr_state_at_pickup, skip_before_pickup_reason, superseded_by_sha = _get_pr_state_at_pickup(
        should_check_pr_state=should_check_pr_state,
        pr_number=pr_number,
        github_token=github_token,
        repository=repository,
        sha=sha,
    )
    skip_before_pickup = bool(skip_before_pickup_reason)

    requested_legs = _resolve_requested_legs(
        legs_raw=legs_raw,
        code_bucket_root=code_bucket_root,
    )
    accepted_legs, rejected_legs, accepted_exec_legs = _build_leg_lists(
        requested_legs,
        skip_before_pickup=skip_before_pickup,
        skip_before_pickup_reason=skip_before_pickup_reason,
    )
    accepted_leg_count = len(accepted_exec_legs)

    stop_heartbeat = threading.Event()
    heartbeat_thread: threading.Thread | None = None
    stop_progress = threading.Event()
    progress_thread: threading.Thread | None = None
    check_run_id: int | None = None
    cancelled_due_to_pr_state = False
    cancel_reason: str | None = None
    pointer_promotion_allowed = True
    start_timestamp = time.monotonic()
    leg_summaries: list[dict[str, Any] | None] = []

    def _stop_heartbeat_thread() -> None:
        nonlocal heartbeat_thread
        stop_heartbeat.set()
        if heartbeat_thread is None:
            return
        heartbeat_thread.join(timeout=5)
        heartbeat_thread = None

    def _stop_progress_thread() -> None:
        nonlocal progress_thread
        stop_progress.set()
        if progress_thread is None:
            return
        progress_thread.join(timeout=5)
        progress_thread = None

    def _upsert_pr_comment(
        *,
        result: str,
        summary_line: str,
        details_line: str,
        superseding_sha: str | None = None,
    ) -> None:
        nonlocal github_token
        if pr_number is None or not repository or not sha or not github_token:
            return
        marker = _comment_marker_for_sha(sha)
        body = _format_bmt_comment(
            result,
            summary_line,
            details_line,
            repository=repository,
            tested_sha=sha,
            workflow_run_id=workflow_run_id,
            pr_number=pr_number,
            server_url=(run_payload.get("server_url") or "https://github.com").strip(),
            superseding_sha=superseding_sha,
        )
        if github_pr_comment.upsert_pr_comment_by_marker(github_token, repository, pr_number, marker, body):
            pass
        else:
            pass

    try:
        handshake_uri = _run_handshake_uri_from_trigger_uri(run_trigger_uri)
        if skip_before_pickup:
            run_disposition = "skipped"
        elif accepted_leg_count == 0:
            run_disposition = "accepted_but_empty"
        else:
            run_disposition = "accepted"

        handshake_payload: dict[str, Any] = {
            "support_resolution_version": "v2",
            "workflow_run_id": str(workflow_run_id),
            "received_at": _now_iso(),
            "repository": repository,
            "sha": sha,
            "run_context": run_context,
            "run_trigger_uri": run_trigger_uri,
            "requested_leg_count": len(requested_legs),
            "accepted_leg_count": accepted_leg_count,
            "requested_legs": requested_legs,
            "accepted_legs": accepted_legs,
            "rejected_legs": rejected_legs,
            "run_disposition": run_disposition,
            "skip_reason": skip_before_pickup_reason if skip_before_pickup else None,
            "pr_state": pr_state_at_pickup.get("state") if pr_state_at_pickup else None,
            "pr_merged": pr_state_at_pickup.get("merged") if pr_state_at_pickup else None,
            "pr_state_checked_at": pr_state_at_pickup.get("checked_at") if pr_state_at_pickup else None,
            "pr_head_sha": pr_state_at_pickup.get("head_sha") if pr_state_at_pickup else None,
            "superseded_by_sha": superseded_by_sha,
            "vm": {
                "hostname": os.uname().nodename,
                "pid": os.getpid(),
            },
        }
        if _gcloud_upload_json(handshake_uri, handshake_payload):
            pass

        started_at = _now_iso()
        initial_legs: list[dict[str, Any]] = []
        for leg in requested_legs:
            idx = int(leg.get("index", -1))
            project = str(leg.get("project", "?"))
            bmt_id = str(leg.get("bmt_id", "?"))
            leg_run_id = str(leg.get("run_id", "?"))
            decision = str(leg.get("decision", "rejected"))
            reason = str(leg.get("reason")) if leg.get("reason") is not None else None
            is_skipped = skip_before_pickup or decision != "accepted"
            initial_legs.append(
                {
                    "index": idx,
                    "project": project,
                    "bmt_id": bmt_id,
                    "run_id": leg_run_id,
                    "status": "skipped" if is_skipped else "pending",
                    "skip_reason": (skip_before_pickup_reason if skip_before_pickup else reason)
                    if is_skipped
                    else None,
                    "started_at": None,
                    "completed_at": started_at if is_skipped else None,
                    "duration_sec": None,
                    "files_total": None,
                    "files_completed": 0,
                }
            )

        try:
            last_run_duration_sec = status_file.read_last_run_duration(bucket, runtime_prefix)
        except (subprocess.CalledProcessError, OSError, ValueError):
            last_run_duration_sec = None

        initial_status = {
            "run_id": run_id,
            "workflow_run_id": workflow_run_id,
            "repository": repository,
            "sha": sha,
            "vm_state": (
                "skipped_pr_closed_before_pickup"
                if skip_before_pickup_reason == "pr_closed_before_pickup"
                else "skipped_superseded_by_new_commit"
                if skip_before_pickup_reason == "superseded_by_new_commit"
                else "accepted_but_empty"
                if accepted_leg_count == 0
                else "acknowledged"
            ),
            "started_at": started_at,
            "last_heartbeat": started_at,
            "legs_total": len(requested_legs),
            "legs_completed": 0,
            "current_leg": None,
            "legs": initial_legs,
            "eta_sec": None,
            "elapsed_sec": 0,
            "last_run_duration_sec": last_run_duration_sec,
            "errors": [],
            "run_outcome": "skipped" if (skip_before_pickup or accepted_leg_count == 0) else "running",
            "cancel_reason": (
                skip_before_pickup_reason
                if skip_before_pickup
                else "no_runtime_supported_legs"
                if accepted_leg_count == 0
                else None
            ),
            "cancelled_at": started_at if (skip_before_pickup or accepted_leg_count == 0) else None,
            "superseded_by_sha": superseded_by_sha,
        }
        with contextlib.suppress(subprocess.CalledProcessError, OSError, ValueError):
            status_file.write_status(bucket, runtime_prefix, run_id, initial_status)

        if skip_before_pickup:
            if skip_before_pickup_reason == "superseded_by_new_commit":
                pass
            else:
                pass
            return False

        if accepted_leg_count == 0:
            return False

        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(bucket, runtime_prefix, run_id, stop_heartbeat),
            daemon=True,
        )
        heartbeat_thread.start()

        if repository and sha and github_token:
            check_run_id, github_token = _create_check_run_resilient(
                github_token,
                repository,
                sha,
                name=runtime_status_context,
                status="in_progress",
                output={
                    "title": f"BMT Execution Started ({accepted_leg_count} tasks)",
                    "summary": f"Running {accepted_leg_count} test suites…",
                },
                token_resolver=github_token_resolver,
            )
            if check_run_id is not None:
                progress_thread = threading.Thread(
                    target=_check_run_progress_loop,
                    args=(
                        bucket,
                        runtime_prefix,
                        run_id,
                        repository,
                        check_run_id,
                        github_token,
                        github_token_resolver,
                        stop_progress,
                    ),
                    daemon=True,
                )
                progress_thread.start()

        try:
            orchestrator_path = _download_orchestrator(code_bucket_root, workspace_root)
        except subprocess.CalledProcessError:
            _stop_heartbeat_thread()
            _stop_progress_thread()
            try:
                failed_at = _now_iso()
                failed_status = status_file.read_status(bucket, runtime_prefix, run_id)
                if failed_status:
                    failed_status["vm_state"] = "failed"
                    failed_status["run_outcome"] = "failed"
                    failed_status["cancel_reason"] = None
                    failed_status["cancelled_at"] = None
                    failed_status["superseded_by_sha"] = None
                    failed_status["current_leg"] = None
                    failed_status["last_heartbeat"] = failed_at
                    failed_status["elapsed_sec"] = int(time.monotonic() - start_timestamp)
                    errors = failed_status.get("errors")
                    if not isinstance(errors, list):
                        errors = []
                    errors.append(
                        {
                            "at": failed_at,
                            "message": "Failed to download orchestrator on VM.",
                        }
                    )
                    failed_status["errors"] = errors
                    status_file.write_status(bucket, runtime_prefix, run_id, failed_status)
            except (subprocess.CalledProcessError, OSError, ValueError):
                pass
            if repository and sha and github_token:
                _post_commit_status_resilient(
                    repository,
                    sha,
                    "failure",
                    "Test runner could not be loaded on the VM.",
                    None,
                    github_token,
                    context=gate_status_context,
                    token_resolver=github_token_resolver,
                )
                check_run_id, github_token, _ = _finalize_check_run_resilient(
                    token=github_token,
                    repository=repository,
                    sha=sha,
                    status_context=runtime_status_context,
                    check_run_id=check_run_id,
                    conclusion="failure",
                    output={
                        "title": "BMT VM Error",
                        "summary": "Test runner could not be started on the VM.",
                    },
                    token_resolver=github_token_resolver,
                )
                if pr_number is not None:
                    _upsert_pr_comment(
                        result="⚠️ Tests did not run",
                        summary_line="The test runner could not start on the VM.",
                        details_line="For details, open the **Checks** tab on this PR.",
                    )
            return False

        try:
            accepted_completed = 0
            for exec_idx, leg in enumerate(accepted_exec_legs):
                status_idx = int(leg["index"])
                if should_check_pr_state and pr_number is not None:
                    pr_state_now = github_pull_request.get_pr_state(github_token, repository, pr_number, attempts=3)
                    state_now = str(pr_state_now.get("state"))
                    if state_now == "unknown":
                        pass
                    else:
                        cancel_detected = False
                        detected_reason: str | None = None
                        detected_superseding_sha: str | None = None

                        if state_now == "closed":
                            cancel_detected = True
                            detected_reason = "pr_closed_during_run"
                        else:
                            pr_head_sha_now = pr_state_now.get("head_sha")
                            if isinstance(pr_head_sha_now, str):
                                pr_head_sha_now = pr_head_sha_now.strip() or None
                            else:
                                pr_head_sha_now = None
                            if sha and pr_head_sha_now and pr_head_sha_now != sha:
                                cancel_detected = True
                                detected_reason = "superseded_by_new_commit"
                                detected_superseding_sha = pr_head_sha_now

                        if cancel_detected:
                            cancelled_due_to_pr_state = True
                            cancel_reason = detected_reason
                            pointer_promotion_allowed = False
                            superseded_by_sha = detected_superseding_sha
                            cancelled_at = _now_iso()
                            if cancel_reason == "superseded_by_new_commit":
                                pass
                            else:
                                pass
                            try:
                                current_status = status_file.read_status(bucket, runtime_prefix, run_id)
                                if current_status:
                                    current_status["vm_state"] = (
                                        "cancelled_pr_closed_during_run"
                                        if cancel_reason == "pr_closed_during_run"
                                        else "cancelled_superseded_by_new_commit"
                                    )
                                    current_status["run_outcome"] = "cancelled"
                                    current_status["cancel_reason"] = cancel_reason
                                    current_status["cancelled_at"] = cancelled_at
                                    current_status["last_heartbeat"] = cancelled_at
                                    current_status["elapsed_sec"] = int(time.monotonic() - start_timestamp)
                                    current_status["current_leg"] = None
                                    current_status["superseded_by_sha"] = superseded_by_sha
                                    status_legs = current_status.get("legs")
                                    if isinstance(status_legs, list):
                                        for pending_leg in accepted_exec_legs[exec_idx:]:
                                            rem_idx = int(pending_leg["index"])
                                            if rem_idx < 0 or rem_idx >= len(status_legs):
                                                continue
                                            row = status_legs[rem_idx]
                                            if not isinstance(row, dict):
                                                continue
                                            if row.get("status") in {"pass", "fail", "warning"}:
                                                continue
                                            row["status"] = "skipped"
                                            row["skip_reason"] = cancel_reason
                                            row["completed_at"] = cancelled_at
                                    status_file.write_status(bucket, runtime_prefix, run_id, current_status)
                            except (subprocess.CalledProcessError, OSError, ValueError):
                                pass
                            break

                try:
                    current_status = status_file.read_status(bucket, runtime_prefix, run_id)
                    if current_status:
                        current_status["legs"][status_idx]["status"] = "running"
                        current_status["legs"][status_idx]["skip_reason"] = None
                        current_status["legs"][status_idx]["started_at"] = _now_iso()
                        current_status["current_leg"] = current_status["legs"][status_idx].copy()
                        current_status["elapsed_sec"] = int(time.monotonic() - start_timestamp)
                        current_status["run_outcome"] = "running"
                        current_status["cancel_reason"] = None
                        current_status["cancelled_at"] = None
                        current_status["superseded_by_sha"] = None
                        status_file.write_status(bucket, runtime_prefix, run_id, current_status)
                except (subprocess.CalledProcessError, OSError, ValueError):
                    pass

                trigger = {
                    "bucket": bucket,
                    "project": str(leg.get("project", "?")),
                    "bmt_id": str(leg.get("bmt_id", "?")),
                    "run_context": run_context,
                    "run_id": str(leg.get("run_id", "?")),
                    "leg_index": status_idx,
                    "workflow_run_id": workflow_run_id,
                }
                leg_start_time = time.monotonic()
                exit_code = _run_orchestrator(orchestrator_path, trigger, workspace_root)
                leg_duration = int(time.monotonic() - leg_start_time)
                state = "PASS" if exit_code == 0 else "FAIL"
                run_root = _latest_run_root(workspace_root, trigger["project"], trigger["bmt_id"])
                summary = _load_manager_summary(run_root)
                leg_summaries.append(summary)
                accepted_completed += 1

                try:
                    current_status = status_file.read_status(bucket, runtime_prefix, run_id)
                    if current_status:
                        leg_status = "pass" if exit_code == 0 else "fail"
                        current_status["legs"][status_idx]["status"] = leg_status
                        current_status["legs"][status_idx]["skip_reason"] = None
                        current_status["legs"][status_idx]["completed_at"] = _now_iso()
                        current_status["legs"][status_idx]["duration_sec"] = leg_duration

                        if summary:
                            bmt_results = summary.get("bmt_results", {})
                            results = bmt_results.get("results", [])
                            current_status["legs"][status_idx]["files_total"] = len(results)
                            current_status["legs"][status_idx]["files_completed"] = len(results)

                            orchestration_timing = summary.get("orchestration_timing", {})
                            if "duration_sec" in orchestration_timing:
                                current_status["legs"][status_idx]["duration_sec"] = orchestration_timing[
                                    "duration_sec"
                                ]

                        current_status["legs_completed"] = accepted_completed
                        current_status["elapsed_sec"] = int(time.monotonic() - start_timestamp)

                        if exec_idx + 1 < accepted_leg_count:
                            next_idx = int(accepted_exec_legs[exec_idx + 1]["index"])
                            current_status["current_leg"] = current_status["legs"][next_idx].copy()
                        else:
                            current_status["current_leg"] = None

                        status_file.write_status(bucket, runtime_prefix, run_id, current_status)

                        if check_run_id and repository and sha and github_token:
                            _, github_token = _update_check_run_resilient(
                                github_token,
                                repository,
                                check_run_id,
                                token_resolver=github_token_resolver,
                                output={
                                    "title": f"BMT Progress: {accepted_completed}/{accepted_leg_count} tasks complete",
                                    "summary": github_checks.render_progress_markdown(
                                        current_status["legs"],
                                        elapsed_sec=current_status["elapsed_sec"],
                                        eta_sec=current_status.get("eta_sec"),
                                    ),
                                },
                                attempts=2,
                            )
                except (subprocess.CalledProcessError, OSError, ValueError):
                    pass

            if cancelled_due_to_pr_state:
                cancelled_at = _now_iso()
                _stop_heartbeat_thread()
                _stop_progress_thread()
                try:
                    final_status = status_file.read_status(bucket, runtime_prefix, run_id)
                    if final_status:
                        final_status["vm_state"] = (
                            "cancelled_pr_closed_during_run"
                            if cancel_reason == "pr_closed_during_run"
                            else "cancelled_superseded_by_new_commit"
                        )
                        final_status["run_outcome"] = "cancelled"
                        final_status["cancel_reason"] = cancel_reason or "pr_closed_during_run"
                        final_status["cancelled_at"] = final_status.get("cancelled_at") or cancelled_at
                        final_status["last_heartbeat"] = cancelled_at
                        final_status["elapsed_sec"] = int(time.monotonic() - start_timestamp)
                        final_status["current_leg"] = None
                        final_status["superseded_by_sha"] = superseded_by_sha
                        status_file.write_status(bucket, runtime_prefix, run_id, final_status)
                        with contextlib.suppress(subprocess.CalledProcessError, OSError, ValueError):
                            status_file.write_last_run_duration(bucket, runtime_prefix, final_status["elapsed_sec"])
                except (subprocess.CalledProcessError, OSError, ValueError):
                    pass

                if repository and sha and github_token:
                    check_summary = "Tests cancelled: pull request was closed."
                    if cancel_reason == "superseded_by_new_commit":
                        short_new = _short_sha(superseded_by_sha or "")
                        check_summary = f"Tests cancelled: superseded by newer commit ({short_new})."
                    check_run_id, github_token, check_completed = _finalize_check_run_resilient(
                        token=github_token,
                        repository=repository,
                        sha=sha,
                        status_context=runtime_status_context,
                        check_run_id=check_run_id,
                        conclusion="neutral",
                        output={
                            "title": "BMT Cancelled",
                            "summary": check_summary,
                        },
                        token_resolver=github_token_resolver,
                    )
                    if check_completed:
                        pass

                if repository and sha and github_token:
                    cancel_description = "Tests cancelled: pull request was closed."
                    if cancel_reason == "superseded_by_new_commit":
                        cancel_description = "Tests cancelled: superseded by a newer commit."
                    _post_commit_status_resilient(
                        repository,
                        sha,
                        "error",
                        cancel_description,
                        None,
                        github_token,
                        context=gate_status_context,
                        token_resolver=github_token_resolver,
                    )
                if cancel_reason == "superseded_by_new_commit":
                    _upsert_pr_comment(
                        result="⏭️ Run superseded",
                        summary_line="A newer commit was pushed — this run was cancelled.",
                        details_line="",
                        superseding_sha=superseded_by_sha,
                    )
                else:
                    pass
                return False

            state, description = _aggregate_verdicts_from_summaries(leg_summaries)

            _stop_heartbeat_thread()
            _stop_progress_thread()
            try:
                final_status = status_file.read_status(bucket, runtime_prefix, run_id)
                if final_status:
                    final_status["vm_state"] = "completed"
                    final_status["run_outcome"] = "completed"
                    final_status["cancel_reason"] = None
                    final_status["cancelled_at"] = None
                    final_status["superseded_by_sha"] = None
                    final_status["last_heartbeat"] = _now_iso()
                    final_status["elapsed_sec"] = int(time.monotonic() - start_timestamp)
                    status_file.write_status(bucket, runtime_prefix, run_id, final_status)
                    with contextlib.suppress(subprocess.CalledProcessError, OSError, ValueError):
                        status_file.write_last_run_duration(bucket, runtime_prefix, final_status["elapsed_sec"])
            except (subprocess.CalledProcessError, OSError, ValueError):
                pass

            log_dump_url_final: str | None = None
            if state == "failure":
                failed_runner_legs = [
                    s
                    for s in leg_summaries
                    if s and (s.get("reason_code") or "") in ("runner_failures", "runner_timeout")
                ]
                if failed_runner_legs:
                    try:
                        content_parts = [log_config.get_recent_log_content(workspace_root, include_orchestrator=True)]
                        for summary in failed_runner_legs:
                            proj = (summary.get("project_id") or summary.get("project") or "?").strip()
                            bid = (summary.get("bmt_id") or "?").strip()
                            run_root = _latest_run_root(workspace_root, proj, bid)
                            if run_root is not None:
                                log_config._append_runner_log_tail(run_root, content_parts)
                        content_final = "\n".join(content_parts)
                        if len(content_final.encode("utf-8")) > log_config.DUMP_TOTAL_MAX_BYTES:
                            content_final = content_final.encode("utf-8")[: log_config.DUMP_TOTAL_MAX_BYTES].decode(
                                "utf-8", errors="replace"
                            )
                        suffix_final = f"run_{run_id}_fail_{_now_iso().replace(':', '-').replace('.', '-')}"
                        if log_config.dump_logs_to_gcs(bucket, runtime_bucket_root, suffix_final, content_final):
                            info_final = log_config.log_dump_object_info(bucket, runtime_bucket_root, suffix_final)
                            if info_final:
                                log_dump_url_final = generate_signed_url(info_final[0], info_final[1])
                    except Exception:
                        pass

            if repository and sha and github_token:
                conclusion = "success" if state == "success" else "failure"
                check_run_id, github_token, check_completed = _finalize_check_run_resilient(
                    token=github_token,
                    repository=repository,
                    sha=sha,
                    status_context=runtime_status_context,
                    check_run_id=check_run_id,
                    conclusion=conclusion,
                    output={
                        "title": f"BMT Complete: {'PASS' if state == 'success' else 'FAIL'}",
                        "summary": github_checks.render_results_table(
                            [s for s in leg_summaries if s is not None],
                            {
                                "state": "PASS" if state == "success" else "FAIL",
                                "decision": state,
                                "reasons": [],
                            },
                            run_id=run_id,
                            runtime_bucket_root=runtime_bucket_root,
                            log_dump_url=log_dump_url_final,
                        ),
                    },
                    token_resolver=github_token_resolver,
                )
                if check_completed:
                    pass
                else:
                    pass

            if pointer_promotion_allowed:
                for summary in leg_summaries:
                    if summary is not None:
                        _update_pointer_and_cleanup(runtime_bucket_root, summary)

            if repository and sha and github_token:
                if _post_commit_status_resilient(
                    repository,
                    sha,
                    state,
                    description,
                    None,
                    github_token,
                    context=gate_status_context,
                    token_resolver=github_token_resolver,
                ):
                    pass
                else:
                    pass
                if pr_number is not None:
                    details = "For details, open the **Checks** tab on this PR."
                    if state == "success":
                        _upsert_pr_comment(
                            result="✅ Tests passed",
                            summary_line="All test suites passed.",
                            details_line="",
                        )
                    else:
                        if log_dump_url_final:
                            details += f"\n\nLog dump (link expires in 3 days): {log_dump_url_final}"
                            if failed_runner_legs:
                                details = (
                                    "kardome_runner failed. Log dump includes runner output for failed files. "
                                    + details
                                )
                        _upsert_pr_comment(
                            result="❌ Tests failed",
                            summary_line=_failed_legs_display(leg_summaries),
                            details_line=details,
                        )
            return True
        except Exception as exc:
            traceback.print_exc()
            _stop_heartbeat_thread()
            _stop_progress_thread()
            log_dump_url_inner: str | None = None
            try:
                content_inner = log_config.get_recent_log_content(workspace_root, include_orchestrator=True)
                suffix_inner = f"run_{run_id}_crash_{_now_iso().replace(':', '-').replace('.', '-')}"
                if log_config.dump_logs_to_gcs(bucket, runtime_bucket_root, suffix_inner, content_inner):
                    info = log_config.log_dump_object_info(bucket, runtime_bucket_root, suffix_inner)
                    if info:
                        log_dump_url_inner = generate_signed_url(info[0], info[1])
            except Exception:
                pass
            try:
                failed_at = _now_iso()
                failed_status = status_file.read_status(bucket, runtime_prefix, run_id)
                if failed_status:
                    failed_status["vm_state"] = "failed"
                    failed_status["run_outcome"] = "failed"
                    failed_status["cancel_reason"] = None
                    failed_status["cancelled_at"] = None
                    failed_status["superseded_by_sha"] = None
                    failed_status["current_leg"] = None
                    failed_status["last_heartbeat"] = failed_at
                    failed_status["elapsed_sec"] = int(time.monotonic() - start_timestamp)
                    errors = failed_status.get("errors")
                    if not isinstance(errors, list):
                        errors = []
                    errors.append({"at": failed_at, "message": f"Unhandled error: {exc!s}"})
                    failed_status["errors"] = errors
                    status_file.write_status(bucket, runtime_prefix, run_id, failed_status)
            except (subprocess.CalledProcessError, OSError, ValueError):
                pass
            if repository and sha and github_token:
                _post_commit_status_resilient(
                    repository,
                    sha,
                    "failure",
                    f"Runner error: {exc!s}"[:140],
                    None,
                    github_token,
                    context=gate_status_context,
                    token_resolver=github_token_resolver,
                )
                out_summary_inner = f"Unhandled error: {exc!s}"
                if log_dump_url_inner:
                    out_summary_inner += f"\n\nLog dump (link expires in 3 days): {log_dump_url_inner}"
                check_run_id, github_token, check_completed = _finalize_check_run_resilient(
                    token=github_token,
                    repository=repository,
                    sha=sha,
                    status_context=runtime_status_context,
                    check_run_id=check_run_id,
                    conclusion="failure",
                    output={
                        "title": "BMT VM Error",
                        "summary": out_summary_inner,
                    },
                    token_resolver=github_token_resolver,
                )
                if not check_completed:
                    pass
                if pr_number is not None:
                    details_inner = "For details, open the **Checks** tab on this PR."
                    if log_dump_url_inner:
                        details_inner += f"\n\nLog dump (link expires in 3 days): {log_dump_url_inner}"
                    _upsert_pr_comment(
                        result="❌ BMT failed",
                        summary_line="The test runner hit an error. See the Checks tab for details.",
                        details_line=details_inner,
                    )
            return False
    except Exception as exc:
        log = logging.getLogger(log_config.VM_WATCHER_LOGGER_NAME)
        log.exception("Unhandled exception in run trigger processing")
        log_dump_url: str | None = None
        try:
            content = log_config.get_recent_log_content(workspace_root, include_orchestrator=True)
            suffix = f"run_{run_id}_crash_{_now_iso().replace(':', '-').replace('.', '-')}"
            if log_config.dump_logs_to_gcs(bucket, runtime_bucket_root, suffix, content):
                info = log_config.log_dump_object_info(bucket, runtime_bucket_root, suffix)
                if info:
                    log_dump_url = generate_signed_url(info[0], info[1])
        except Exception:
            pass
        if repository and sha and github_token:
            _post_commit_status_resilient(
                repository,
                sha,
                "failure",
                f"Runner error: {exc!s}"[:140],
                None,
                github_token,
                context=gate_status_context,
                token_resolver=github_token_resolver,
            )
            out_summary = f"Unhandled error: {exc!s}"
            if log_dump_url:
                out_summary += f"\n\nLog dump (link expires in 3 days): {log_dump_url}"
            check_run_id, github_token, check_completed = _finalize_check_run_resilient(
                token=github_token,
                repository=repository,
                sha=sha,
                status_context=runtime_status_context,
                check_run_id=check_run_id,
                conclusion="failure",
                output={
                    "title": "BMT VM Error",
                    "summary": out_summary,
                },
                token_resolver=github_token_resolver,
            )
            if not check_completed:
                pass
            if pr_number is not None:
                details = "For details, open the **Checks** tab on this PR."
                if log_dump_url:
                    details += f"\n\nLog dump (link expires in 3 days): {log_dump_url}"
                _upsert_pr_comment(
                    result="❌ BMT failed",
                    summary_line="The test runner hit an error. See the Checks tab for details.",
                    details_line=details,
                )
        return False
    finally:
        _stop_heartbeat_thread()
        _stop_progress_thread()
        _gcloud_rm(run_trigger_uri)
        _cleanup_workflow_artifacts(
            runtime_bucket_root=runtime_bucket_root,
            keep_workflow_ids={workflow_run_id_str},
        )
        _prune_workspace_runs(workspace_root, keep_recent_per_bmt=_KEEP_RECENT_LOCAL_RUNS)


def _handle_one_pubsub_message(
    *,
    subscriber: Any,
    subscription_path: str,
    received_msg: Any,
    code_bucket_root: str,
    runtime_bucket_root: str,
    workspace_root: Path,
    github_token_resolver: Callable[[str], str | None],
    exit_after_run: bool,
    idle_timeout_sec: int,
) -> bool:
    """Process one Pub/Sub message; ack or nack. Returns True if caller should exit now (exit_after_run and consumed and no idle window)."""
    ack_id = received_msg.ack_id
    try:
        payload = json.loads(received_msg.message.data.decode("utf-8"))
    except (json.JSONDecodeError, ValueError):
        subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": [ack_id]})
        return False
    bucket = (
        str(payload.get("bucket", "")).strip() or runtime_bucket_root.split("gs://", 1)[-1].split("/", maxsplit=1)[0]
    )
    run_id = str(payload.get("workflow_run_id", "")).strip()
    if not run_id:
        subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": [ack_id]})
        return False
    trigger_uri = f"gs://{bucket}/triggers/runs/{run_id}.json"
    trigger_consumed = _process_run_trigger(
        trigger_uri,
        code_bucket_root,
        runtime_bucket_root,
        workspace_root,
        github_token_resolver,
    )
    if trigger_consumed:
        subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": [ack_id]})
        return exit_after_run and idle_timeout_sec <= 0
    subscriber.modify_ack_deadline(
        request={"subscription": subscription_path, "ack_ids": [ack_id], "ack_deadline_seconds": 0}
    )
    return False


def _run_pubsub_loop(
    *,
    subscription_path: str,
    code_bucket_root: str,
    runtime_bucket_root: str,
    workspace_root: Path,
    github_token_resolver: Callable[[str], str | None],
    exit_after_run: bool,
    idle_timeout_sec: int,
) -> int:
    """Pull triggers from a Pub/Sub subscription instead of polling GCS.

    The CI writes the trigger payload to GCS AND publishes the same JSON to
    the Pub/Sub topic. The VM receives messages instantly (no polling lag),
    uses the GCS trigger URI reconstructed from the payload, and acks only
    after the trigger is fully consumed. Nacks cause Pub/Sub to redeliver.
    """
    from google.cloud import pubsub_v1

    subscriber = pubsub_v1.SubscriberClient()
    idle_deadline = time.monotonic() + idle_timeout_sec if (exit_after_run and idle_timeout_sec > 0) else None

    while not _shutdown_holder[0]:
        try:
            response = subscriber.pull(
                request={"subscription": subscription_path, "max_messages": 1},
                timeout=HTTP_TIMEOUT,
            )
        except Exception:
            time.sleep(5)
            continue

        if not response.received_messages:
            if idle_deadline is not None and time.monotonic() >= idle_deadline:
                return 0
            continue

        idle_deadline = None  # reset once a message arrives

        for received_msg in response.received_messages:
            if _shutdown_holder[0]:
                break
            exit_now = _handle_one_pubsub_message(
                subscriber=subscriber,
                subscription_path=subscription_path,
                received_msg=received_msg,
                code_bucket_root=code_bucket_root,
                runtime_bucket_root=runtime_bucket_root,
                workspace_root=workspace_root,
                github_token_resolver=github_token_resolver,
                exit_after_run=exit_after_run,
                idle_timeout_sec=idle_timeout_sec,
            )
            if exit_now:
                return 0
            if exit_after_run and idle_timeout_sec > 0:
                idle_deadline = time.monotonic() + idle_timeout_sec

    return 0


def main() -> int:
    args = parse_args()
    workspace_root = _resolve_workspace_root(args.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    log_config.configure_vm_watcher_logging(workspace_root)

    code_bucket_root = _code_bucket_root(args.bucket)
    runtime_bucket_root = _runtime_bucket_root(args.bucket)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    exit_after_run = getattr(args, "exit_after_run", False)
    idle_timeout_sec = getattr(args, "idle_timeout_sec", 0)

    # Use GitHub App auth module for per-repository token resolution
    github_token_resolver = github_auth.resolve_auth_for_repository

    enabled_repositories = github_auth.list_enabled_repositories()
    if enabled_repositories is None:
        return 2
    if not enabled_repositories:
        pass
    else:
        pass

    # Startup sweep: enforce bounded retention even after prior failed runs.
    _prune_workspace_runs(workspace_root, keep_recent_per_bmt=_KEEP_RECENT_LOCAL_RUNS)
    _cleanup_workflow_artifacts(
        runtime_bucket_root=runtime_bucket_root,
        keep_workflow_ids=set(),
    )

    subscription = getattr(args, "subscription", "").strip()
    gcp_project = getattr(args, "gcp_project", "").strip() or os.environ.get("GCP_PROJECT", "")

    if subscription:
        if not gcp_project:
            return 1
        subscription_path = f"projects/{gcp_project}/subscriptions/{subscription}"
        return _run_pubsub_loop(
            subscription_path=subscription_path,
            code_bucket_root=code_bucket_root,
            runtime_bucket_root=runtime_bucket_root,
            workspace_root=workspace_root,
            github_token_resolver=github_token_resolver,
            exit_after_run=exit_after_run,
            idle_timeout_sec=idle_timeout_sec,
        )

    return _run_gcs_poll_loop(
        args=args,
        code_bucket_root=code_bucket_root,
        runtime_bucket_root=runtime_bucket_root,
        workspace_root=workspace_root,
        github_token_resolver=github_token_resolver,
        exit_after_run=exit_after_run,
        idle_timeout_sec=idle_timeout_sec,
    )


def _run_gcs_poll_loop(
    *,
    args: argparse.Namespace,
    code_bucket_root: str,
    runtime_bucket_root: str,
    workspace_root: Path,
    github_token_resolver: Callable[[str], str | None],
    exit_after_run: bool,
    idle_timeout_sec: int,
) -> int:
    poll_log = logging.getLogger(log_config.VM_WATCHER_LOGGER_NAME)
    idle_deadline = time.monotonic() + idle_timeout_sec if (exit_after_run and idle_timeout_sec > 0) else None
    while not _shutdown_holder[0]:
        run_trigger_uris = _discover_run_triggers(runtime_bucket_root)
        if run_trigger_uris:
            idle_deadline = None
            poll_log.info("Discovered %d run trigger(s)", len(run_trigger_uris))
            for run_trigger_uri in run_trigger_uris:
                if _shutdown_holder[0]:
                    break
                trigger_consumed = _process_run_trigger(
                    run_trigger_uri,
                    code_bucket_root,
                    runtime_bucket_root,
                    workspace_root,
                    github_token_resolver,
                )
                if exit_after_run and trigger_consumed:
                    if idle_timeout_sec > 0:
                        idle_deadline = time.monotonic() + idle_timeout_sec
                    else:
                        return 0
            log_config.process_log_dump_requests(args.bucket, runtime_bucket_root, workspace_root)
        elif idle_deadline is not None and time.monotonic() >= idle_deadline:
            return 0
        else:
            log_config.process_log_dump_requests(args.bucket, runtime_bucket_root, workspace_root)
        if not _shutdown_holder[0]:
            time.sleep(args.poll_interval_sec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
