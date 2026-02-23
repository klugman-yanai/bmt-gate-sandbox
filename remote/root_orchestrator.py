#!/usr/bin/env python3
"""Bucket-root orchestrator.

Runs one project+BMT manager invocation on the VM.
The manager script is downloaded from bucket storage at runtime.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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
    _ = parser.add_argument("--leg-index", type=int, help="Index of this leg in the workflow (for progress tracking)")
    _ = parser.add_argument("--workflow-run-id", help="Workflow run ID (for progress tracking)")
    return parser.parse_args()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _normalize_prefix(prefix: str) -> str:
    return prefix.strip("/")


def _bucket_root_uri(bucket: str, prefix: str) -> str:
    prefix = _normalize_prefix(prefix)
    if prefix:
        return f"gs://{bucket}/{prefix}"
    return f"gs://{bucket}"


def _bucket_uri(bucket_root: str, path_or_uri: str) -> str:
    if path_or_uri.startswith("gs://"):
        return path_or_uri
    return f"{bucket_root}/{path_or_uri.lstrip('/')}"


def _prune_run_dirs(run_parent: Path, keep_recent: int = 2) -> None:
    """Keep only the newest ``keep_recent`` run_* directories under one parent."""
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


def _prune_workspace(workspace_root: Path, keep_recent_per_bmt: int = 2) -> None:
    """Prune local workspace so each project/BMT keeps only current + previous run."""
    _prune_run_dirs(workspace_root, keep_recent=keep_recent_per_bmt)
    for project_dir in workspace_root.iterdir():
        if not project_dir.is_dir():
            continue
        for bmt_dir in project_dir.iterdir():
            if bmt_dir.is_dir():
                _prune_run_dirs(bmt_dir, keep_recent=keep_recent_per_bmt)


def _gcloud_cp(src: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ = subprocess.run(["gcloud", "storage", "cp", src, str(dst), "--quiet"], check=True)


def _gcloud_upload(src: Path, dst: str) -> None:
    _ = subprocess.run(["gcloud", "storage", "cp", str(src), dst, "--quiet"], check=True)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise OrchestratorError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    run_id = args.run_id.strip()
    if args.run_context in {"dev", "pr"} and not run_id:
        raise OrchestratorError("--run-id is required for dev/pr runs")
    bucket_root = _bucket_root_uri(args.bucket, args.bucket_prefix)

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    _prune_workspace(workspace_root, keep_recent_per_bmt=2)

    run_root = workspace_root / args.project / args.bmt_id / f"run_{_now_stamp()}_{os.getpid()}"
    run_root.mkdir(parents=True, exist_ok=True)
    try:
        projects_json_path = run_root / "bmt_projects.json"
        _gcloud_cp(_bucket_uri(bucket_root, "bmt_projects.json"), projects_json_path)
        projects_cfg = _load_json(projects_json_path).get("projects", {})

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
        _gcloud_cp(_bucket_uri(bucket_root, manager_rel), local_manager)
        _gcloud_cp(_bucket_uri(bucket_root, jobs_rel), local_jobs)
        local_manager.chmod(local_manager.stat().st_mode | 0o111)

        manager_summary_path = run_root / "manager_summary.json"
        command = [
            sys.executable,
            str(local_manager),
            "--bucket",
            args.bucket,
            "--bucket-prefix",
            _normalize_prefix(args.bucket_prefix),
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

        # Set up env vars for manager progress tracking
        env = os.environ.copy()
        if args.leg_index is not None and args.workflow_run_id:
            env["BMT_STATUS_BUCKET"] = args.bucket
            env["BMT_STATUS_RUN_ID"] = str(args.workflow_run_id)
            env["BMT_STATUS_LEG_INDEX"] = str(args.leg_index)

        proc = subprocess.run(command, check=False, env=env)
        manager_exit_code = proc.returncode

        manager_summary: dict[str, Any] | None = None
        if manager_summary_path.is_file():
            manager_summary = _load_json(manager_summary_path)
        manager_status = manager_summary.get("status") if isinstance(manager_summary, dict) else None
        manager_reason_code = manager_summary.get("reason_code") if isinstance(manager_summary, dict) else None
        manager_verdict_uri = manager_summary.get("ci_verdict_uri") if isinstance(manager_summary, dict) else None

        root_summary = {
            "timestamp": _now_iso(),
            "bucket": args.bucket,
            "bucket_prefix": _normalize_prefix(args.bucket_prefix),
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
        _gcloud_upload(summary_local, _bucket_uri(bucket_root, "bmt_root_results.json"))

        if args.human:
            print(json.dumps(root_summary, indent=2))
        else:
            state = "PASS" if manager_exit_code == 0 else "FAIL"
            print(f"BMT_ROOT_GATE={state} PROJECT={args.project} BMT={args.bmt_id}")

        return manager_exit_code
    finally:
        _prune_run_dirs(run_root.parent, keep_recent=2)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OrchestratorError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(2) from None
