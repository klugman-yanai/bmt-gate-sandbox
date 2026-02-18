#!/usr/bin/env python3
"""SK project BMT manager.

Runs per-file runner invocations by creating transient JSON configs from
project template and applying BMT-specific runtime overrides.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SKManagerError(RuntimeError):
    """Raised for manager execution/config errors."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SK project BMT manager")
    _ = parser.add_argument("--bucket", required=True)
    _ = parser.add_argument(
        "--bucket-prefix", default=os.environ.get("BMT_BUCKET_PREFIX", "")
    )
    _ = parser.add_argument("--project-id", required=True)
    _ = parser.add_argument("--bmt-id", required=True)
    _ = parser.add_argument("--jobs-config", required=True)
    _ = parser.add_argument("--workspace-root", default=".")
    _ = parser.add_argument(
        "--run-context", choices=["dev", "pr", "manual"], default="manual"
    )
    _ = parser.add_argument("--limit", type=int, default=int(os.environ.get("LIMIT", "0")))
    _ = parser.add_argument(
        "--max-jobs",
        type=int,
        default=int(os.environ.get("MAX_JOBS", str(os.cpu_count() or 4))),
    )
    _ = parser.add_argument("--summary-out", default="manager_summary.json")
    _ = parser.add_argument("--human", action="store_true")
    return parser.parse_args()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_prefix(prefix: str) -> str:
    return prefix.strip("/")


def _bucket_root_uri(bucket: str, prefix: str) -> str:
    p = _normalize_prefix(prefix)
    return f"gs://{bucket}/{p}" if p else f"gs://{bucket}"


def _bucket_uri(bucket_root: str, path_or_uri: str) -> str:
    if path_or_uri.startswith("gs://"):
        return path_or_uri
    return f"{bucket_root}/{path_or_uri.lstrip('/')}"


def _gcs_exists(uri: str) -> bool:
    proc = subprocess.run(
        ["gcloud", "storage", "ls", uri],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


def _gcloud_cp(src: str, dst: Path | str) -> None:
    dst_path = Path(dst) if not isinstance(dst, Path) else dst
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    _ = subprocess.run(
        ["gcloud", "storage", "cp", src, str(dst_path), "--quiet"], check=True
    )


def _gcloud_upload(src: Path, dst_uri: str) -> None:
    _ = subprocess.run(
        ["gcloud", "storage", "cp", str(src), dst_uri, "--quiet"], check=True
    )


def _gcloud_rsync(src: str, dst: Path | str) -> None:
    dst_path = Path(dst) if not isinstance(dst, Path) else dst
    dst_path.mkdir(parents=True, exist_ok=True)
    _ = subprocess.run(
        ["gcloud", "storage", "rsync", "--recursive", src, str(dst_path), "--quiet"],
        check=True,
    )


def _set_dotted(cfg: dict[str, Any], dotted_key: str, value: Any) -> None:
    cursor: dict[str, Any] = cfg
    parts = dotted_key.split(".")
    if not parts:
        return
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value


def _counter_regex(bmt_cfg: dict[str, Any]) -> re.Pattern[str]:
    parsing = bmt_cfg.get("parsing", {})
    if isinstance(parsing, dict):
        pattern = str(parsing.get("counter_pattern", "")).strip()
        if pattern:
            return re.compile(pattern)
        keyword = str(parsing.get("keyword", "NAMUH")).strip()
        return re.compile(rf"Hi {re.escape(keyword)} counter = (\\d+)")
    return re.compile(r"Hi NAMUH counter = (\\d+)")


def _read_counter(log_path: Path, counter_re: re.Pattern[str]) -> int:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = counter_re.findall(text)
    if not matches:
        return 0
    return int(matches[-1])


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SKManagerError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_result_file(
    bucket_root: str, results_prefix: str, filename: str
) -> tuple[float | None, dict[str, Any] | None]:
    uri = _bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/{filename}")
    if not _gcs_exists(uri):
        return None, None
    with tempfile.TemporaryDirectory(prefix="sk_result_file_") as tmp_dir:
        local_path = Path(tmp_dir) / filename
        _gcloud_cp(uri, local_path)
        data = _load_json(local_path)
        score = data.get("aggregate_score")
        return (float(score), data) if score is not None else (None, data)


def _gate_result(
    comparison: str,
    current_score: float,
    last_score: float | None,
    failed_count: int,
    run_context: str,
) -> dict[str, Any]:
    if failed_count > 0:
        return {
            "comparison": comparison,
            "last_score": last_score,
            "current_score": current_score,
            "passed": False,
            "reason": "runner_failures",
        }

    if last_score is None:
        if run_context == "pr":
            return {
                "comparison": comparison,
                "last_score": None,
                "current_score": current_score,
                "passed": False,
                "reason": "missing_previous_result",
            }
        return {
            "comparison": comparison,
            "last_score": None,
            "current_score": current_score,
            "passed": True,
            "reason": "bootstrap_no_previous_result",
        }

    if comparison == "gte":
        passed = current_score >= last_score
        reason = "score_gte_last" if passed else "score_below_last"
    elif comparison == "lte":
        passed = current_score <= last_score
        reason = "score_lte_last" if passed else "score_above_last"
    else:
        raise SKManagerError(f"Unsupported gate comparison: {comparison}")

    return {
        "comparison": comparison,
        "last_score": last_score,
        "current_score": current_score,
        "passed": passed,
        "reason": reason,
    }


def _resolve_status(
    gate: dict[str, Any], warning_policy: dict[str, Any]
) -> tuple[str, str]:
    reason = str(gate.get("reason", "unknown"))
    if not bool(gate.get("passed")):
        return "fail", reason

    if (
        reason == "bootstrap_no_previous_result"
        and bool(warning_policy.get("bootstrap_without_baseline", False))
    ):
        return "warning", "bootstrap_without_baseline"

    return "pass", reason


def _run_one(
    wav_path: Path,
    inputs_root: Path,
    outputs_dir: Path,
    logs_dir: Path,
    runtime_dir: Path,
    runner_path: Path,
    template_cfg: dict[str, Any],
    num_source_test: int | None,
    enable_overrides: dict[str, Any],
    counter_re: re.Pattern[str],
) -> dict[str, Any]:
    rel = wav_path.relative_to(inputs_root)
    output_path = outputs_dir / rel
    log_path = logs_dir / rel.with_suffix(rel.suffix + ".log")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = copy.deepcopy(template_cfg)
    cfg["MICS_PATH"] = str(wav_path.resolve())
    cfg["KARDOME_OUTPUT_PATH"] = str(output_path.resolve())
    if "USER_OUTPUT_PATH" in cfg:
        cfg["USER_OUTPUT_PATH"] = str(output_path.resolve())
    if num_source_test is not None:
        cfg["NUM_SOURCE_TEST"] = int(num_source_test)

    for dotted_key, value in enable_overrides.items():
        _set_dotted(cfg, dotted_key, value)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", dir=runtime_dir, delete=False
    ) as temp_file:
        json.dump(cfg, temp_file, indent=2)
        temp_path = Path(temp_file.name)

    exit_code = 1
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            proc = subprocess.run(
                [str(runner_path), str(temp_path)],
                cwd=str(runtime_dir),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
            )
            exit_code = proc.returncode
    finally:
        temp_path.unlink(missing_ok=True)

    counter = _read_counter(log_path, counter_re)
    return {
        "file": str(rel),
        "exit_code": exit_code,
        "namuh_count": counter,
        "status": "ok" if exit_code == 0 else "failed",
        "log": str(log_path),
        "output": str(output_path),
    }


def main() -> int:
    args = parse_args()
    bucket_root = _bucket_root_uri(args.bucket, args.bucket_prefix)

    jobs_cfg = _load_json(Path(args.jobs_config))
    bmts = jobs_cfg.get("bmts", {})
    bmt_cfg = bmts.get(args.bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise SKManagerError(f"Unknown BMT id: {args.bmt_id}")
    if not bool(bmt_cfg.get("enabled", True)):
        raise SKManagerError(f"BMT is disabled: {args.bmt_id}")

    run_root = Path(args.workspace_root).expanduser().resolve()
    staging_dir = run_root / "staging"
    runtime_dir = run_root / "runtime"
    inputs_dir = run_root / "inputs"
    outputs_dir = run_root / "outputs"
    logs_dir = run_root / "logs"
    results_dir = run_root / "results"
    archive_dir = run_root / "archive"
    for d in (
        staging_dir,
        runtime_dir,
        inputs_dir,
        outputs_dir,
        logs_dir,
        results_dir,
        archive_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)

    runner_uri = _bucket_uri(bucket_root, str(bmt_cfg["runner"]["uri"]))
    template_uri = _bucket_uri(bucket_root, str(bmt_cfg["template_uri"]))
    paths_cfg = bmt_cfg.get("paths", {})
    dataset_uri = _bucket_uri(bucket_root, str(paths_cfg["dataset_prefix"]))
    outputs_prefix = str(paths_cfg["outputs_prefix"]).rstrip("/")
    results_prefix = str(paths_cfg["results_prefix"]).rstrip("/")
    archive_prefix = str(paths_cfg["archive_prefix"]).rstrip("/")

    runner_path = staging_dir / Path(runner_uri).name
    template_path = staging_dir / "input_template.json"
    _gcloud_cp(runner_uri, runner_path)
    _gcloud_cp(template_uri, template_path)
    runner_path.chmod(runner_path.stat().st_mode | 0o111)

    _gcloud_rsync(dataset_uri, inputs_dir)
    wav_files = sorted(inputs_dir.rglob("*.wav"))
    if args.limit > 0:
        wav_files = wav_files[: args.limit]
    if not wav_files:
        raise SKManagerError(f"No wav files found under dataset: {dataset_uri}")

    template_cfg = _load_json(template_path)
    runtime_cfg = (
        bmt_cfg.get("runtime", {}) if isinstance(bmt_cfg.get("runtime"), dict) else {}
    )
    num_source_test = runtime_cfg.get("num_source_test")
    enable_overrides = runtime_cfg.get("enable_overrides", {})
    if not isinstance(enable_overrides, dict):
        raise SKManagerError("runtime.enable_overrides must be an object")

    counter_re = _counter_regex(bmt_cfg)

    total = len(wav_files)
    max_workers = max(1, args.max_jobs)
    file_results: list[dict[str, Any]] = []

    if args.human:
        print(f"Running {args.project_id}.{args.bmt_id} on {total} wav files")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _run_one,
                wav,
                inputs_dir,
                outputs_dir,
                logs_dir,
                runtime_dir,
                runner_path,
                template_cfg,
                int(num_source_test) if num_source_test is not None else None,
                enable_overrides,
                counter_re,
            ): wav
            for wav in wav_files
        }
        for idx, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            file_results.append(result)
            if args.human:
                print(
                    f"[{idx}/{total}] {result['file']} count={result['namuh_count']} exit={result['exit_code']}"
                )

    file_results.sort(key=lambda item: item["file"])
    failed_count = sum(1 for item in file_results if int(item["exit_code"]) != 0)
    raw_score = (
        sum(int(item["namuh_count"]) for item in file_results) / len(file_results)
        if file_results
        else 0.0
    )
    aggregate_score = raw_score

    gate_cfg = bmt_cfg.get("gate", {}) if isinstance(bmt_cfg.get("gate"), dict) else {}
    warning_policy = (
        bmt_cfg.get("warning_policy", {})
        if isinstance(bmt_cfg.get("warning_policy"), dict)
        else {}
    )
    demo_cfg = bmt_cfg.get("demo", {}) if isinstance(bmt_cfg.get("demo"), dict) else {}
    demo_force_pass = bool(demo_cfg.get("force_pass", False))
    comparison = str(gate_cfg.get("comparison", "gte"))
    # Gate against the previous run's latest.json for direct run-to-run comparison.
    last_score, previous_latest = _read_result_file(bucket_root, results_prefix, "latest.json")
    delta_from_previous = (
        (aggregate_score - last_score) if last_score is not None else None
    )
    gate = _gate_result(
        comparison, aggregate_score, last_score, failed_count, args.run_context
    )
    status, reason_code = _resolve_status(gate, warning_policy)
    if demo_force_pass and status == "fail":
        status = "pass"
        reason_code = "demo_force_pass"

    ts_iso = _now_iso()
    ts_compact = _now_stamp()
    latest_local = results_dir / "latest.json"
    archive_local = archive_dir / f"{ts_compact}.json"
    last_passing_local = results_dir / "last_passing.json"

    result = {
        "timestamp": ts_iso,
        "project_id": args.project_id,
        "bmt_id": args.bmt_id,
        "status": status,
        "reason_code": reason_code,
        "demo_force_pass": demo_force_pass,
        "aggregate_score": aggregate_score,
        "raw_aggregate_score": raw_score,
        "delta_from_previous": delta_from_previous,
        "failed_count": failed_count,
        "gate": gate,
        "file_results": file_results,
        "previous_latest": previous_latest,
        "artifacts": {
            "runner_uri": runner_uri,
            "template_uri": template_uri,
            "dataset_uri": dataset_uri,
            "results_prefix": results_prefix,
            "archive_prefix": archive_prefix,
        },
    }

    _ = latest_local.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    _ = shutil.copy2(latest_local, archive_local)

    should_update_last_passing = args.run_context == "dev" and bool(gate["passed"])
    if should_update_last_passing:
        _ = last_passing_local.write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )

    _gcloud_upload(
        latest_local, _bucket_uri(bucket_root, f"{results_prefix}/latest.json")
    )
    _gcloud_upload(
        archive_local,
        _bucket_uri(bucket_root, f"{archive_prefix}/{archive_local.name}"),
    )
    if should_update_last_passing:
        _gcloud_upload(
            last_passing_local,
            _bucket_uri(bucket_root, f"{results_prefix}/last_passing.json"),
        )

    # Upload output wav artifacts for this run to the canonical outputs prefix.
    _ = subprocess.run(
        [
            "gcloud",
            "storage",
            "rsync",
            "--recursive",
            str(outputs_dir),
            _bucket_uri(bucket_root, outputs_prefix),
            "--quiet",
        ],
        check=True,
    )

    manager_summary = {
        "timestamp": ts_iso,
        "project_id": args.project_id,
        "bmt_id": args.bmt_id,
        "run_context": args.run_context,
        "status": status,
        "reason_code": reason_code,
        "demo_force_pass": demo_force_pass,
        "passed": bool(gate["passed"]),
        "reason": gate.get("reason"),
        "aggregate_score": aggregate_score,
        "raw_aggregate_score": raw_score,
        "delta_from_previous": delta_from_previous,
        "failed_count": failed_count,
        "latest_json": str(latest_local),
    }
    _ = Path(args.summary_out).write_text(
        json.dumps(manager_summary, indent=2) + "\n", encoding="utf-8"
    )

    state = status.upper()
    print(
        f"SK_BMT_GATE={state} BMT={args.bmt_id} SCORE={aggregate_score:.3f} "
        + f"RAW={raw_score:.3f}"
    )

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SKManagerError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(2) from None
