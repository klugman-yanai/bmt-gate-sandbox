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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add remote/lib to path for github_auth module
_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR / "lib"))
import github_auth  # type: ignore[import-not-found]  # noqa: E402
import github_checks  # type: ignore[import-not-found]  # noqa: E402
import github_pr_comment  # type: ignore[import-not-found]  # noqa: E402
import status_file  # type: ignore[import-not-found]  # noqa: E402

_shutdown = False
_KEEP_RECENT_WORKFLOW_FILES = 2
_KEEP_RECENT_LOCAL_RUNS = 2
UTC = timezone.utc


def _handle_signal(signum: int, _frame: Any) -> None:
    global _shutdown
    print(f"Received signal {signum}, shutting down gracefully...")
    _shutdown = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll GCS for BMT trigger files")
    _ = parser.add_argument("--bucket", required=True)
    _ = parser.add_argument("--bucket-prefix", default=os.environ.get("BMT_BUCKET_PREFIX", ""))
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


def _normalize_prefix(prefix: str) -> str:
    return prefix.strip("/")


def _child_prefix(parent: str, leaf: str) -> str:
    parent_clean = _normalize_prefix(parent)
    leaf_clean = _normalize_prefix(leaf)
    if not leaf_clean:
        return parent_clean
    return f"{parent_clean}/{leaf_clean}" if parent_clean else leaf_clean


def _code_prefix(parent: str) -> str:
    return _child_prefix(parent, "code")


def _runtime_prefix(parent: str) -> str:
    return _child_prefix(parent, "runtime")


def _bucket_root_uri(bucket: str, prefix: str) -> str:
    prefix = _normalize_prefix(prefix)
    return f"gs://{bucket}/{prefix}" if prefix else f"gs://{bucket}"


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


def _gcloud_download_json(uri: str) -> dict[str, Any] | None:
    """Download a JSON object from GCS."""
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
            return None
        try:
            return json.loads(local_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  Failed to parse {uri}: {exc}")
            return None


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
        "--bucket-prefix-parent",
        str(trigger.get("bucket_prefix_parent", "")),
        "--code-prefix",
        str(trigger.get("code_prefix", "")),
        "--runtime-prefix",
        str(trigger.get("runtime_prefix", "")),
        # Compatibility for older orchestrator versions.
        "--bucket-prefix",
        str(trigger.get("bucket_prefix", "")),
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
    context: str = "BMT Gate",
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
        "context": (context or "BMT Gate").strip() or "BMT Gate",
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


def _progress_description(legs: list[dict[str, Any]], elapsed_sec: int) -> str:
    """Build short commit-status description for PR (max 140 chars) so devs see progress in the browser."""
    total = len(legs)
    completed = sum(1 for leg in legs if leg.get("status") not in ("pending", "running"))
    pass_n = sum(1 for leg in legs if leg.get("status") == "pass")
    fail_n = sum(1 for leg in legs if leg.get("status") == "fail")
    running_n = sum(1 for leg in legs if leg.get("status") == "running")
    elapsed_str = f"{elapsed_sec // 60}m" if elapsed_sec >= 60 else f"{elapsed_sec}s"
    # Prefer one-line summary that fits; fall back to compact counts
    summary_parts = []
    if pass_n:
        summary_parts.append(f"{pass_n} pass")
    if fail_n:
        summary_parts.append(f"{fail_n} fail")
    if running_n:
        summary_parts.append(f"{running_n} running")
    if completed < total and not running_n:
        summary_parts.append(f"{total - completed} pending")
    line = ", ".join(summary_parts) if summary_parts else "running"
    desc = f"BMT: {completed}/{total} legs · {line} — {elapsed_str}"
    return desc[:140]


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


def _format_bmt_comment(result: str, summary_line: str, details_line: str) -> str:
    """Build PR comment body: heading + summary + details line."""
    return f"## BMT result: {result}\n\n{summary_line}\n\n{details_line}"


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


def _process_run_trigger(
    run_trigger_uri: str,
    default_code_bucket_root: str,
    default_runtime_bucket_root: str,
    default_runtime_prefix: str,
    workspace_root: Path,
    github_token_resolver: Callable[[str], str | None],
) -> None:
    """Download run trigger, run each leg, aggregate, post commit status, release locks, delete trigger."""
    run_payload = _gcloud_download_json(run_trigger_uri)
    if run_payload is None:
        print(f"  Skipping unparseable run trigger: {run_trigger_uri}")
        _gcloud_rm(run_trigger_uri)
        return

    legs = run_payload.get("legs") or []
    repository = (run_payload.get("repository") or "").strip()
    sha = (run_payload.get("sha") or "").strip()
    run_context = run_payload.get("run_context", "manual")
    workflow_run_id = run_payload.get("workflow_run_id", "?")
    status_context = (run_payload.get("status_context") or "BMT Gate").strip() or "BMT Gate"
    description_pending = (
        run_payload.get("description_pending") or ""
    ).strip() or "BMT running on VM; status will update when complete."

    pr_number: int | None = None
    pr_raw = run_payload.get("pull_request_number")
    if pr_raw is not None:
        with contextlib.suppress(TypeError, ValueError):
            pr_number = int(pr_raw)

    # Resolve GitHub token for this specific repository
    github_token = github_token_resolver(repository) if repository else None
    if not github_token:
        print(f"  Warning: No GitHub auth for {repository}; VM will not post commit status")

    if not legs:
        print(f"  Run trigger has no legs: {run_trigger_uri}")
        _gcloud_rm(run_trigger_uri)
        return

    accepted_legs: list[dict[str, str]] = []
    rejected_legs: list[dict[str, int | str]] = []
    for idx, leg in enumerate(legs):
        if not isinstance(leg, dict):
            rejected_legs.append({"index": idx, "reason": "invalid_leg_type"})
            continue
        accepted_legs.append(
            {
                "project": str(leg.get("project", "?")),
                "bmt_id": str(leg.get("bmt_id", "?")),
                "run_id": str(leg.get("run_id", "?")),
            }
        )

    handshake_uri = _run_handshake_uri_from_trigger_uri(run_trigger_uri)
    handshake_payload: dict[str, Any] = {
        "workflow_run_id": str(workflow_run_id),
        "received_at": _now_iso(),
        "repository": repository,
        "sha": sha,
        "run_context": str(run_context),
        "run_trigger_uri": run_trigger_uri,
        "requested_leg_count": len(legs),
        "accepted_leg_count": len(accepted_legs),
        "accepted_legs": accepted_legs,
        "rejected_legs": rejected_legs,
        "vm": {
            "hostname": os.uname().nodename,
            "pid": os.getpid(),
        },
    }
    if _gcloud_upload_json(handshake_uri, handshake_payload):
        print(f"  Wrote VM handshake ack: {handshake_uri}")

    bucket = str(run_payload.get("bucket", "")).strip()
    parent_prefix = _normalize_prefix(str(run_payload.get("bucket_prefix_parent") or ""))
    runtime_prefix = _normalize_prefix(str(run_payload.get("runtime_prefix") or ""))
    code_prefix = _normalize_prefix(str(run_payload.get("code_prefix") or ""))
    legacy_bucket_prefix = _normalize_prefix(str(run_payload.get("bucket_prefix") or ""))
    if not runtime_prefix:
        runtime_prefix = legacy_bucket_prefix or _runtime_prefix(parent_prefix) or default_runtime_prefix
    if not code_prefix:
        code_prefix = _code_prefix(parent_prefix)
    code_bucket_root = _bucket_root_uri(bucket, code_prefix) if bucket else default_code_bucket_root
    runtime_bucket_root = _bucket_root_uri(bucket, runtime_prefix) if bucket else default_runtime_bucket_root

    print(
        f"  Processing run {workflow_run_id} with {len(legs)} leg(s) "
        f"[parent={parent_prefix or '<none>'} code={code_prefix or '<none>'} runtime={runtime_prefix or '<none>'}]"
    )

    # Initialize status file for progress tracking
    run_id = str(workflow_run_id)  # Use workflow_run_id as the overall run identifier
    initial_status = {
        "run_id": run_id,
        "workflow_run_id": workflow_run_id,
        "repository": repository,
        "sha": sha,
        "vm_state": "acknowledged",
        "started_at": _now_iso(),
        "last_heartbeat": _now_iso(),
        "legs_total": len(legs),
        "legs_completed": 0,
        "current_leg": None,
        "legs": [
            {
                "index": i,
                "project": leg.get("project", "?"),
                "bmt_id": leg.get("bmt_id", "?"),
                "run_id": leg.get("run_id", "?"),
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "duration_sec": None,
                "files_total": None,
                "files_completed": 0,
            }
            for i, leg in enumerate(legs)
        ],
        "eta_sec": None,
        "elapsed_sec": 0,
        "last_run_duration_sec": None,
        "errors": [],
    }
    workflow_run_id_str = str(workflow_run_id)
    try:
        status_file.write_status(bucket, runtime_prefix, run_id, initial_status)
        print(f"  Initialized status file for run {run_id}")
    except Exception as exc:
        print(f"  Warning: Failed to write initial status file: {exc}")

    # Start heartbeat thread
    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(bucket, runtime_prefix, run_id, stop_heartbeat),
        daemon=True,
    )
    heartbeat_thread.start()
    print("  Started heartbeat thread")

    # Create GitHub Check Run
    check_run_id: int | None = None
    if repository and sha and github_token:
        try:
            check_run_id = github_checks.create_check_run(
                github_token,
                repository,
                sha,
                name=status_context,
                status="in_progress",
                output={
                    "title": f"BMT Execution Started ({len(legs)} legs)",
                    "summary": f"Running BMT for {len(legs)} project configurations...",
                },
            )
            print(f"  Created GitHub Check Run: {check_run_id}")
        except Exception as exc:
            print(f"  Warning: Failed to create Check Run: {exc}")

    # Handshake: post pending so GitHub shows BMT has been picked up by the VM
    if repository and sha and github_token:
        _post_commit_status(
            repository,
            sha,
            "pending",
            description_pending,
            None,
            github_token,
            context=status_context,
        )

    try:
        try:
            orchestrator_path = _download_orchestrator(code_bucket_root, workspace_root)
        except subprocess.CalledProcessError as exc:
            print(f"  Failed to download orchestrator: {exc}")
            if repository and sha and github_token:
                _post_commit_status(
                    repository,
                    sha,
                    "failure",
                    "BMT VM: failed to download orchestrator",
                    None,
                    github_token,
                    context=status_context,
                )
                if pr_number is not None:
                    body = _format_bmt_comment(
                        "Did not run",
                        "The test runner could not start.",
                        "For details, open the **Checks** tab on this PR.",
                    )
                    github_pr_comment.post_pr_comment(github_token, repository, pr_number, body)
            return

        leg_summaries: list[dict[str, Any] | None] = []
        start_timestamp = time.time()

        try:
            for idx, leg in enumerate(legs):
                if not isinstance(leg, dict):
                    leg_summaries.append(None)
                    continue

                # Update status: mark leg as running
                try:
                    current_status = status_file.read_status(bucket, runtime_prefix, run_id)
                    if current_status:
                        current_status["legs"][idx]["status"] = "running"
                        current_status["legs"][idx]["started_at"] = _now_iso()
                        current_status["current_leg"] = current_status["legs"][idx].copy()
                        current_status["elapsed_sec"] = int(time.time() - start_timestamp)
                        status_file.write_status(bucket, runtime_prefix, run_id, current_status)
                except Exception as exc:
                    print(f"  Warning: Failed to update status for leg {idx}: {exc}")

                trigger = {
                    "bucket": bucket,
                    "bucket_prefix_parent": parent_prefix,
                    "code_prefix": code_prefix,
                    "runtime_prefix": runtime_prefix,
                    # Compatibility field for older orchestrator versions.
                    "bucket_prefix": runtime_prefix,
                    "project": leg.get("project", "?"),
                    "bmt_id": leg.get("bmt_id", "?"),
                    "run_context": run_context,
                    "run_id": leg.get("run_id", "?"),
                    "leg_index": idx,
                    "workflow_run_id": workflow_run_id,
                }
                leg_start_time = time.time()
                exit_code = _run_orchestrator(orchestrator_path, trigger, workspace_root)
                leg_duration = int(time.time() - leg_start_time)
                state = "PASS" if exit_code == 0 else "FAIL"
                print(f"  Leg {idx + 1}/{len(legs)} {trigger['project']}.{trigger['bmt_id']} -> {state}")
                run_root = _latest_run_root(workspace_root, trigger["project"], trigger["bmt_id"])
                summary = _load_manager_summary(run_root)
                leg_summaries.append(summary)

                # Update status: mark leg as complete
                try:
                    current_status = status_file.read_status(bucket, runtime_prefix, run_id)
                    if current_status:
                        leg_status = "pass" if exit_code == 0 else "fail"
                        current_status["legs"][idx]["status"] = leg_status
                        current_status["legs"][idx]["completed_at"] = _now_iso()
                        current_status["legs"][idx]["duration_sec"] = leg_duration

                        # Get files info from manager summary if available
                        if summary:
                            bmt_results = summary.get("bmt_results", {})
                            results = bmt_results.get("results", [])
                            current_status["legs"][idx]["files_total"] = len(results)
                            current_status["legs"][idx]["files_completed"] = len(results)

                            # Get orchestration timing for ETA
                            orchestration_timing = summary.get("orchestration_timing", {})
                            if "duration_sec" in orchestration_timing:
                                current_status["legs"][idx]["duration_sec"] = orchestration_timing["duration_sec"]

                        current_status["legs_completed"] = idx + 1
                        current_status["elapsed_sec"] = int(time.time() - start_timestamp)

                        # Update current_leg to next leg or None
                        if idx + 1 < len(legs):
                            current_status["current_leg"] = current_status["legs"][idx + 1].copy()
                        else:
                            current_status["current_leg"] = None

                        status_file.write_status(bucket, runtime_prefix, run_id, current_status)

                        # Update Check Run with progress (what devs see in GitHub browser)
                        if check_run_id and repository and sha and github_token:
                            try:
                                github_checks.update_check_run(
                                    github_token,
                                    repository,
                                    check_run_id,
                                    output={
                                        "title": f"BMT Progress: {idx + 1}/{len(legs)} legs complete",
                                        "summary": github_checks.render_progress_markdown(
                                            current_status["legs"],
                                            elapsed_sec=current_status["elapsed_sec"],
                                            eta_sec=current_status.get("eta_sec"),
                                        ),
                                    },
                                )
                            except Exception as exc:
                                print(f"  Warning: Failed to update Check Run: {exc}")
                        # Update commit status description so PR status line shows progress
                        if repository and sha and github_token:
                            desc = _progress_description(
                                current_status["legs"],
                                current_status["elapsed_sec"],
                            )
                            _post_commit_status(
                                repository,
                                sha,
                                "pending",
                                desc,
                                None,
                                github_token,
                                context=status_context,
                            )
                except Exception as exc:
                    print(f"  Warning: Failed to update status after leg {idx}: {exc}")

            state, description = _aggregate_verdicts_from_summaries(leg_summaries)
            print(f"  Aggregate: {state} — {description}")

            # Finalize status file
            try:
                final_status = status_file.read_status(bucket, runtime_prefix, run_id)
                if final_status:
                    final_status["vm_state"] = "completed"
                    final_status["last_heartbeat"] = _now_iso()
                    final_status["elapsed_sec"] = int(time.time() - start_timestamp)
                    status_file.write_status(bucket, runtime_prefix, run_id, final_status)
                    print("  Finalized status file")
            except Exception as exc:
                print(f"  Warning: Failed to finalize status file: {exc}")

            # Complete GitHub Check Run
            if check_run_id and repository and sha and github_token:
                try:
                    conclusion = "success" if state == "success" else "failure"
                    github_checks.update_check_run(
                        github_token,
                        repository,
                        check_run_id,
                        status="completed",
                        conclusion=conclusion,
                        output={
                            "title": f"BMT Complete: {state.upper()}",
                            "summary": github_checks.render_results_table(leg_summaries, {
                                "state": "PASS" if state == "success" else "FAIL",
                                "decision": state,
                                "reasons": [],
                            }),
                        },
                    )
                    print(f"  Completed Check Run: {conclusion}")
                except Exception as exc:
                    print(f"  Warning: Failed to complete Check Run: {exc}")

            for summary in leg_summaries:
                if summary is not None:
                    _update_pointer_and_cleanup(runtime_bucket_root, summary)

            if repository and sha and github_token:
                if _post_commit_status(repository, sha, state, description, None, github_token, context=status_context):
                    print(f"  Posted commit status: {state}")
                else:
                    print("  Could not post commit status (check GITHUB_STATUS_TOKEN)")
                if pr_number is not None:
                    details = "For details, open the **Checks** tab on this PR."
                    if state == "success":
                        body = _format_bmt_comment("Success", "All tests passed.", details)
                    else:
                        body = _format_bmt_comment("Failed", _failed_legs_display(leg_summaries), details)
                    if github_pr_comment.post_pr_comment(github_token, repository, pr_number, body):
                        print("  Posted PR comment")
                    else:
                        print("  Could not post PR comment (non-fatal)")
        except Exception as exc:
            print(f"  Error during BMT run: {exc}")
            traceback.print_exc()
            if repository and sha and github_token:
                _post_commit_status(
                    repository,
                    sha,
                    "failure",
                    f"BMT VM error: {exc!s}"[:140],
                    None,
                    github_token,
                    context=status_context,
                )
                if check_run_id is not None:
                    try:
                        github_checks.update_check_run(
                            github_token,
                            repository,
                            check_run_id,
                            status="completed",
                            conclusion="failure",
                            output={
                                "title": "BMT VM Error",
                                "summary": f"Unhandled error: {exc!s}",
                            },
                        )
                    except Exception as update_exc:
                        print(f"  Warning: Failed to complete Check Run on error: {update_exc}")
                if pr_number is not None:
                    body = _format_bmt_comment(
                        "Failed",
                        "The test runner encountered an error.",
                        "For details, open the **Checks** tab on this PR.",
                    )
                    if github_pr_comment.post_pr_comment(github_token, repository, pr_number, body):
                        print("  Posted PR comment")
                    else:
                        print("  Could not post PR comment (non-fatal)")
            return
    except Exception as exc:
        print(f"  Warning: post-run finalization failed: {exc}")
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=5)
        print("  Stopped heartbeat thread")
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

    parent = _normalize_prefix(args.bucket_prefix)
    code_prefix = _code_prefix(parent)
    runtime_prefix = _runtime_prefix(parent)
    code_bucket_root = _bucket_root_uri(args.bucket, code_prefix)
    runtime_bucket_root = _bucket_root_uri(args.bucket, runtime_prefix)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print(
        f"BMT Watcher started: bucket={args.bucket} "
        f"parent={parent or '<none>'} code={code_prefix or '<none>'} runtime={runtime_prefix or '<none>'} "
        f"poll={args.poll_interval_sec}s"
    )
    print(f"Workspace: {workspace_root}")

    # Use GitHub App auth module for per-repository token resolution
    github_token_resolver = github_auth.resolve_auth_for_repository

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
                    runtime_prefix,
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
