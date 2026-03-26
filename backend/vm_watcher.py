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
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from google.api_core import exceptions as gcs_exceptions
from google.cloud import storage as gcs_lib
from whenever import Instant


def _get_bmt_config_defaults() -> tuple[int, int, int]:
    try:
        import config.bmt_config as _m
    except ImportError:
        import backend.config.bmt_config as _m
    return (
        int(_m.IDLE_TIMEOUT_SEC),
        int(_m.STALE_TRIGGER_AGE_HOURS),
        int(_m.TRIGGER_METADATA_KEEP_RECENT),
    )


_idle_sec_val, _stale_hours_val, _keep_recent_val = _get_bmt_config_defaults()
try:
    from config.bmt_config import DEFAULT_RUNTIME_CONTEXT, BmtConfig, get_config
    from utils import _bucket_uri, _code_bucket_root, _now_iso, _runtime_bucket_root

    from backend.config.constants import EXECUTABLE_MODE, GITHUB_API_VERSION, HTTP_TIMEOUT

    from .github import (
        github_auth,
        github_checks,
        github_pr_comment,
        github_pull_request,
        status_file,
    )
except ImportError:
    from backend.config.bmt_config import DEFAULT_RUNTIME_CONTEXT, BmtConfig, get_config
    from backend.config.constants import EXECUTABLE_MODE, GITHUB_API_VERSION, HTTP_TIMEOUT
    from backend.github import (
        github_auth,
        github_checks,
        github_pr_comment,
        github_pull_request,
        status_file,
    )
    from backend.utils import _bucket_uri, _code_bucket_root, _now_iso, _runtime_bucket_root

IDLE_TIMEOUT_DEFAULT = _idle_sec_val
STALE_TRIGGER_AGE_HOURS_DEFAULT = _stale_hours_val
KEEP_RECENT_DEFAULT = _keep_recent_val

_shutdown = False
_KEEP_RECENT_LOCAL_RUNS = 2

# Fallback when trigger payload omits contexts; single source of truth backend/config/bmt_config.py
DEFAULT_STATUS_CONTEXT: str = BmtConfig().bmt_status_context
DEFAULT_RUNTIME_STATUS_CONTEXT: str = DEFAULT_RUNTIME_CONTEXT
PROJECT_WIDE_BMT_IDS = frozenset({"", "*", "__all__", "all", "project_all", "__project_wide__"})


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


def _handle_signal(_signum: int, _frame: Any) -> None:
    global _shutdown
    _shutdown = True


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


_gcs_client: gcs_lib.Client | None = None


def _get_gcs_client() -> gcs_lib.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = gcs_lib.Client()
    return _gcs_client


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    """Parse 'gs://bucket/path/to/blob' → ('bucket', 'path/to/blob')."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a GCS URI: {uri}")
    parts = uri[5:].split("/", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _gcs_list(uri: str) -> list[str]:
    """List all objects under a GCS URI prefix. Returns full gs:// URIs."""
    bucket_name, prefix = _parse_gcs_uri(uri)
    try:
        blobs = _get_gcs_client().list_blobs(bucket_name, prefix=prefix)
        return [f"gs://{bucket_name}/{b.name}" for b in blobs]
    except (gcs_exceptions.GoogleAPICallError, OSError):
        return []


def _gcloud_ls(uri: str, *, recursive: bool = False) -> list[str]:  # noqa: ARG001 (recursive ignored; SDK always recurses)
    """List objects under a GCS URI prefix. Returns list of full URIs."""
    return _gcs_list(uri)


def _gcloud_download_json(uri: str) -> tuple[dict[str, Any] | None, str | None]:
    """Download a JSON object from GCS.

    Returns:
      (payload, None) on success.
      (None, "download_failed") on 404 or transient download failures.
      (None, "invalid_json") when object exists but payload is malformed.
    """
    bucket_name, blob_name = _parse_gcs_uri(uri)
    try:
        blob = _get_gcs_client().bucket(bucket_name).blob(blob_name)
        text = blob.download_as_text(encoding="utf-8")
    except gcs_exceptions.NotFound:
        return None, "download_failed"
    except (gcs_exceptions.GoogleAPICallError, OSError):
        traceback.print_exc()
        raise
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "invalid_json"
    return payload, None


def _gcloud_upload_json(uri: str, payload: dict[str, Any]) -> bool:
    """Upload a JSON object to GCS. Returns True on success."""
    bucket_name, blob_name = _parse_gcs_uri(uri)
    try:
        blob = _get_gcs_client().bucket(bucket_name).blob(blob_name)
        blob.upload_from_string(
            json.dumps(payload, indent=2) + "\n",
            content_type="application/json",
        )
        return True
    except (gcs_exceptions.GoogleAPICallError, OSError):
        traceback.print_exc()
        return False


def _gcloud_rm(uri: str, *, recursive: bool = False) -> bool:
    """Delete a GCS object or all objects under a prefix."""
    bucket_name, blob_name = _parse_gcs_uri(uri)
    client = _get_gcs_client()
    try:
        if recursive:
            blobs = list(client.list_blobs(bucket_name, prefix=blob_name))
            if blobs:
                with client.batch():
                    for blob in blobs:
                        blob.delete()
        else:
            client.bucket(bucket_name).blob(blob_name).delete()
        return True
    except gcs_exceptions.NotFound:
        return True  # already gone
    except (gcs_exceptions.GoogleAPICallError, OSError):
        return False


def _gcloud_exists(uri: str) -> bool:
    """Return True when a GCS object exists."""
    bucket_name, blob_name = _parse_gcs_uri(uri)
    try:
        return _get_gcs_client().bucket(bucket_name).blob(blob_name).exists()
    except (gcs_exceptions.GoogleAPICallError, OSError):
        return False


def _load_jobs_config_from_gcs(code_bucket_root: str, project: str) -> tuple[dict[str, Any] | None, str | None]:
    """Load per-project jobs config from code bucket.

    Returns (payload, error_reason_code).
    """
    jobs_uri = _bucket_uri(code_bucket_root, f"projects/{project}/bmt_jobs.json")
    result, err = _gcloud_download_json(jobs_uri)
    if result is None:
        reason = "jobs_schema_invalid" if err == "invalid_json" else "jobs_config_missing"
        return None, reason
    if not isinstance(result.get("bmts"), dict):
        return None, "jobs_schema_invalid"
    return result, None


_RUN_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_run_token(raw: str) -> str:
    token = _RUN_ID_SAFE.sub("-", raw.strip())
    token = token.strip("-._")
    return token or "bmt"


def _derive_leg_run_id(base_run_id: str, bmt_id: str, used: set[str]) -> str:
    """Build a deterministic unique run_id for one expanded BMT leg."""
    base = _safe_run_token(base_run_id) if base_run_id.strip() else "leg"
    suffix = _safe_run_token(bmt_id) if bmt_id.strip() else "bmt"
    candidate = f"{base}-{suffix}"
    if candidate not in used:
        used.add(candidate)
        return candidate
    idx = 2
    while True:
        alt = f"{candidate}-{idx}"
        if alt not in used:
            used.add(alt)
            return alt
        idx += 1


def _append_resolved_leg(
    requested_legs: list[dict[str, Any]],
    *,
    project: str,
    bmt_id: str,
    run_id: str,
    reason: str | None,
) -> None:
    decision = "accepted" if reason is None else "rejected"
    requested_legs.append(
        {
            "index": len(requested_legs),
            "project": project,
            "bmt_id": bmt_id,
            "run_id": run_id,
            "decision": decision,
            "reason": reason,
        }
    )


def _resolve_requested_legs(
    *,
    legs_raw: list[Any],
    code_bucket_root: str,
) -> list[dict[str, Any]]:
    """Resolve requested legs against VM runtime support by convention files.

    Supports project-wide request legs (request_scope=project_wide or bmt_id sentinel),
    expanding each project into all BMT entries from jobs config.
    """
    requested_legs: list[dict[str, Any]] = []
    manager_exists_cache: dict[str, bool] = {}
    jobs_cache: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
    used_run_ids: set[str] = set()

    for raw_idx, leg in enumerate(legs_raw):
        project = "?"
        bmt_id_raw = ""
        run_id_base = ""

        if not isinstance(leg, dict):
            _append_resolved_leg(
                requested_legs,
                project=project,
                bmt_id="?",
                run_id=f"leg-{raw_idx + 1}",
                reason="invalid_leg_type",
            )
            continue

        project = str(leg.get("project", "")).strip() or "?"
        bmt_id_raw = str(leg.get("bmt_id", "")).strip()
        run_id_base = str(leg.get("run_id", "")).strip() or f"leg-{raw_idx + 1}-{project}"
        request_scope = str(leg.get("request_scope", "")).strip().lower()
        project_wide = request_scope == "project_wide" or bmt_id_raw.lower() in PROJECT_WIDE_BMT_IDS

        if project == "?":
            _append_resolved_leg(
                requested_legs,
                project=project,
                bmt_id=(bmt_id_raw or "__all__") if project_wide else (bmt_id_raw or "?"),
                run_id=_derive_leg_run_id(run_id_base, bmt_id_raw or "invalid", used_run_ids),
                reason="invalid_leg_type",
            )
            continue

        if project not in manager_exists_cache:
            manager_uri = _bucket_uri(code_bucket_root, f"projects/{project}/bmt_manager.py")
            manager_exists_cache[project] = _gcloud_exists(manager_uri)
        if not manager_exists_cache[project]:
            _append_resolved_leg(
                requested_legs,
                project=project,
                bmt_id=(bmt_id_raw or "__all__") if project_wide else (bmt_id_raw or "?"),
                run_id=_derive_leg_run_id(run_id_base, bmt_id_raw or "manager-missing", used_run_ids),
                reason="manager_missing",
            )
            continue

        if project not in jobs_cache:
            jobs_cache[project] = _load_jobs_config_from_gcs(code_bucket_root, project)
        jobs_payload, jobs_error = jobs_cache[project]
        if jobs_error is not None or jobs_payload is None:
            _append_resolved_leg(
                requested_legs,
                project=project,
                bmt_id=(bmt_id_raw or "__all__") if project_wide else (bmt_id_raw or "?"),
                run_id=_derive_leg_run_id(run_id_base, bmt_id_raw or "jobs-error", used_run_ids),
                reason=jobs_error or "jobs_schema_invalid",
            )
            continue

        bmts = jobs_payload.get("bmts")
        if not isinstance(bmts, dict):
            _append_resolved_leg(
                requested_legs,
                project=project,
                bmt_id=(bmt_id_raw or "__all__") if project_wide else (bmt_id_raw or "?"),
                run_id=_derive_leg_run_id(run_id_base, bmt_id_raw or "jobs-schema", used_run_ids),
                reason="jobs_schema_invalid",
            )
            continue

        if project_wide:
            if not bmts:
                _append_resolved_leg(
                    requested_legs,
                    project=project,
                    bmt_id="?",
                    run_id=_derive_leg_run_id(run_id_base, "empty-project", used_run_ids),
                    reason="bmt_not_defined",
                )
                continue

            for bmt_id_key in sorted(bmts):
                bmt_id = str(bmt_id_key).strip() or "?"
                run_id = _derive_leg_run_id(run_id_base, bmt_id, used_run_ids)
                bmt_cfg = bmts.get(bmt_id_key)
                if not isinstance(bmt_cfg, dict):
                    reason = "jobs_schema_invalid"
                elif bmt_cfg.get("enabled", True) is False:
                    reason = "bmt_disabled"
                else:
                    reason = None
                _append_resolved_leg(
                    requested_legs,
                    project=project,
                    bmt_id=bmt_id,
                    run_id=run_id,
                    reason=reason,
                )
            continue

        bmt_id = bmt_id_raw or "?"
        run_id = _derive_leg_run_id(run_id_base, bmt_id, used_run_ids)
        bmt_cfg = bmts.get(bmt_id)
        if not isinstance(bmt_cfg, dict):
            reason = "bmt_not_defined"
        elif bmt_cfg.get("enabled", True) is False:
            reason = "bmt_disabled"
        else:
            reason = None
        _append_resolved_leg(
            requested_legs,
            project=project,
            bmt_id=bmt_id,
            run_id=run_id,
            reason=reason,
        )

    return requested_legs


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


def _discover_run_triggers(runtime_bucket_root: str) -> list[str]:
    """List run trigger JSON files under triggers/runs/."""
    runs_uri = _bucket_uri(runtime_bucket_root, "triggers/runs/")
    all_objects = _gcloud_ls(runs_uri)
    return [uri for uri in all_objects if uri.endswith(".json")]


def _run_handshake_uri_from_trigger_uri(run_trigger_uri: str) -> str:
    """Map triggers/runs/<id>.json -> triggers/acks/<id>.json."""
    return run_trigger_uri.replace("/triggers/runs/", "/triggers/acks/", 1)


def _post_commit_status(
    repository: str,
    sha: str,
    state: str,
    description: str,
    target_url: str | None,
    token: str,
    context: str = DEFAULT_STATUS_CONTEXT,
) -> bool:
    """Post a commit status to GitHub. state: pending|success|failure|error."""
    if not token or not repository or not sha:
        return False
    owner, _, repo = repository.partition("/")
    if not repo:
        return False
    url = f"https://api.github.com/repos/{owner}/{repo}/statuses/{sha}"
    body = {
        "state": state,
        "context": (context or DEFAULT_STATUS_CONTEXT).strip() or DEFAULT_STATUS_CONTEXT,
        "description": description[:140],
    }
    if target_url:
        body["target_url"] = target_url
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return False


def _with_refreshed_token(
    repository: str,
    token_resolver: Callable[[str], str | None],
    current_token: str,
) -> str:
    """Try resolving a fresh token; fall back to current token on failure."""
    refreshed = token_resolver(repository)
    if refreshed:
        return refreshed
    return current_token


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
    """Post commit status with token refresh retries for transient auth/API issues."""
    token_in_use = token
    max_attempts = max(1, attempts)
    for attempt in range(1, max_attempts + 1):
        if _post_commit_status(repository, sha, state, description, target_url, token_in_use, context=context):
            return True
        if attempt < max_attempts:
            token_in_use = _with_refreshed_token(repository, token_resolver, token_in_use)
    return False


def _create_check_run_resilient(
    token: str,
    repository: str,
    sha: str,
    *,
    name: str,
    status: str,
    output: dict[str, Any],
    token_resolver: Callable[[str], str | None],
    attempts: int = 3,
) -> tuple[int | None, str]:
    """Create check run with token refresh retries. Returns (check_run_id, token_used)."""
    token_in_use = token
    max_attempts = max(1, attempts)
    for attempt in range(1, max_attempts + 1):
        try:
            check_run_id = github_checks.create_check_run(
                token_in_use,
                repository,
                sha,
                name=name,
                status=status,
                output=output,
            )
            return check_run_id, token_in_use
        except (OSError, ValueError, RuntimeError):
            if attempt < max_attempts:
                token_in_use = _with_refreshed_token(repository, token_resolver, token_in_use)
    return None, token_in_use


def _update_check_run_resilient(
    token: str,
    repository: str,
    check_run_id: int,
    *,
    token_resolver: Callable[[str], str | None],
    status: str | None = None,
    conclusion: str | None = None,
    output: dict[str, Any] | None = None,
    attempts: int = 3,
) -> tuple[bool, str]:
    """Update check run with token refresh retries. Returns (updated, token_used)."""
    token_in_use = token
    max_attempts = max(1, attempts)
    for attempt in range(1, max_attempts + 1):
        try:
            github_checks.update_check_run(
                token_in_use,
                repository,
                check_run_id,
                status=status,
                conclusion=conclusion,
                output=output,
            )
            return True, token_in_use
        except (OSError, ValueError, RuntimeError):
            if attempt < max_attempts:
                token_in_use = _with_refreshed_token(repository, token_resolver, token_in_use)
    return False, token_in_use


def _finalize_check_run_resilient(
    *,
    token: str,
    repository: str,
    sha: str,
    status_context: str,
    check_run_id: int | None,
    conclusion: str,
    output: dict[str, Any],
    token_resolver: Callable[[str], str | None],
) -> tuple[int | None, str, bool]:
    """Finalize check run, creating one at completion if initial creation failed."""
    token_in_use = token
    run_id = check_run_id

    if run_id is not None:
        updated, token_in_use = _update_check_run_resilient(
            token_in_use,
            repository,
            run_id,
            token_resolver=token_resolver,
            status="completed",
            conclusion=conclusion,
            output=output,
        )
        return run_id, token_in_use, updated

    created_id, token_in_use = _create_check_run_resilient(
        token_in_use,
        repository,
        sha,
        name=status_context,
        status="in_progress",
        output={
            "title": "BMT Finalizing",
            "summary": "Late-created check run while publishing final BMT result.",
        },
        token_resolver=token_resolver,
    )
    if created_id is None:
        return None, token_in_use, False

    updated, token_in_use = _update_check_run_resilient(
        token_in_use,
        repository,
        created_id,
        token_resolver=token_resolver,
        status="completed",
        conclusion=conclusion,
        output=output,
    )
    return created_id, token_in_use, updated


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


def _run_id_from_json_uri(uri: str) -> str | None:
    """Extract run ID from a trailing `<run_id>.json` object URI."""
    name = uri.rsplit("/", 1)[-1]
    if not name.endswith(".json"):
        return None
    run_id = name[:-5].strip()
    return run_id or None


def _workflow_run_sort_key(run_id: str) -> tuple[int, int | str]:
    """Sort run IDs newest-first by numeric value when possible, else lexicographically."""
    rid = run_id.strip()
    if rid.isdigit():
        return (1, int(rid))
    return (0, rid)


def _trim_trigger_family(
    family_prefix_uri: str,
    *,
    keep_ids: set[str],
    keep_recent: int = _KEEP_RECENT_WORKFLOW_FILES,
) -> None:
    """Prune stale JSON objects in one trigger family and keep only recent + explicit IDs."""
    object_uris = [uri for uri in _gcloud_ls(family_prefix_uri) if uri.endswith(".json")]
    entries: list[tuple[str, str]] = []
    for uri in object_uris:
        run_id = _run_id_from_json_uri(uri)
        if run_id is None:
            continue
        entries.append((run_id, uri))
    if not entries:
        return

    normalized_keep = {rid.strip() for rid in keep_ids if rid and rid.strip()}
    sorted_entries = sorted(entries, key=lambda item: _workflow_run_sort_key(item[0]), reverse=True)
    recent_ids: list[str] = []
    for run_id, _ in sorted_entries:
        if run_id not in recent_ids:
            recent_ids.append(run_id)
        if len(recent_ids) >= max(keep_recent, 0):
            break
    retained_ids = normalized_keep.union(recent_ids)

    deleted = 0
    failed = 0
    for run_id, uri in entries:
        if run_id in retained_ids:
            continue
        if _gcloud_rm(uri):
            deleted += 1
        else:
            failed += 1


def _cleanup_stale_run_triggers(runtime_bucket_root: str) -> None:
    """Delete run triggers older than _STALE_TRIGGER_AGE_HOURS from triggers/runs/."""
    runs_uri = _bucket_uri(runtime_bucket_root, "triggers/runs/")
    trigger_uris = [uri for uri in _gcloud_ls(runs_uri) if uri.endswith(".json")]
    if not trigger_uris:
        return
    cutoff = Instant.now().timestamp() - _STALE_TRIGGER_AGE_HOURS * 3600
    deleted = 0
    for uri in trigger_uris:
        payload, err = _gcloud_download_json(uri)
        if err is not None or payload is None:
            continue
        triggered_at_raw = payload.get("triggered_at")
        if not isinstance(triggered_at_raw, str):
            continue
        try:
            triggered_ts = Instant.parse_iso(triggered_at_raw.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            continue
        if triggered_ts < cutoff and _gcloud_rm(uri):
            deleted += 1
    if deleted:
        pass


def _cleanup_workflow_artifacts(
    *,
    runtime_bucket_root: str,
    keep_workflow_ids: set[str],
) -> None:
    """Keep workflow metadata families bounded to current + previous entries."""
    if not runtime_bucket_root.strip():
        return

    _cleanup_stale_run_triggers(runtime_bucket_root)

    families = [
        _bucket_uri(runtime_bucket_root, "triggers/acks/"),
        _bucket_uri(runtime_bucket_root, "triggers/status/"),
    ]
    seen: set[str] = set()
    for family_uri in families:
        if family_uri in seen:
            continue
        seen.add(family_uri)
        _trim_trigger_family(
            family_uri,
            keep_ids=keep_workflow_ids,
            keep_recent=_KEEP_RECENT_WORKFLOW_FILES,
        )


def _cleanup_legacy_result_history(bucket_root: str, results_prefix: str) -> None:
    """Delete legacy run-history prefixes no longer used by pointer/snapshot flow."""
    clean_prefix = results_prefix.strip("/")
    if not clean_prefix or "/results/" not in clean_prefix:
        return

    before_results, _, bmt_suffix = clean_prefix.partition("/results/")
    if not bmt_suffix:
        return
    base = f"{before_results}/results" if before_results else "results"
    legacy_prefixes = [
        f"{base}/archive",
        f"{base}/logs/{bmt_suffix}",
    ]
    for rel in legacy_prefixes:
        legacy_uri = _bucket_uri(bucket_root, rel)
        if _gcloud_rm(legacy_uri, recursive=True):
            pass


def _load_manager_summary(run_root: Path | None) -> dict[str, Any] | None:
    """Load manager_summary.json from a run root; return None if missing or invalid."""
    if run_root is None:
        return None
    path = run_root / "manager_summary.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _results_prefix_from_ci_verdict_uri(bucket_root: str, ci_verdict_uri: str) -> str | None:
    """Derive results_prefix from manager summary ci_verdict_uri (snapshot path)."""
    uri = (ci_verdict_uri or "").strip()
    if not uri or not uri.startswith("gs://"):
        return None
    # ci_verdict_uri = gs://bucket[/prefix]/results_prefix/snapshots/run_id/ci_verdict.json
    if "/snapshots/" not in uri:
        return None
    prefix = uri.split("/snapshots/")[0]
    # prefix = gs://bucket or gs://bucket/prefix/path
    root = bucket_root.rstrip("/")
    if not prefix.startswith(root):
        return None
    rel = prefix[len(root) :].lstrip("/")
    return rel or None


def _aggregate_verdicts_from_summaries(summaries: list[dict[str, Any] | None]) -> tuple[str, str]:
    """Compute (state, description) from manager summaries. state: success|failure."""
    pass_count = 0
    fail_count = 0
    for summary in summaries:
        if summary is None:
            fail_count += 1
            continue
        status = (summary.get("status") or "").strip().lower()
        if status in ("pass", "warning"):
            pass_count += 1
        else:
            fail_count += 1
    total = len(summaries)
    if fail_count == 0:
        return "success", f"BMT: {pass_count}/{total} passed"
    return "failure", f"BMT: {fail_count}/{total} failed, {pass_count} passed"


def _short_sha(sha: str, *, length: int = 12) -> str:
    """Return short SHA for display while preserving the full hash elsewhere."""
    clean = (sha or "").strip()
    if not clean:
        return "unknown"
    return clean[: max(4, length)]


def _commit_url(repository: str, sha: str, server_url: str = "https://github.com") -> str:
    """Build commit URL when repository and SHA are available."""
    repo = (repository or "").strip()
    clean_sha = (sha or "").strip()
    base = (server_url or "https://github.com").rstrip("/")
    if not repo or not clean_sha:
        return ""
    return f"{base}/{repo}/commit/{clean_sha}"


def _commit_markdown_link(repository: str, sha: str, server_url: str = "https://github.com") -> str:
    """Render commit link markdown with short SHA text."""
    url = _commit_url(repository, sha, server_url)
    short = _short_sha(sha)
    if not url:
        return f"`{short}`"
    return f"[`{short}`]({url})"


def _comment_marker_for_sha(sha: str) -> str:
    """Stable hidden marker used for commit-specific PR comment upsert."""
    return f"<!-- bmt-vm-comment-sha:{(sha or '').strip()} -->"


def _format_bmt_comment(
    result: str,
    summary_line: str,
    details_line: str,
    *,
    repository: str,
    tested_sha: str,
    workflow_run_id: str | int | None,
    pr_number: int | None = None,
    server_url: str = "https://github.com",
    superseding_sha: str | None = None,
) -> str:
    """Build PR comment body with commit linkage and stable marker for upsert.
    Always includes direct links: commit, workflow run, and Checks tab.
    """
    base = (server_url or "https://github.com").rstrip("/")
    commit_link = _commit_markdown_link(repository, tested_sha, server_url)
    workflow_link = ""
    if workflow_run_id is not None:
        run_id_str = str(workflow_run_id).strip()
        if run_id_str:
            workflow_link = f"[Workflow run]({base}/{repository}/actions/runs/{run_id_str})"
    checks_link = f"[Checks tab]({base}/{repository}/commit/{tested_sha}/checks)"
    if pr_number is not None and pr_number > 0:
        checks_link = f"[Checks tab]({base}/{repository}/pull/{pr_number}/checks)"

    link_parts = [commit_link]
    if workflow_link:
        link_parts.append(workflow_link)
    link_parts.append(checks_link)
    links_line = " · ".join(link_parts)

    lines = [
        _comment_marker_for_sha(tested_sha),
        f"## {result}",
        "",
        links_line,
        "",
        summary_line,
    ]
    if details_line:
        lines.extend(["", details_line])
    if superseding_sha:
        lines.extend(["", f"Superseded by {_commit_markdown_link(repository, superseding_sha, server_url)}"])
    return "\n".join(lines)


def _human_readable_bmt_label(bmt_id: str) -> str:
    """Turn bmt_id (e.g. false_reject_namuh) into display text (e.g. False Rejects)."""
    if not bmt_id or bmt_id == "?":
        return bmt_id or "?"
    return bmt_id.replace("_", " ").strip().title()


def _failed_legs_display(summaries: list[dict[str, Any] | None]) -> str:
    """List failed project · BMT in human-readable form for PR comment."""
    parts: list[str] = []
    for summary in summaries or []:
        if summary is None:
            continue
        status = (summary.get("status") or "").strip().lower()
        if status in ("pass", "warning"):
            continue
        project = (summary.get("project_id") or summary.get("project") or "?").strip()
        if project and project != "?":
            project = project.upper() if len(project) <= 3 else project.title()
        bmt_id = (summary.get("bmt_id") or "?").strip()
        bmt_label = _human_readable_bmt_label(bmt_id) if bmt_id != "?" else "?"
        parts.append(f"**{project} · {bmt_label}**")
    if not parts:
        return "One or more test suites did not pass."
    return "Failed: " + "; ".join(parts)


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
                title = f"Running — {legs_done}/{len(legs)} legs complete"
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


def _update_pointer_and_cleanup(
    bucket_root: str,
    summary: dict[str, Any],
) -> None:
    """Update current.json for this leg and delete stale snapshots. No-op if no ci_verdict_uri."""
    ci_verdict_uri = (summary.get("ci_verdict_uri") or "").strip()
    if not ci_verdict_uri or "/snapshots/" not in ci_verdict_uri:
        return
    results_prefix = _results_prefix_from_ci_verdict_uri(bucket_root, ci_verdict_uri)
    if not results_prefix:
        return
    run_id = (summary.get("run_id") or "").strip()
    if not run_id:
        return
    passed = bool(summary.get("passed"))

    current_uri = _bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/current.json")
    existing: dict[str, Any] = {}
    existing_raw, _ = _gcloud_download_json(current_uri)
    if isinstance(existing_raw, dict):
        existing = existing_raw
    previous_last_passing = existing.get("last_passing")
    if isinstance(previous_last_passing, str):
        previous_last_passing = previous_last_passing.strip() or None
    else:
        previous_last_passing = None

    new_latest = run_id
    new_last_passing = run_id if passed else previous_last_passing
    updated_at = _now_iso()
    new_pointer = {
        "latest": new_latest,
        "last_passing": new_last_passing,
        "updated_at": updated_at,
    }
    if not _gcloud_upload_json(current_uri, new_pointer):
        return
    referenced: set[str] = set()
    if new_latest:
        referenced.add(new_latest)
    if new_last_passing:
        referenced.add(new_last_passing)
    snapshots_prefix_uri = _bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/snapshots/")
    object_uris = _gcloud_ls(snapshots_prefix_uri, recursive=True)
    seen_run_ids: set[str] = set()
    for obj_uri in object_uris:
        if not obj_uri.startswith(snapshots_prefix_uri):
            continue
        rest = obj_uri[len(snapshots_prefix_uri) :].lstrip("/")
        parts = rest.split("/")
        if parts:
            seen_run_ids.add(parts[0])
    for run_id_to_delete in seen_run_ids:
        if run_id_to_delete in referenced:
            continue
        delete_prefix = _bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/snapshots/{run_id_to_delete}")
        if _gcloud_rm(delete_prefix, recursive=True):
            pass
    _cleanup_legacy_result_history(bucket_root, results_prefix)


def _process_run_trigger(  # noqa: PLR0911
    run_trigger_uri: str,
    default_code_bucket_root: str,
    default_runtime_bucket_root: str,
    workspace_root: Path,
    github_token_resolver: Callable[[str], str | None],
) -> bool:
    """Returns True if trigger was consumed (exit-after-run may fire), False if kept for retry."""
    """Download run trigger, run each leg, aggregate, post commit status, release locks, delete trigger."""
    downloaded = _gcloud_download_json(run_trigger_uri)
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
            _gcloud_rm(run_trigger_uri)
        else:
            pass
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
    if run_context == "pr" and pr_number is None:
        pass

    pr_state_at_pickup: dict[str, str | bool | None] | None = None
    skip_before_pickup_reason: str | None = None
    superseded_by_sha: str | None = None
    if should_check_pr_state and pr_number is not None:
        pr_state_at_pickup = github_pull_request.get_pr_state(github_token, repository, pr_number, attempts=3)
        state_at_pickup = str(pr_state_at_pickup.get("state"))
        if state_at_pickup == "unknown":
            pass
        elif state_at_pickup == "closed":
            skip_before_pickup_reason = "pr_closed_before_pickup"
        else:
            pr_head_sha = pr_state_at_pickup.get("head_sha")
            if isinstance(pr_head_sha, str):
                pr_head_sha = pr_head_sha.strip() or None
            else:
                pr_head_sha = None
            if sha and pr_head_sha and pr_head_sha != sha:
                skip_before_pickup_reason = "superseded_by_new_commit"
                superseded_by_sha = pr_head_sha

    skip_before_pickup = bool(skip_before_pickup_reason)

    requested_legs = _resolve_requested_legs(
        legs_raw=legs_raw,
        code_bucket_root=code_bucket_root,
    )
    if skip_before_pickup:
        for leg in requested_legs:
            leg["decision"] = "rejected"
            leg["reason"] = skip_before_pickup_reason or "skipped"

    accepted_legs: list[dict[str, str]] = [
        {
            "project": str(leg.get("project", "?")),
            "bmt_id": str(leg.get("bmt_id", "?")),
            "run_id": str(leg.get("run_id", "?")),
        }
        for leg in requested_legs
        if leg.get("decision") == "accepted"
    ]
    rejected_legs: list[dict[str, int | str]] = [
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
    accepted_exec_legs: list[dict[str, str | int]] = [
        {
            "index": int(leg.get("index", -1)),
            "project": str(leg.get("project", "?")),
            "bmt_id": str(leg.get("bmt_id", "?")),
            "run_id": str(leg.get("run_id", "?")),
        }
        for leg in requested_legs
        if leg.get("decision") == "accepted"
    ]
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
                    "title": f"BMT Execution Started ({accepted_leg_count} legs)",
                    "summary": f"Running BMT for {accepted_leg_count} runtime-supported project configurations...",
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
                    "BMT VM: failed to download orchestrator",
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
                        "summary": "Failed to download orchestrator on VM.",
                    },
                    token_resolver=github_token_resolver,
                )
                if pr_number is not None:
                    _upsert_pr_comment(
                        result="⚠️ BMT did not run",
                        summary_line="The test runner could not start.",
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
                                    "title": f"BMT Progress: {accepted_completed}/{accepted_leg_count} legs complete",
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
                    check_summary = "Cancelled: PR closed before completion."
                    if cancel_reason == "superseded_by_new_commit":
                        short_new = _short_sha(superseded_by_sha or "")
                        check_summary = f"Cancelled: superseded by newer commit ({short_new})."
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
                    cancel_description = "BMT cancelled: PR closed before completion."
                    if cancel_reason == "superseded_by_new_commit":
                        cancel_description = "BMT cancelled: superseded by newer commit."
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
                        result="⏭️ BMT superseded",
                        summary_line="A newer commit arrived — this run was cancelled.",
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
                            result="✅ BMT passed",
                            summary_line="All tests passed.",
                            details_line="",
                        )
                    else:
                        _upsert_pr_comment(
                            result="❌ BMT failed",
                            summary_line=_failed_legs_display(leg_summaries),
                            details_line=details,
                        )
            return True
        except Exception as exc:
            traceback.print_exc()
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
                    f"BMT VM error: {exc!s}"[:140],
                    None,
                    github_token,
                    context=gate_status_context,
                    token_resolver=github_token_resolver,
                )
                check_run_id, github_token, check_completed = _finalize_check_run_resilient(
                    token=github_token,
                    repository=repository,
                    sha=sha,
                    status_context=runtime_status_context,
                    check_run_id=check_run_id,
                    conclusion="failure",
                    output={
                        "title": "BMT VM Error",
                        "summary": f"Unhandled error: {exc!s}",
                    },
                    token_resolver=github_token_resolver,
                )
                if not check_completed:
                    pass
                if pr_number is not None:
                    _upsert_pr_comment(
                        result="❌ BMT failed",
                        summary_line="The test runner encountered an error.",
                        details_line="For details, open the **Checks** tab on this PR.",
                    )
            return False
    except Exception:
        logging.getLogger(__name__).exception("Unhandled exception in run trigger processing")
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

    while not _shutdown:
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
            if _shutdown:
                break
            ack_id = received_msg.ack_id
            try:
                payload = json.loads(received_msg.message.data.decode("utf-8"))
            except (json.JSONDecodeError, ValueError):
                subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": [ack_id]})
                continue

            # Reconstruct the GCS trigger URI from the payload so we can reuse
            # _process_run_trigger unchanged (it still deletes the GCS object on success).
            bucket = str(payload.get("bucket", "")).strip() or runtime_bucket_root.split("gs://", 1)[-1].split("/")[0]
            run_id = str(payload.get("workflow_run_id", "")).strip()
            if not run_id:
                subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": [ack_id]})
                continue

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
                if exit_after_run:
                    if idle_timeout_sec > 0:
                        idle_deadline = time.monotonic() + idle_timeout_sec
                    else:
                        return 0
            else:
                # Nack: let Pub/Sub redeliver after the ack deadline expires.
                subscriber.modify_ack_deadline(
                    request={"subscription": subscription_path, "ack_ids": [ack_id], "ack_deadline_seconds": 0}
                )

    return 0


def main() -> int:
    args = parse_args()
    workspace_root = _resolve_workspace_root(args.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)

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

    # GCS polling fallback (used when --subscription is not set)
    idle_deadline = time.monotonic() + idle_timeout_sec if (exit_after_run and idle_timeout_sec > 0) else None

    while not _shutdown:
        run_trigger_uris = _discover_run_triggers(runtime_bucket_root)

        if run_trigger_uris:
            idle_deadline = None  # reset once a trigger is found
            for run_trigger_uri in run_trigger_uris:
                if _shutdown:
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
        elif idle_deadline is not None and time.monotonic() >= idle_deadline:
            return 0

        if not _shutdown:
            time.sleep(args.poll_interval_sec)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
