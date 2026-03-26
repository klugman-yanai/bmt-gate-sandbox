#!/usr/bin/env python3
"""Bucket-root orchestrator.

Runs one project+BMT manager invocation on the VM.
The manager script is downloaded from bucket storage at runtime.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from google.api_core import exceptions as gcs_exceptions
from google.cloud import storage as gcs_storage

from backend.config.constants import EXECUTABLE_MODE
from backend.utils import _bucket_uri, _code_bucket_root, _now_iso, _now_stamp, _runtime_bucket_root


def _get_keep_recent_default() -> int:
    try:
        import config.bmt_config as _m
    except ImportError:
        import backend.config.bmt_config as _m
    return int(_m.TRIGGER_METADATA_KEEP_RECENT)


KEEP_RECENT_DEFAULT: int = _get_keep_recent_default()


class OrchestratorError(RuntimeError):
    """Raised for invalid orchestration state."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one project+BMT manager from bucket")
    _ = parser.add_argument("--bucket", required=True)
    _ = parser.add_argument("--project", required=True)
    _ = parser.add_argument("--bmt-id", required=True)
    _ = parser.add_argument("--run-context", choices=["dev", "pr", "manual"], default="manual")
    _ = parser.add_argument("--run-id", default="")
    _ = parser.add_argument("--workspace-root", default=os.environ.get("BMT_WORKSPACE_ROOT", ""))
    _ = parser.add_argument("--summary-out", default="bmt_root_results.json")
    _ = parser.add_argument("--human", action="store_true")
    _ = parser.add_argument("--leg-index", type=int, help="Index of this leg in the workflow (for progress tracking)")
    _ = parser.add_argument("--workflow-run-id", help="Workflow run ID (for progress tracking)")
    return parser.parse_args()


def _resolve_workspace_root(raw: str) -> Path:
    if raw.strip():
        return Path(raw).expanduser().resolve()
    preferred = Path("~/bmt_workspace").expanduser()
    legacy = Path("~/sk_runtime").expanduser()
    if legacy.exists() and not preferred.exists():
        return legacy.resolve()
    return preferred.resolve()


def _prune_run_dirs(run_parent: Path, keep_recent: int = KEEP_RECENT_DEFAULT) -> None:
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


def _prune_workspace(workspace_root: Path, keep_recent_per_bmt: int = KEEP_RECENT_DEFAULT) -> None:
    """Prune local workspace so each project/BMT keeps only current + previous run."""
    _prune_run_dirs(workspace_root, keep_recent=keep_recent_per_bmt)
    for project_dir in workspace_root.iterdir():
        if not project_dir.is_dir():
            continue
        for bmt_dir in project_dir.iterdir():
            if bmt_dir.is_dir():
                _prune_run_dirs(bmt_dir, keep_recent=keep_recent_per_bmt)


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a GCS URI: {uri!r}")
    parts = uri[len("gs://") :].split("/", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


_gcs_client: gcs_storage.Client | None = None


def _get_gcs_client() -> gcs_storage.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = gcs_storage.Client()
    return _gcs_client


def _gcloud_cp(src: str, dst: Path) -> None:
    """Download a single object from GCS to local path (SDK-based)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    bucket_name, blob_name = _parse_gcs_uri(src)
    blob = _get_gcs_client().bucket(bucket_name).blob(blob_name)
    try:
        blob.download_to_filename(str(dst))
    except gcs_exceptions.NotFound:
        raise OrchestratorError(f"GCS object not found: {src}") from None
    except (gcs_exceptions.GoogleAPICallError, OSError):
        logging.getLogger(__name__).exception("Failed to download %s", src)
        raise


def _gcloud_upload(src: Path, dst: str) -> None:
    """Upload local file to GCS (SDK-based)."""
    bucket_name, blob_name = _parse_gcs_uri(dst)
    ct = "application/json" if src.suffix.lower() == ".json" else None
    try:
        _get_gcs_client().bucket(bucket_name).blob(blob_name).upload_from_filename(str(src), content_type=ct)
    except (gcs_exceptions.GoogleAPICallError, OSError):
        logging.getLogger(__name__).exception("Failed to upload %s -> %s", src, dst)
        raise


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise OrchestratorError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _manager_rel_path(project: str) -> str:
    return f"projects/{project}/bmt_manager.py"


def _jobs_rel_path(project: str) -> str:
    return f"projects/{project}/bmt_jobs.json"


def _validate_jobs_config(jobs_payload: dict[str, Any], *, project: str, bmt_id: str, jobs_path: Path) -> None:
    if not isinstance(jobs_payload, dict):
        raise OrchestratorError(f"Invalid jobs schema in {jobs_path}: expected JSON object")
    bmts = jobs_payload.get("bmts")
    if not isinstance(bmts, dict):
        raise OrchestratorError(f"Invalid jobs schema in {jobs_path}: missing object key 'bmts'")

    bmt_cfg = bmts.get(bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise OrchestratorError(f"BMT id '{bmt_id}' is not defined for project '{project}' in {jobs_path}")

    if bmt_cfg.get("enabled", True) is False:
        raise OrchestratorError(f"BMT id '{bmt_id}' is disabled for project '{project}' in {jobs_path}")


def main() -> int:
    args = parse_args()
    run_id = args.run_id.strip()
    if args.run_context in {"dev", "pr"} and not run_id:
        raise OrchestratorError("--run-id is required for dev/pr runs")
    code_bucket_root = _code_bucket_root(args.bucket)
    runtime_bucket_root = _runtime_bucket_root(args.bucket)

    workspace_root = _resolve_workspace_root(args.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    _prune_workspace(workspace_root, keep_recent_per_bmt=KEEP_RECENT_DEFAULT)

    run_root = workspace_root / args.project / args.bmt_id / f"run_{_now_stamp()}_{os.getpid()}"
    run_root.mkdir(parents=True, exist_ok=True)
    try:
        manager_rel = _manager_rel_path(args.project)
        jobs_rel = _jobs_rel_path(args.project)

        local_manager = run_root / manager_rel
        local_jobs = run_root / jobs_rel
        _gcloud_cp(_bucket_uri(code_bucket_root, manager_rel), local_manager)
        _gcloud_cp(_bucket_uri(code_bucket_root, jobs_rel), local_jobs)
        try:
            jobs_payload = _load_json(local_jobs)
        except json.JSONDecodeError as exc:
            raise OrchestratorError(f"Invalid JSON in {local_jobs}: {exc}") from exc
        _validate_jobs_config(jobs_payload, project=args.project, bmt_id=args.bmt_id, jobs_path=local_jobs)

        local_manager.chmod(local_manager.stat().st_mode | EXECUTABLE_MODE)

        manager_summary_path = run_root / "manager_summary.json"
        command = [
            sys.executable,
            str(local_manager),
            "--bucket",
            args.bucket,
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
            env["BMT_STATUS_RUNTIME_PREFIX"] = "runtime"
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
        _gcloud_upload(summary_local, _bucket_uri(runtime_bucket_root, "bmt_root_results.json"))

        if args.human:
            pass
        else:
            pass

        return manager_exit_code
    finally:
        _prune_run_dirs(run_root.parent, keep_recent=KEEP_RECENT_DEFAULT)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OrchestratorError:
        raise SystemExit(2) from None
