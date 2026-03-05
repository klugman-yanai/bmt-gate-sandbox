#!/usr/bin/env python3
"""VM-side trigger watcher.

Polls GCS for run trigger files (one per workflow run, contains all legs).
Runs root_orchestrator.py for each leg, aggregates verdicts, and posts
commit status to GitHub so the PR is gated without blocking the workflow runner.
Designed to run as a systemd service — stdlib + gcloud CLI only, no pip deps.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add remote/lib to path for github_auth module
_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR / "lib"))
import github_auth  # type: ignore[import-not-found]  # noqa: E402
import github_checks  # type: ignore[import-not-found]  # noqa: E402
import github_pr_comment  # type: ignore[import-not-found]  # noqa: E402
import github_pull_request  # type: ignore[import-not-found]  # noqa: E402
import status_file  # type: ignore[import-not-found]  # noqa: E402

_shutdown = False
_KEEP_RECENT_LOCAL_RUNS = 2

# Fallback when trigger payload omits contexts; normal path is run_trigger payload (workflow sets from repo vars).
DEFAULT_STATUS_CONTEXT = "BMT Gate"
DEFAULT_RUNTIME_STATUS_CONTEXT = "BMT Runtime"
PROJECT_WIDE_BMT_IDS = frozenset({"", "*", "__all__", "all", "project_all", "__project_wide__"})


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            print(f"Warning: invalid integer for {name}={raw!r}; using default {default}.")
            value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


_KEEP_RECENT_WORKFLOW_FILES = _env_int("BMT_TRIGGER_METADATA_KEEP_RECENT", 2, minimum=0)


def _handle_signal(signum: int, _frame: Any) -> None:
    global _shutdown
    print(f"Received signal {signum}, shutting down gracefully...")
    _shutdown = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll GCS for BMT trigger files")
    _ = parser.add_argument("--bucket", required=True)
    _ = parser.add_argument("--poll-interval-sec", type=int, default=10)
    _ = parser.add_argument("--workspace-root", default=os.environ.get("BMT_WORKSPACE_ROOT", ""))
    _ = parser.add_argument(
        "--exit-after-run",
        action="store_true",
        help="Exit after processing one run (for on-demand VM: then stop instance).",
    )
    return parser.parse_args()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _code_bucket_root(bucket: str) -> str:
    return f"gs://{bucket}/code"


def _runtime_bucket_root(bucket: str) -> str:
    return f"gs://{bucket}/runtime"


def _bucket_uri(bucket_root: str, path: str) -> str:
    return f"{bucket_root}/{path.lstrip('/')}"


def _resolve_workspace_root(raw: str) -> Path:
    """Default to ~/bmt_workspace with compatibility fallback to legacy ~/sk_runtime."""
    if raw.strip():
        return Path(raw).expanduser().resolve()
    preferred = Path("~/bmt_workspace").expanduser()
    legacy = Path("~/sk_runtime").expanduser()
    if legacy.exists() and not preferred.exists():
        print("Warning: using legacy workspace path ~/sk_runtime (set --workspace-root or BMT_WORKSPACE_ROOT).")
        return legacy.resolve()
    return preferred.resolve()


def _gcloud_ls(uri: str, recursive: bool = False) -> list[str]:
    """List objects under a GCS URI prefix. Returns list of full URIs."""
    cmd = ["gcloud", "storage", "ls", uri]
    if recursive:
        cmd.append("--recursive")
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _gcloud_download_json(uri: str) -> tuple[dict[str, Any] | None, str | None]:
    """Download a JSON object from GCS.

    Returns:
      (payload, None) on success.
      (None, "download_failed") on transient download failures.
      (None, "invalid_json") when object exists but payload is malformed.
    """
    with tempfile.TemporaryDirectory(prefix="vm_watcher_") as tmp_dir:
        local_path = Path(tmp_dir) / "trigger.json"
        proc = subprocess.run(
            ["gcloud", "storage", "cp", uri, str(local_path), "--quiet"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"  Failed to download {uri}: {proc.stderr.strip()}")
            return None, "download_failed"
        try:
            payload = json.loads(local_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  Failed to parse {uri}: {exc}")
            return None, "invalid_json"
        if not isinstance(payload, dict):
            print(f"  Invalid JSON payload type for {uri}: expected object")
            return None, "invalid_json"
        return payload, None


def _gcloud_upload_json(uri: str, payload: dict[str, Any]) -> bool:
    """Upload a JSON object to GCS."""
    with tempfile.TemporaryDirectory(prefix="vm_watcher_ack_") as tmp_dir:
        local_path = Path(tmp_dir) / "ack.json"
        local_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        proc = subprocess.run(
            ["gcloud", "storage", "cp", str(local_path), uri, "--quiet"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"  Failed to upload {uri}: {proc.stderr.strip()}")
            return False
    return True


def _gcloud_rm(uri: str, recursive: bool = False) -> bool:
    """Delete a GCS object or prefix (with recursive=True)."""
    cmd = ["gcloud", "storage", "rm", uri, "--quiet"]
    if recursive:
        cmd.append("--recursive")
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _gcloud_exists(uri: str) -> bool:
    """Return True when a GCS object exists."""
    proc = subprocess.run(
        ["gcloud", "storage", "ls", uri],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _load_jobs_config_from_gcs(code_bucket_root: str, project: str) -> tuple[dict[str, Any] | None, str | None]:
    """Load per-project jobs config from code bucket.

    Returns (payload, error_reason_code).
    """
    jobs_rel = f"{project}/config/bmt_jobs.json"
    jobs_uri = _bucket_uri(code_bucket_root, jobs_rel)
    if not _gcloud_exists(jobs_uri):
        return None, "jobs_config_missing"

    with tempfile.TemporaryDirectory(prefix="vm_watcher_jobs_") as tmp_dir:
        local_jobs = Path(tmp_dir) / "bmt_jobs.json"
        proc = subprocess.run(
            ["gcloud", "storage", "cp", jobs_uri, str(local_jobs), "--quiet"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"  Warning: Failed to download jobs config for {project}: {proc.stderr.strip()}")
            return None, "jobs_config_missing"
        try:
            payload = json.loads(local_jobs.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, "jobs_schema_invalid"

    if not isinstance(payload, dict):
        return None, "jobs_schema_invalid"
    bmts = payload.get("bmts")
    if not isinstance(bmts, dict):
        return None, "jobs_schema_invalid"
    return payload, None


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
            manager_uri = _bucket_uri(code_bucket_root, f"{project}/bmt_manager.py")
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
    subprocess.run(
        ["gcloud", "storage", "cp", orchestrator_uri, str(local_path), "--quiet"],
        check=True,
    )
    local_path.chmod(local_path.stat().st_mode | 0o111)
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
    """List run trigger JSON files under runtime/triggers/runs/."""
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
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print(f"  Failed to post commit status: {exc}")
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
    output: dict[str, str],
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
        except Exception as exc:
            print(f"  Warning: Failed to create Check Run (attempt {attempt}/{max_attempts}): {exc}")
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
    output: dict[str, str] | None = None,
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
        except Exception as exc:
            print(f"  Warning: Failed to update Check Run (attempt {attempt}/{max_attempts}): {exc}")
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
    output: dict[str, str],
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
    if deleted or failed:
        kept = len(entries) - deleted
        print(
            f"  Trimmed {family_prefix_uri}: kept={kept} deleted={deleted} failed={failed} "
            f"(retain recent={max(keep_recent, 0)} + explicit={len(normalized_keep)})"
        )


def _cleanup_workflow_artifacts(
    *,
    runtime_bucket_root: str,
    keep_workflow_ids: set[str],
) -> None:
    """Keep workflow metadata families bounded to current + previous entries."""
    if not runtime_bucket_root.strip():
        return

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
            print(f"  Removed legacy history prefix: {legacy_uri}")


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


def _commit_url(repository: str, sha: str) -> str:
    """Build commit URL when repository and SHA are available."""
    repo = (repository or "").strip()
    clean_sha = (sha or "").strip()
    if not repo or not clean_sha:
        return ""
    return f"https://github.com/{repo}/commit/{clean_sha}"


def _commit_markdown_link(repository: str, sha: str) -> str:
    """Render commit link markdown with short SHA text."""
    url = _commit_url(repository, sha)
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
    superseding_sha: str | None = None,
) -> str:
    """Build PR comment body with commit linkage and stable marker for upsert."""
    lines = [
        _comment_marker_for_sha(tested_sha),
        f"## BMT result: {result}",
        "",
        summary_line,
        "",
        details_line,
        "",
        f"- Tested commit: {_commit_markdown_link(repository, tested_sha)}",
    ]
    if superseding_sha:
        lines.append(f"- Superseding commit: {_commit_markdown_link(repository, superseding_sha)}")
    if workflow_run_id is not None:
        lines.append(f"- Workflow run id: `{workflow_run_id}`")
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
        try:
            status_file.update_heartbeat(bucket, runtime_prefix, run_id)
        except Exception as exc:
            print(f"  Heartbeat update failed: {exc}")
        stop_event.wait(15)  # Sleep 15s or until stop_event


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
    with tempfile.TemporaryDirectory(prefix="vm_watcher_ptr_") as tmp_dir:
        local_current = Path(tmp_dir) / "current.json"
        proc = subprocess.run(
            ["gcloud", "storage", "cp", current_uri, str(local_current), "--quiet"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and local_current.is_file():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                existing = json.loads(local_current.read_text(encoding="utf-8"))
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
    with tempfile.TemporaryDirectory(prefix="vm_watcher_ptr_") as tmp_dir:
        local_current = Path(tmp_dir) / "current.json"
        local_current.write_text(json.dumps(new_pointer, indent=2) + "\n", encoding="utf-8")
        proc = subprocess.run(
            ["gcloud", "storage", "cp", str(local_current), current_uri, "--quiet"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"  Warning: failed to write pointer {current_uri}")
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
            print(f"  Cleaned snapshot {run_id_to_delete}")
    _cleanup_legacy_result_history(bucket_root, results_prefix)


def _process_run_trigger(  # noqa: PLR0911
    run_trigger_uri: str,
    default_code_bucket_root: str,
    default_runtime_bucket_root: str,
    workspace_root: Path,
    github_token_resolver: Callable[[str], str | None],
) -> None:
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
            print(f"  Removing malformed run trigger: {run_trigger_uri}")
            _gcloud_rm(run_trigger_uri)
        else:
            print(f"  Deferring run trigger after transient download/auth issue: {run_trigger_uri}")
        return

    legs_raw = run_payload.get("legs") or []
    if not isinstance(legs_raw, list):
        legs_raw = []

    repository = (run_payload.get("repository") or "").strip()
    sha = (run_payload.get("sha") or "").strip()
    run_context = str(run_payload.get("run_context", "manual"))
    workflow_run_id = run_payload.get("workflow_run_id", "?")
    gate_status_context = (run_payload.get("status_context") or DEFAULT_STATUS_CONTEXT).strip() or DEFAULT_STATUS_CONTEXT
    runtime_status_context = (
        run_payload.get("runtime_status_context") or DEFAULT_RUNTIME_STATUS_CONTEXT
    ).strip() or DEFAULT_RUNTIME_STATUS_CONTEXT

    pr_number: int | None = None
    pr_raw = run_payload.get("pull_request_number")
    if pr_raw is not None:
        with contextlib.suppress(TypeError, ValueError):
            pr_number = int(pr_raw)

    if not repository:
        print("  Error: Run trigger missing repository; cannot resolve GitHub App auth")
        _gcloud_rm(run_trigger_uri)
        return

    github_token = github_token_resolver(repository)
    if not github_token:
        print(
            f"  Error: GitHub App auth could not be resolved for {repository}; "
            "keeping trigger for retry"
        )
        return

    if not legs_raw:
        print(f"  Run trigger has no legs: {run_trigger_uri}")
        _gcloud_rm(run_trigger_uri)
        return

    bucket = str(run_payload.get("bucket", "")).strip()
    code_bucket_root = _code_bucket_root(bucket) if bucket else default_code_bucket_root
    runtime_bucket_root = _runtime_bucket_root(bucket) if bucket else default_runtime_bucket_root
    runtime_prefix = "runtime"

    print(f"  Processing run {workflow_run_id} with {len(legs_raw)} requested leg(s)")

    run_id = str(workflow_run_id)
    workflow_run_id_str = str(workflow_run_id)

    should_check_pr_state = run_context == "pr" and pr_number is not None
    if run_context == "pr" and pr_number is None:
        print("  Warning: run_context=pr but pull_request_number is missing; fail-open (continuing run).")

    pr_state_at_pickup: dict[str, str | bool | None] | None = None
    skip_before_pickup_reason: str | None = None
    superseded_by_sha: str | None = None
    if should_check_pr_state and pr_number is not None:
        pr_state_at_pickup = github_pull_request.get_pr_state(github_token, repository, pr_number, attempts=3)
        state_at_pickup = str(pr_state_at_pickup.get("state"))
        if state_at_pickup == "unknown":
            print(
                f"  Warning: could not verify PR state at pickup (error={pr_state_at_pickup.get('error')}); "
                "fail-open (continuing run)."
            )
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
    print(f"  Runtime support resolution: accepted={accepted_leg_count} rejected={len(rejected_legs)}")

    stop_heartbeat = threading.Event()
    heartbeat_thread: threading.Thread | None = None
    check_run_id: int | None = None
    cancelled_due_to_pr_state = False
    cancel_reason: str | None = None
    pointer_promotion_allowed = True
    start_timestamp = time.time()
    leg_summaries: list[dict[str, Any] | None] = []

    def _stop_heartbeat_thread() -> None:
        nonlocal heartbeat_thread
        stop_heartbeat.set()
        if heartbeat_thread is None:
            return
        heartbeat_thread.join(timeout=5)
        print("  Stopped heartbeat thread")
        heartbeat_thread = None

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
            superseding_sha=superseding_sha,
        )
        if github_pr_comment.upsert_pr_comment_by_marker(github_token, repository, pr_number, marker, body):
            print("  Upserted PR comment")
        else:
            print("  Could not upsert PR comment (non-fatal)")

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
            print(f"  Wrote VM handshake ack: {handshake_uri}")

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
                    "skip_reason": (skip_before_pickup_reason if skip_before_pickup else reason) if is_skipped else None,
                    "started_at": None,
                    "completed_at": started_at if is_skipped else None,
                    "duration_sec": None,
                    "files_total": None,
                    "files_completed": 0,
                }
            )

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
            "last_run_duration_sec": None,
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
        try:
            status_file.write_status(bucket, runtime_prefix, run_id, initial_status)
            print(f"  Initialized status file for run {run_id}")
        except Exception as exc:
            print(f"  Warning: Failed to write initial status file: {exc}")

        if skip_before_pickup:
            if skip_before_pickup_reason == "superseded_by_new_commit":
                print(
                    "  Run was superseded by newer PR head before pickup; "
                    "skipping run without GitHub status/check updates."
                )
            else:
                print("  PR is already closed at pickup; skipping run without GitHub status/check updates.")
            return

        if accepted_leg_count == 0:
            print("  No runtime-supported legs were accepted by VM; marking run as accepted_but_empty.")
            return

        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(bucket, runtime_prefix, run_id, stop_heartbeat),
            daemon=True,
        )
        heartbeat_thread.start()
        print("  Started heartbeat thread")

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
                print(f"  Created GitHub Check Run: {check_run_id}")

        try:
            orchestrator_path = _download_orchestrator(code_bucket_root, workspace_root)
        except subprocess.CalledProcessError as exc:
            print(f"  Failed to download orchestrator: {exc}")
            _stop_heartbeat_thread()
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
                    failed_status["elapsed_sec"] = int(time.time() - start_timestamp)
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
            except Exception as status_exc:
                print(f"  Warning: Failed to write terminal failure status: {status_exc}")
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
                        result="Did not run",
                        summary_line="The test runner could not start.",
                        details_line="For details, open the **Checks** tab on this PR.",
                    )
            return

        try:
            accepted_completed = 0
            for exec_idx, leg in enumerate(accepted_exec_legs):
                status_idx = int(leg["index"])
                if should_check_pr_state and pr_number is not None:
                    pr_state_now = github_pull_request.get_pr_state(github_token, repository, pr_number, attempts=3)
                    state_now = str(pr_state_now.get("state"))
                    if state_now == "unknown":
                        print(
                            f"  Warning: could not re-check PR state for leg {status_idx} "
                            f"(error={pr_state_now.get('error')}); fail-open (continuing)."
                        )
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
                                print(
                                    "  Run superseded before next leg; cancelling remaining legs. "
                                    f"superseding_sha={superseded_by_sha or 'unknown'}"
                                )
                            else:
                                print(f"  PR closed before leg {exec_idx + 1}; cancelling remaining legs.")
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
                                    current_status["elapsed_sec"] = int(time.time() - start_timestamp)
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
                            except Exception as exc:
                                print(f"  Warning: Failed to update cancellation status: {exc}")
                            break

                try:
                    current_status = status_file.read_status(bucket, runtime_prefix, run_id)
                    if current_status:
                        current_status["legs"][status_idx]["status"] = "running"
                        current_status["legs"][status_idx]["skip_reason"] = None
                        current_status["legs"][status_idx]["started_at"] = _now_iso()
                        current_status["current_leg"] = current_status["legs"][status_idx].copy()
                        current_status["elapsed_sec"] = int(time.time() - start_timestamp)
                        current_status["run_outcome"] = "running"
                        current_status["cancel_reason"] = None
                        current_status["cancelled_at"] = None
                        current_status["superseded_by_sha"] = None
                        status_file.write_status(bucket, runtime_prefix, run_id, current_status)
                except Exception as exc:
                    print(f"  Warning: Failed to update status for leg {status_idx}: {exc}")

                trigger = {
                    "bucket": bucket,
                    "project": str(leg.get("project", "?")),
                    "bmt_id": str(leg.get("bmt_id", "?")),
                    "run_context": run_context,
                    "run_id": str(leg.get("run_id", "?")),
                    "leg_index": status_idx,
                    "workflow_run_id": workflow_run_id,
                }
                leg_start_time = time.time()
                exit_code = _run_orchestrator(orchestrator_path, trigger, workspace_root)
                leg_duration = int(time.time() - leg_start_time)
                state = "PASS" if exit_code == 0 else "FAIL"
                print(f"  Leg {exec_idx + 1}/{accepted_leg_count} {trigger['project']}.{trigger['bmt_id']} -> {state}")
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
                                current_status["legs"][status_idx]["duration_sec"] = orchestration_timing["duration_sec"]

                        current_status["legs_completed"] = accepted_completed
                        current_status["elapsed_sec"] = int(time.time() - start_timestamp)

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
                except Exception as exc:
                    print(f"  Warning: Failed to update status after leg {status_idx}: {exc}")

            if cancelled_due_to_pr_state:
                cancelled_at = _now_iso()
                _stop_heartbeat_thread()
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
                        final_status["elapsed_sec"] = int(time.time() - start_timestamp)
                        final_status["current_leg"] = None
                        final_status["superseded_by_sha"] = superseded_by_sha
                        status_file.write_status(bucket, runtime_prefix, run_id, final_status)
                except Exception as exc:
                    print(f"  Warning: Failed to finalize cancellation status file: {exc}")

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
                        print("  Completed Check Run: neutral (cancelled)")

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
                        result="Superseded",
                        summary_line="This VM run was superseded by a newer commit on the PR.",
                        details_line="A newer commit arrived before all legs completed; this run stopped before the next leg.",
                        superseding_sha=superseded_by_sha,
                    )
                    print("  Cancelled run due to superseding commit; skipped pointer promotion.")
                else:
                    print("  Cancelled run due to closed PR; skipping pointer promotion and PR comments.")
                return

            state, description = _aggregate_verdicts_from_summaries(leg_summaries)
            print(f"  Aggregate: {state} — {description}")

            _stop_heartbeat_thread()
            try:
                final_status = status_file.read_status(bucket, runtime_prefix, run_id)
                if final_status:
                    final_status["vm_state"] = "completed"
                    final_status["run_outcome"] = "completed"
                    final_status["cancel_reason"] = None
                    final_status["cancelled_at"] = None
                    final_status["superseded_by_sha"] = None
                    final_status["last_heartbeat"] = _now_iso()
                    final_status["elapsed_sec"] = int(time.time() - start_timestamp)
                    status_file.write_status(bucket, runtime_prefix, run_id, final_status)
                    print("  Finalized status file")
            except Exception as exc:
                print(f"  Warning: Failed to finalize status file: {exc}")

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
                        "title": f"BMT Complete: {state.upper()}",
                        "summary": github_checks.render_results_table(
                            leg_summaries,
                            {
                                "state": "PASS" if state == "success" else "FAIL",
                                "decision": state,
                                "reasons": [],
                            },
                        ),
                    },
                    token_resolver=github_token_resolver,
                )
                if check_completed:
                    print(f"  Completed Check Run: {conclusion}")
                else:
                    print("  Could not finalize Check Run")

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
                    print(f"  Posted commit status: {state}")
                else:
                    print("  Could not post commit status")
                if pr_number is not None:
                    details = "For details, open the **Checks** tab on this PR."
                    if state == "success":
                        _upsert_pr_comment(
                            result="Success",
                            summary_line="All tests passed.",
                            details_line=details,
                        )
                    else:
                        _upsert_pr_comment(
                            result="Failed",
                            summary_line=_failed_legs_display(leg_summaries),
                            details_line=details,
                        )
        except Exception as exc:
            print(f"  Error during BMT run: {exc}")
            traceback.print_exc()
            _stop_heartbeat_thread()
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
                    failed_status["elapsed_sec"] = int(time.time() - start_timestamp)
                    errors = failed_status.get("errors")
                    if not isinstance(errors, list):
                        errors = []
                    errors.append({"at": failed_at, "message": f"Unhandled error: {exc!s}"})
                    failed_status["errors"] = errors
                    status_file.write_status(bucket, runtime_prefix, run_id, failed_status)
            except Exception as status_exc:
                print(f"  Warning: Failed to write terminal failure status: {status_exc}")
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
                    print("  Warning: Failed to complete Check Run on error")
                if pr_number is not None:
                    _upsert_pr_comment(
                        result="Failed",
                        summary_line="The test runner encountered an error.",
                        details_line="For details, open the **Checks** tab on this PR.",
                    )
            return
    except Exception as exc:
        print(f"  Warning: post-run finalization failed: {exc}")
    finally:
        _stop_heartbeat_thread()
        _gcloud_rm(run_trigger_uri)
        _cleanup_workflow_artifacts(
            runtime_bucket_root=runtime_bucket_root,
            keep_workflow_ids={workflow_run_id_str},
        )
        _prune_workspace_runs(workspace_root, keep_recent_per_bmt=_KEEP_RECENT_LOCAL_RUNS)
        print(f"  Run {workflow_run_id} complete")


def main() -> int:
    args = parse_args()
    workspace_root = _resolve_workspace_root(args.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)

    code_bucket_root = _code_bucket_root(args.bucket)
    runtime_bucket_root = _runtime_bucket_root(args.bucket)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print(
        f"BMT Watcher started: bucket={args.bucket} "
        f"code={code_bucket_root} runtime={runtime_bucket_root} "
        f"poll={args.poll_interval_sec}s"
    )
    print(f"Workspace: {workspace_root}")

    # Use GitHub App auth module for per-repository token resolution
    github_token_resolver = github_auth.resolve_auth_for_repository

    enabled_repositories = github_auth.list_enabled_repositories()
    if enabled_repositories is None:
        print("Error: cannot start watcher without a valid GitHub App repository config.")
        return 2
    if not enabled_repositories:
        print("Warning: no enabled repositories in GitHub App config; incoming triggers will be rejected.")
    unresolved_repositories: list[str] = []
    for repository in enabled_repositories:
        token = github_token_resolver(repository)
        if not token:
            unresolved_repositories.append(repository)
    if unresolved_repositories:
        joined = ", ".join(unresolved_repositories)
        print(
            "Error: GitHub App auth preflight failed for enabled repositories: "
            f"{joined}. Ensure *_ID, *_INSTALLATION_ID, and *_PRIVATE_KEY are present and valid."
        )
        return 2
    if enabled_repositories:
        print(f"GitHub App auth preflight passed for {len(enabled_repositories)} enabled repository(ies).")

    # Startup sweep: enforce bounded retention even after prior failed runs.
    _prune_workspace_runs(workspace_root, keep_recent_per_bmt=_KEEP_RECENT_LOCAL_RUNS)
    _cleanup_workflow_artifacts(
        runtime_bucket_root=runtime_bucket_root,
        keep_workflow_ids=set(),
    )

    while not _shutdown:
        run_trigger_uris = _discover_run_triggers(runtime_bucket_root)

        if run_trigger_uris:
            print(f"[{_now_iso()}] Found {len(run_trigger_uris)} run trigger(s)")
            for run_trigger_uri in run_trigger_uris:
                if _shutdown:
                    break
                _process_run_trigger(
                    run_trigger_uri,
                    code_bucket_root,
                    runtime_bucket_root,
                    workspace_root,
                    github_token_resolver,
                )
                if getattr(args, "exit_after_run", False):
                    print("Exit-after-run: done, exiting so VM can stop.")
                    return 0

        if not _shutdown:
            time.sleep(args.poll_interval_sec)

    print("Watcher stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
