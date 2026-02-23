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
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Add remote/lib to path for github_auth module
_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR / "lib"))
import github_auth  # type: ignore[import-not-found]  # noqa: E402
from gcs import (  # type: ignore[import-not-found]  # noqa: E402
    bucket_root_uri,
    bucket_uri,
    gcloud_download_json,
    gcloud_ls,
    gcloud_rm,
    normalize_prefix,
    now_iso,
)

_shutdown = False


def _handle_signal(signum: int, _frame: Any) -> None:
    global _shutdown
    print(f"Received signal {signum}, shutting down gracefully...")
    _shutdown = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll GCS for BMT trigger files")
    _ = parser.add_argument("--bucket", required=True)
    _ = parser.add_argument("--bucket-prefix", default=os.environ.get("BMT_BUCKET_PREFIX", ""))
    _ = parser.add_argument("--poll-interval-sec", type=int, default=10)
    _ = parser.add_argument("--workspace-root", default=str(Path("~/sk_runtime").expanduser()))
    _ = parser.add_argument(
        "--exit-after-run",
        action="store_true",
        help="Exit after processing one run (for on-demand VM: then stop instance).",
    )
    return parser.parse_args()


def _download_orchestrator(bucket_root: str, workspace_root: Path) -> Path:
    """Download root_orchestrator.py from the bucket."""
    orchestrator_uri = bucket_uri(bucket_root, "root_orchestrator.py")
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
    proc = subprocess.run(command, check=False)
    return proc.returncode


def _discover_run_triggers(bucket_root: str, prefix: str) -> list[str]:
    """List run trigger JSON files under triggers/runs/ (one file per workflow run)."""
    parts = normalize_prefix(prefix)
    runs_prefix = "triggers/runs/"
    if parts:
        runs_prefix = f"{parts}/triggers/runs/"
    runs_uri = bucket_uri(bucket_root, runs_prefix)
    all_objects = gcloud_ls(runs_uri)
    return [uri for uri in all_objects if uri.endswith(".json")]


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

    current_uri = bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/current.json")
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
    updated_at = now_iso()
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
    snapshots_prefix_uri = bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/snapshots/")
    object_uris = gcloud_ls(snapshots_prefix_uri, recursive=True)
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
        delete_prefix = bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/snapshots/{run_id_to_delete}")
        if gcloud_rm(delete_prefix, recursive=True):
            print(f"  Cleaned snapshot {run_id_to_delete}")


def _process_run_trigger(
    run_trigger_uri: str,
    bucket_root: str,
    workspace_root: Path,
    github_token_resolver: Callable[[str], str | None],
) -> None:
    """Download run trigger, run each leg, aggregate, post commit status, release locks, delete trigger."""
    run_payload = gcloud_download_json(run_trigger_uri)
    if run_payload is None:
        print(f"  Skipping unparseable run trigger: {run_trigger_uri}")
        gcloud_rm(run_trigger_uri)
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

    # Resolve GitHub token for this specific repository
    github_token = github_token_resolver(repository) if repository else None
    if not github_token:
        print(f"  Warning: No GitHub auth for {repository}; VM will not post commit status")

    if not legs:
        print(f"  Run trigger has no legs: {run_trigger_uri}")
        gcloud_rm(run_trigger_uri)
        return

    print(f"  Processing run {workflow_run_id} with {len(legs)} leg(s)")

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
        orchestrator_path = _download_orchestrator(bucket_root, workspace_root)
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
        gcloud_rm(run_trigger_uri)
        return

    bucket = run_payload.get("bucket", "")
    bucket_prefix = (run_payload.get("bucket_prefix") or "").strip()
    leg_summaries: list[dict[str, Any] | None] = []
    for idx, leg in enumerate(legs):
        if not isinstance(leg, dict):
            leg_summaries.append(None)
            continue
        trigger = {
            "bucket": bucket,
            "bucket_prefix": bucket_prefix,
            "project": leg.get("project", "?"),
            "bmt_id": leg.get("bmt_id", "?"),
            "run_context": run_context,
            "run_id": leg.get("run_id", "?"),
        }
        exit_code = _run_orchestrator(orchestrator_path, trigger, workspace_root)
        state = "PASS" if exit_code == 0 else "FAIL"
        print(f"  Leg {idx + 1}/{len(legs)} {trigger['project']}.{trigger['bmt_id']} -> {state}")
        run_root = _latest_run_root(workspace_root, trigger["project"], trigger["bmt_id"])
        leg_summaries.append(_load_manager_summary(run_root))

    state, description = _aggregate_verdicts_from_summaries(leg_summaries)
    print(f"  Aggregate: {state} — {description}")

    for summary in leg_summaries:
        if summary is not None:
            _update_pointer_and_cleanup(bucket_root, summary)

    if repository and sha and github_token:
        if _post_commit_status(repository, sha, state, description, None, github_token, context=status_context):
            print(f"  Posted commit status: {state}")
        else:
            print("  Could not post commit status (check GITHUB_STATUS_TOKEN)")

    gcloud_rm(run_trigger_uri)
    print(f"  Run {workflow_run_id} complete")


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    bucket_root = bucket_root_uri(args.bucket, args.bucket_prefix)
    prefix = normalize_prefix(args.bucket_prefix)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print(f"BMT Watcher started: bucket={args.bucket} prefix={prefix or '<none>'} poll={args.poll_interval_sec}s")
    print(f"Workspace: {workspace_root}")

    # Use GitHub App auth module for per-repository token resolution
    github_token_resolver = github_auth.resolve_auth_for_repository

    while not _shutdown:
        run_trigger_uris = _discover_run_triggers(bucket_root, prefix)

        if run_trigger_uris:
            print(f"[{now_iso()}] Found {len(run_trigger_uris)} run trigger(s)")
            for run_trigger_uri in run_trigger_uris:
                if _shutdown:
                    break
                _process_run_trigger(run_trigger_uri, bucket_root, workspace_root, github_token_resolver)
                if getattr(args, "exit_after_run", False):
                    print("Exit-after-run: done, exiting so VM can stop.")
                    return 0

        if not _shutdown:
            time.sleep(args.poll_interval_sec)

    print("Watcher stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
