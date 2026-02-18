#!/usr/bin/env python3
"""Collect a normalized per-matrix BMT outcome payload for CI."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


VALID_STATUSES = {"pass", "warning", "fail", "timeout"}


def _normalize_prefix(prefix: str) -> str:
    return prefix.strip("/")


def _bucket_root_uri(bucket: str, prefix: str) -> str:
    normalized = _normalize_prefix(prefix)
    return f"gs://{bucket}/{normalized}" if normalized else f"gs://{bucket}"


def _bucket_uri(bucket_root: str, rel: str) -> str:
    return f"{bucket_root}/{rel.lstrip('/')}"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_check(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return proc.returncode, (proc.stderr or proc.stdout or "").strip()


def _resolve_results_prefix(project: str, bmt_id: str) -> str:
    root = Path("remote")
    projects_cfg = _read_json(root / "bmt_projects.json").get("projects", {})
    project_cfg = projects_cfg.get(project)
    if not isinstance(project_cfg, dict):
        raise ValueError(f"Unknown project: {project}")

    jobs_rel = str(project_cfg.get("jobs_config", "")).strip()
    if not jobs_rel:
        raise ValueError(f"Project {project} missing jobs_config")

    jobs_cfg = _read_json(root / jobs_rel)
    bmt_cfg = jobs_cfg.get("bmts", {}).get(bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise ValueError(f"Unknown bmt_id: {project}.{bmt_id}")

    paths_cfg = bmt_cfg.get("paths", {})
    if not isinstance(paths_cfg, dict):
        raise ValueError(f"BMT {project}.{bmt_id} paths must be an object")

    results_prefix = str(paths_cfg.get("results_prefix", "")).strip().rstrip("/")
    if not results_prefix:
        raise ValueError(f"BMT {project}.{bmt_id} missing paths.results_prefix")
    return results_prefix


def _download_latest(bucket_root: str, results_prefix: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    latest_uri = _bucket_uri(bucket_root, f"{results_prefix}/latest.json")
    with tempfile.TemporaryDirectory(prefix="bmt_outcome_") as tmp_dir:
        local_path = Path(tmp_dir) / "latest.json"
        rc, err = _run_check(
            ["gcloud", "storage", "cp", latest_uri, str(local_path), "--quiet"]
        )
        if rc != 0:
            return None, latest_uri, err
        return _read_json(local_path), latest_uri, None


def _normalize_status(raw: str) -> str | None:
    value = str(raw or "").strip().lower()
    return value if value in VALID_STATUSES else None


def _derive_from_latest(latest: dict[str, Any]) -> tuple[str, str]:
    status = _normalize_status(str(latest.get("status", "")))
    reason_code = str(
        latest.get("reason_code")
        or latest.get("gate", {}).get("reason")
        or "unknown"
    )

    if status:
        return status, reason_code

    gate = latest.get("gate", {})
    if isinstance(gate, dict):
        gate_passed = gate.get("passed")
        gate_reason = str(gate.get("reason") or "gate_unknown")
        if gate_passed is True:
            if gate_reason == "bootstrap_no_previous_result":
                return "warning", "bootstrap_without_baseline"
            return "pass", gate_reason
        if gate_passed is False:
            return "fail", gate_reason

    return "fail", "missing_status"


def build_outcome(
    bucket: str,
    bucket_prefix: str,
    project: str,
    bmt_id: str,
    trigger_result: str,
    trigger_exit: int,
) -> dict[str, Any]:
    bucket_root = _bucket_root_uri(bucket, bucket_prefix)

    outcome: dict[str, Any] = {
        "project": project,
        "bmt_id": bmt_id,
        "status": "fail",
        "reason_code": "unknown",
        "trigger_result": trigger_result,
        "trigger_exit": trigger_exit,
        "bucket": bucket,
        "bucket_prefix": _normalize_prefix(bucket_prefix),
        "gate": None,
        "scores": {},
        "latest_uri": None,
        "collection_error": None,
    }

    if trigger_result == "trigger_timeout":
        outcome["status"] = "timeout"
        outcome["reason_code"] = "trigger_timeout"
        return outcome

    if trigger_result == "trigger_fail":
        outcome["status"] = "fail"
        outcome["reason_code"] = "trigger_failed"

    try:
        results_prefix = _resolve_results_prefix(project, bmt_id)
        latest, latest_uri, latest_err = _download_latest(bucket_root, results_prefix)
        outcome["latest_uri"] = latest_uri

        if latest_err:
            outcome["collection_error"] = latest_err
            if trigger_result == "trigger_pass":
                outcome["status"] = "fail"
                outcome["reason_code"] = "latest_missing_after_trigger"
            return outcome

        if not isinstance(latest, dict):
            outcome["collection_error"] = "latest.json is not a JSON object"
            if trigger_result == "trigger_pass":
                outcome["status"] = "fail"
                outcome["reason_code"] = "invalid_latest_json"
            return outcome

        latest_status, reason_code = _derive_from_latest(latest)
        if trigger_result == "trigger_pass":
            outcome["status"] = latest_status
            outcome["reason_code"] = reason_code
        else:
            outcome["reason_code"] = reason_code

        outcome["gate"] = latest.get("gate")
        outcome["scores"] = {
            "aggregate_score": latest.get("aggregate_score"),
            "raw_aggregate_score": latest.get("raw_aggregate_score"),
            "delta_from_previous": latest.get("delta_from_previous"),
            "score_bias": latest.get("score_bias"),
        }
        return outcome
    except Exception as exc:  # noqa: BLE001 - keep artifact generation robust in CI
        outcome["collection_error"] = str(exc)
        if trigger_result == "trigger_pass":
            outcome["status"] = "fail"
            outcome["reason_code"] = "collection_error"
        return outcome


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("bucket")
    _ = parser.add_argument("bucket_prefix")
    _ = parser.add_argument("project")
    _ = parser.add_argument("bmt_id")
    _ = parser.add_argument("trigger_result")
    _ = parser.add_argument("trigger_exit", type=int)
    _ = parser.add_argument("output_path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outcome = build_outcome(
        bucket=args.bucket,
        bucket_prefix=args.bucket_prefix,
        project=args.project,
        bmt_id=args.bmt_id,
        trigger_result=args.trigger_result,
        trigger_exit=args.trigger_exit,
    )

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")

    print(
        f"BMT_OUTCOME project={outcome['project']} bmt={outcome['bmt_id']} "
        f"status={outcome['status']} reason={outcome['reason_code']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
