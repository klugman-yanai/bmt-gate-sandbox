#!/usr/bin/env python3
"""Bucket-root orchestrator.

Runs one project+BMT manager invocation on the VM.
The manager script is downloaded from bucket storage at runtime.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR / "lib"))
from gcs import (  # type: ignore[import-not-found]  # noqa: E402
    bucket_root_uri,
    bucket_uri,
    gcloud_cp,
    gcloud_upload,
    load_json,
    normalize_prefix,
    now_iso,
    now_stamp,
)


class OrchestratorError(RuntimeError):
    """Raised for invalid orchestration state."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one project+BMT manager from bucket")
    _ = parser.add_argument("--bucket", required=True)
    _ = parser.add_argument("--bucket-prefix", default=os.environ.get("BMT_BUCKET_PREFIX", ""))
    _ = parser.add_argument("--project", required=True)
    _ = parser.add_argument("--bmt-id", required=True)
    _ = parser.add_argument("--run-context", choices=["dev", "pr", "manual"], default="manual")
    _ = parser.add_argument("--run-id", default="")
    _ = parser.add_argument("--workspace-root", default=str(Path("~/sk_runtime").expanduser()))
    _ = parser.add_argument("--summary-out", default="bmt_root_results.json")
    _ = parser.add_argument("--human", action="store_true")
    return parser.parse_args()


def _prune_workspace(workspace_root: Path, max_age_days: int = 3, keep_recent: int = 5) -> None:
    """Prune old run_* workspace directories.

    Keeps the ``keep_recent`` most recently modified run_* directories regardless of age,
    then removes any remaining run_* directories older than ``max_age_days`` days.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_days * 86400)
    run_dirs: list[tuple[float, Path]] = []
    for candidate in workspace_root.rglob("run_*"):
        if candidate.is_dir():
            with contextlib.suppress(OSError):
                run_dirs.append((candidate.stat().st_mtime, candidate))

    # Sort newest-first; keep the first `keep_recent`, prune old ones beyond that.
    run_dirs.sort(key=lambda x: x[0], reverse=True)
    for idx, (mtime, d) in enumerate(run_dirs):
        if idx < keep_recent:
            continue
        if mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    args = parse_args()
    run_id = args.run_id.strip()
    if args.run_context in {"dev", "pr"} and not run_id:
        raise OrchestratorError("--run-id is required for dev/pr runs")
    bucket_root = bucket_root_uri(args.bucket, args.bucket_prefix)

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    _prune_workspace(workspace_root)

    run_root = workspace_root / args.project / args.bmt_id / f"run_{now_stamp()}_{os.getpid()}"
    run_root.mkdir(parents=True, exist_ok=True)

    projects_json_path = run_root / "bmt_projects.json"
    gcloud_cp(bucket_uri(bucket_root, "bmt_projects.json"), projects_json_path)
    projects_cfg = load_json(projects_json_path).get("projects", {})

    project_cfg = projects_cfg.get(args.project)
    if not isinstance(project_cfg, dict):
        raise OrchestratorError(f"Missing project config: {args.project}")
    if not bool(project_cfg.get("enabled", True)):
        raise OrchestratorError(f"Project is disabled: {args.project}")

    manager_rel = str(project_cfg.get("manager_script", "")).strip()
    jobs_rel = str(project_cfg.get("jobs_config", "")).strip()
    if not manager_rel or not jobs_rel:
        raise OrchestratorError(f"Project '{args.project}' must define manager_script and jobs_config")

    local_manager = run_root / manager_rel
    local_jobs = run_root / jobs_rel
    gcloud_cp(bucket_uri(bucket_root, manager_rel), local_manager)
    gcloud_cp(bucket_uri(bucket_root, jobs_rel), local_jobs)
    local_manager.chmod(local_manager.stat().st_mode | 0o111)

    manager_summary_path = run_root / "manager_summary.json"
    command = [
        sys.executable,
        str(local_manager),
        "--bucket",
        args.bucket,
        "--bucket-prefix",
        normalize_prefix(args.bucket_prefix),
        "--project-id",
        args.project,
        "--bmt-id",
        args.bmt_id,
        "--jobs-config",
        str(local_jobs),
        "--workspace-root",
        str(run_root),
        "--run-context",
        args.run_context,
        "--run-id",
        run_id,
        "--summary-out",
        str(manager_summary_path),
    ]
    if args.human:
        command.append("--human")

    proc = subprocess.run(command, check=False)
    manager_exit_code = proc.returncode

    manager_summary: dict[str, Any] | None = None
    if manager_summary_path.is_file():
        manager_summary = load_json(manager_summary_path)
    manager_status = manager_summary.get("status") if isinstance(manager_summary, dict) else None
    manager_reason_code = manager_summary.get("reason_code") if isinstance(manager_summary, dict) else None
    manager_verdict_uri = manager_summary.get("ci_verdict_uri") if isinstance(manager_summary, dict) else None

    root_summary = {
        "timestamp": now_iso(),
        "bucket": args.bucket,
        "bucket_prefix": normalize_prefix(args.bucket_prefix),
        "project": args.project,
        "bmt_id": args.bmt_id,
        "run_context": args.run_context,
        "run_id": run_id,
        "workspace": str(run_root),
        "manager_exit_code": manager_exit_code,
        "passed": manager_exit_code == 0,
        "manager_status": manager_status,
        "manager_reason_code": manager_reason_code,
        "manager_verdict_uri": manager_verdict_uri,
        "manager_summary": manager_summary,
    }

    summary_local = run_root / args.summary_out
    summary_local.write_text(json.dumps(root_summary, indent=2) + "\n", encoding="utf-8")
    gcloud_upload(summary_local, bucket_uri(bucket_root, "bmt_root_results.json"))

    if args.human:
        print(json.dumps(root_summary, indent=2))
    else:
        state = "PASS" if manager_exit_code == 0 else "FAIL"
        print(f"BMT_ROOT_GATE={state} PROJECT={args.project} BMT={args.bmt_id}")

    return manager_exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OrchestratorError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(2) from None
