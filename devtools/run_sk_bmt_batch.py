#!/usr/bin/env -S uv run --script
"""Local SK batch runner (config-first).

Reads BMT behavior from remote/sk/config/bmt_jobs.json and runs kardome_runner
once per wav by creating a transient JSON from the configured template.
CLI flags act as explicit overrides.
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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Ensure devtools dir is on path when run as script so time_utils is importable.
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))
from time_utils import now_iso, now_stamp

PRINT_LOCK = threading.Lock()
DEFAULT_COUNTER_PATTERN = r"Hi NAMUH counter = (\d+)"
TIMESTAMP_NOISE_RE = re.compile(r"^\[\d{2}:\d{2}\.\d{3}\]\s*$")


@dataclass(slots=True)
class FileResult:
    file: str
    exit_code: int
    namuh_count: int
    status: str
    log: str
    output: str
    error: str = ""


@dataclass(slots=True)
class ResolvedConfig:
    jobs_config_path: Path
    bmt_id: str
    bmt_cfg: dict[str, Any]
    runner_path: Path
    template_path: Path
    dataset_root: Path
    output_root: Path
    results_dir: Path
    archive_dir: Path
    log_root: Path
    comparison: str
    num_source_test: int | None
    enable_overrides: dict[str, Any]
    warning_policy: dict[str, Any]
    counter_re: re.Pattern[str]


def ts_print(*args: object, **kwargs: Any) -> None:
    with PRINT_LOCK:
        print(*args, **kwargs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local SK batch over wav files")
    _ = parser.add_argument(
        "--jobs-config",
        default="remote/sk/config/bmt_jobs.json",
        help="BMT jobs config JSON path (source of truth)",
    )
    _ = parser.add_argument(
        "--bmt-id",
        default="false_reject_namuh",
        help="BMT id under bmts.<bmt_id> in jobs config",
    )
    _ = parser.add_argument(
        "--project-id",
        default="sk",
        help="Project id for result metadata",
    )
    _ = parser.add_argument(
        "--run-context",
        default="manual",
        choices=["manual", "dev", "pr"],
        help="Run context",
    )
    _ = parser.add_argument(
        "--sk-root",
        default="remote/sk",
        help="SK root folder used for resolving sk/... contract paths",
    )
    _ = parser.add_argument(
        "--results-subdir",
        default="false_rejects",
        help="Fallback subdir when config paths are missing",
    )
    _ = parser.add_argument(
        "--runner",
        default="",
        help="Runner path override",
    )
    _ = parser.add_argument(
        "--template",
        default="",
        help="Template path override",
    )
    _ = parser.add_argument(
        "--dataset-root",
        default="",
        help="Dataset root override",
    )
    _ = parser.add_argument(
        "--output-root",
        default="",
        help="Output root override",
    )
    _ = parser.add_argument(
        "--log-root",
        default="",
        help="Log root override",
    )
    _ = parser.add_argument(
        "--comparison",
        default="",
        choices=["", "gte", "lte"],
        help="Gate comparison override",
    )
    _ = parser.add_argument(
        "--run-root",
        default="local_batch",
        help="Run scratch root (temp json + summary)",
    )
    _ = parser.add_argument("--limit", type=int, default=0, help="Limit wav files")
    _ = parser.add_argument("--workers", type=int, default=1, help="Parallel workers")
    _ = parser.add_argument(
        "--timeout-sec",
        type=int,
        default=0,
        help="Per-file timeout (0 disables timeout)",
    )
    _ = parser.add_argument(
        "--summary-out",
        default="summary.json",
        help="Summary filename under run-root",
    )
    _ = parser.add_argument(
        "--set-ref-to-mics",
        action="store_true",
        help="Force REF_PATH = MICS_PATH per invocation",
    )
    _ = parser.add_argument(
        "--num-source-test",
        type=int,
        default=None,
        help="Override NUM_SOURCE_TEST",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def maybe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"

    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        delete=False,
        encoding="utf-8",
    ) as tf:
        tf.write(text)
        temp_path = Path(tf.name)
    temp_path.replace(path)


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
        if keyword:
            return re.compile(rf"Hi {re.escape(keyword)} counter = (\d+)")
    return re.compile(DEFAULT_COUNTER_PATTERN)


def _resolve_local_path(path_or_contract: str, sk_root: Path) -> Path:
    raw = str(path_or_contract).strip()
    if not raw:
        raise ValueError("Empty path is not allowed")
    if raw.startswith("gs://"):
        raise ValueError(f"Local script requires local path, not gs:// URI: {raw}")

    p = Path(raw).expanduser()
    if p.is_absolute():
        return p.resolve()
    if raw.startswith("sk/"):
        return (sk_root.parent / raw).resolve()
    return (Path.cwd() / p).resolve()


def _resolve_config(args: argparse.Namespace) -> ResolvedConfig:
    sk_root = Path(args.sk_root).expanduser().resolve()
    jobs_config_path = Path(args.jobs_config).expanduser().resolve()
    jobs_cfg = load_json(jobs_config_path)
    bmts = jobs_cfg.get("bmts", {})
    if not isinstance(bmts, dict):
        raise ValueError("jobs config must contain object key: bmts")

    bmt_cfg = bmts.get(args.bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise ValueError(f"Unknown bmt id: {args.bmt_id}")
    if not bool(bmt_cfg.get("enabled", True)):
        raise ValueError(f"BMT is disabled in config: {args.bmt_id}")

    paths_cfg = bmt_cfg.get("paths", {})
    runtime_cfg = bmt_cfg.get("runtime", {})
    gate_cfg = bmt_cfg.get("gate", {})
    warning_policy = bmt_cfg.get("warning_policy", {})
    runner_cfg = bmt_cfg.get("runner", {})

    if not isinstance(paths_cfg, dict):
        raise ValueError("bmt paths must be an object")
    if not isinstance(runtime_cfg, dict):
        raise ValueError("bmt runtime must be an object")
    if not isinstance(gate_cfg, dict):
        raise ValueError("bmt gate must be an object")
    if not isinstance(warning_policy, dict):
        raise ValueError("bmt warning_policy must be an object")

    runner_contract = ""
    if isinstance(runner_cfg, dict):
        runner_contract = str(runner_cfg.get("uri", "")).strip()
    elif isinstance(runner_cfg, str):
        runner_contract = runner_cfg.strip()

    template_contract = str(bmt_cfg.get("template_uri", "")).strip()
    dataset_contract = str(paths_cfg.get("dataset_prefix", "")).strip()
    outputs_contract = str(paths_cfg.get("outputs_prefix", "")).strip()
    results_contract = str(paths_cfg.get("results_prefix", "")).strip()
    # archive_prefix removed from VM config; local runner keeps it for debugging
    archive_contract = str(paths_cfg.get("archive_prefix", "")).strip()
    logs_contract = str(paths_cfg.get("logs_prefix", "")).strip()

    runner_raw = args.runner.strip() or runner_contract or "sk/runners/kardome_runner"
    template_raw = args.template.strip() or template_contract or "sk/config/input_template.json"
    dataset_raw = args.dataset_root.strip() or dataset_contract or f"sk/inputs/{args.results_subdir}"
    output_raw = args.output_root.strip() or outputs_contract or f"sk/outputs/{args.results_subdir}"
    results_raw = results_contract or f"sk/results/{args.results_subdir}"
    archive_raw = archive_contract or "sk/results/archive"

    runner_path = _resolve_local_path(runner_raw, sk_root)
    template_path = _resolve_local_path(template_raw, sk_root)
    dataset_root = _resolve_local_path(dataset_raw, sk_root)
    output_root = _resolve_local_path(output_raw, sk_root)
    results_dir = _resolve_local_path(results_raw, sk_root)
    archive_dir = _resolve_local_path(archive_raw, sk_root)

    if args.log_root.strip():
        log_root = _resolve_local_path(args.log_root, sk_root)
    elif logs_contract:
        logs_base = _resolve_local_path(logs_contract, sk_root)
        log_root = logs_base if logs_base.name == "latest" else (logs_base / "latest")
    else:
        log_root = results_dir.parent / "logs" / results_dir.name / "latest"

    comparison = args.comparison.strip() or str(gate_cfg.get("comparison", "gte"))
    if comparison not in {"gte", "lte"}:
        raise ValueError(f"Unsupported comparison: {comparison}")

    num_source_test_raw = (
        args.num_source_test if args.num_source_test is not None else runtime_cfg.get("num_source_test")
    )
    num_source_test = int(num_source_test_raw) if num_source_test_raw is not None else None

    enable_overrides = runtime_cfg.get("enable_overrides", {})
    if not isinstance(enable_overrides, dict):
        raise ValueError("runtime.enable_overrides must be an object")

    return ResolvedConfig(
        jobs_config_path=jobs_config_path,
        bmt_id=args.bmt_id,
        bmt_cfg=bmt_cfg,
        runner_path=runner_path,
        template_path=template_path,
        dataset_root=dataset_root,
        output_root=output_root,
        results_dir=results_dir,
        archive_dir=archive_dir,
        log_root=log_root.resolve(),
        comparison=comparison,
        num_source_test=num_source_test,
        enable_overrides=enable_overrides,
        warning_policy=warning_policy,
        counter_re=_counter_regex(bmt_cfg),
    )


def compute_gate(
    comparison: str,
    current_score: float,
    previous_score: float | None,
    failed_count: int,
    run_context: str = "manual",
) -> dict[str, Any]:
    if failed_count > 0:
        return {
            "comparison": comparison,
            "last_score": previous_score,
            "current_score": current_score,
            "passed": False,
            "reason": "runner_failures",
        }
    if previous_score is None:
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
        passed = current_score >= previous_score
        reason = "score_gte_last" if passed else "score_below_last"
    else:
        passed = current_score <= previous_score
        reason = "score_lte_last" if passed else "score_above_last"
    return {
        "comparison": comparison,
        "last_score": previous_score,
        "current_score": current_score,
        "passed": passed,
        "reason": reason,
    }


def resolve_status(gate: dict[str, Any], warning_policy: dict[str, Any]) -> tuple[str, str]:
    reason = str(gate.get("reason", "unknown"))
    if not bool(gate.get("passed")):
        return "fail", reason
    if reason == "bootstrap_no_previous_result" and bool(warning_policy.get("bootstrap_without_baseline", False)):
        return "warning", "bootstrap_without_baseline"
    return "pass", reason


def read_counter(log_path: Path, counter_re: re.Pattern[str]) -> int:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = counter_re.findall(text)
    if not matches:
        return 0
    return int(matches[-1])


def _filter_runner_output(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if TIMESTAMP_NOISE_RE.match(line):
            continue
        kept.append(line)
    return "\n".join(kept) + ("\n" if kept else "")


def run_one(
    wav_path: Path,
    dataset_root: Path,
    runner_path: Path,
    template_cfg: dict[str, Any],
    output_root: Path,
    log_root: Path,
    run_root: Path,
    timeout_sec: int,
    set_ref_to_mics: bool,
    num_source_test: int | None,
    enable_overrides: dict[str, Any],
    counter_re: re.Pattern[str],
) -> FileResult:
    rel = wav_path.relative_to(dataset_root)
    out_path = output_root / rel
    log_path = log_root / rel.with_suffix(rel.suffix + ".log")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = copy.deepcopy(template_cfg)
    cfg["MICS_PATH"] = str(wav_path.resolve())
    cfg["KARDOME_OUTPUT_PATH"] = str(out_path.resolve())
    if "USER_OUTPUT_PATH" in cfg:
        cfg["USER_OUTPUT_PATH"] = str(out_path.resolve())
    if set_ref_to_mics:
        cfg["REF_PATH"] = str(wav_path.resolve())
    if num_source_test is not None:
        cfg["NUM_SOURCE_TEST"] = int(num_source_test)
    for dotted_key, value in enable_overrides.items():
        _set_dotted(cfg, str(dotted_key), value)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        dir=run_root,
        delete=False,
        encoding="utf-8",
    ) as tf:
        json.dump(cfg, tf, indent=2)
        tmp_json = Path(tf.name)

    exit_code = 1
    err = ""
    try:
        proc = subprocess.run(
            [str(runner_path), str(tmp_json)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=(timeout_sec if timeout_sec > 0 else None),
            text=True,
            errors="replace",
        )
        filtered = _filter_runner_output(proc.stdout or "")
        log_path.write_text(filtered, encoding="utf-8")
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        err = f"timeout_after_{timeout_sec}s"
        partial = str(exc.stdout or "")
        log_path.write_text(_filter_runner_output(partial), encoding="utf-8")
    except Exception as exc:
        exit_code = 1
        err = str(exc)
    finally:
        tmp_json.unlink(missing_ok=True)

    counter = read_counter(log_path, counter_re) if log_path.is_file() else 0
    return FileResult(
        file=str(rel),
        exit_code=exit_code,
        namuh_count=counter,
        status="ok" if exit_code == 0 else "failed",
        log=str(log_path),
        output=str(out_path),
        error=err,
    )


def main() -> int:
    args = parse_args()
    run_root = Path(args.run_root).expanduser().resolve()
    sk_root = Path(args.sk_root).expanduser().resolve()
    cfg = _resolve_config(args)

    if not cfg.runner_path.is_file():
        print(f"::error::Runner not found: {cfg.runner_path}", file=sys.stderr)
        return 2
    if not os.access(cfg.runner_path, os.X_OK):
        print(f"::error::Runner is not executable: {cfg.runner_path}", file=sys.stderr)
        return 2
    if not cfg.dataset_root.is_dir():
        print(f"::error::Dataset root not found: {cfg.dataset_root}", file=sys.stderr)
        return 2

    workers = max(1, min(int(args.workers), 256))
    run_root.mkdir(parents=True, exist_ok=True)
    cfg.output_root.mkdir(parents=True, exist_ok=True)
    if cfg.log_root.exists():
        shutil.rmtree(cfg.log_root)
    cfg.log_root.mkdir(parents=True, exist_ok=True)

    template_cfg = load_json(cfg.template_path)
    wav_files = sorted(cfg.dataset_root.rglob("*.wav"))
    if args.limit and args.limit > 0:
        wav_files = wav_files[: args.limit]
    if not wav_files:
        print(f"::error::No wav files found under {cfg.dataset_root}", file=sys.stderr)
        return 2

    ts_print(f"Jobs config: {cfg.jobs_config_path}")
    ts_print(f"BMT id: {cfg.bmt_id}")
    ts_print(f"Runner: {cfg.runner_path}")
    ts_print(f"Template: {cfg.template_path}")
    ts_print(f"Dataset root: {cfg.dataset_root}")
    ts_print(f"SK root: {sk_root}")
    ts_print(f"Wav files: {len(wav_files)}")
    ts_print(f"Workers: {workers}")

    results: list[FileResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                run_one,
                wav,
                cfg.dataset_root,
                cfg.runner_path,
                template_cfg,
                cfg.output_root,
                cfg.log_root,
                run_root,
                int(args.timeout_sec),
                bool(args.set_ref_to_mics),
                cfg.num_source_test,
                cfg.enable_overrides,
                cfg.counter_re,
            ): wav
            for wav in wav_files
        }
        total = len(futures)
        for idx, fut in enumerate(as_completed(futures), start=1):
            res = fut.result()
            results.append(res)
            ts_print(f"[{idx}/{total}] rc={res.exit_code} namuh={res.namuh_count} file={res.file}")

    results.sort(key=lambda x: x.file)
    ok = [r for r in results if r.exit_code == 0]
    failed = [r for r in results if r.exit_code != 0]
    avg = (sum(r.namuh_count for r in results) / len(results)) if results else 0.0

    ts_iso = now_iso()
    ts_compact = now_stamp()
    latest_path = cfg.results_dir / "latest.json"
    last_passing_path = cfg.results_dir / "last_passing.json"
    archive_path = cfg.archive_dir / f"{ts_compact}.json"
    logs_archive_path = cfg.log_root.parent / "archive" / ts_compact
    project_summary_path = sk_root / "results" / "sk_bmt_results.json"

    previous_latest = maybe_load_json(latest_path)
    previous_score: float | None = None
    if isinstance(previous_latest, dict) and previous_latest.get("aggregate_score") is not None:
        try:
            previous_score = float(previous_latest["aggregate_score"])
        except Exception:
            previous_score = None

    gate = compute_gate(cfg.comparison, float(avg), previous_score, len(failed), args.run_context)
    status, reason_code = resolve_status(gate, cfg.warning_policy)

    result_doc = {
        "timestamp": ts_iso,
        "project_id": args.project_id,
        "bmt_id": args.bmt_id,
        "run_context": args.run_context,
        "status": status,
        "reason_code": reason_code,
        "aggregate_score": avg,
        "raw_aggregate_score": avg,
        "failed_count": len(failed),
        "gate": gate,
        "config": {
            "jobs_config": str(cfg.jobs_config_path),
            "runner": str(cfg.runner_path),
            "template": str(cfg.template_path),
            "dataset_root": str(cfg.dataset_root),
            "output_root": str(cfg.output_root),
            "results_dir": str(cfg.results_dir),
            "archive_dir": str(cfg.archive_dir),
            "log_root": str(cfg.log_root),
            "num_source_test": cfg.num_source_test,
            "enable_overrides": cfg.enable_overrides,
            "comparison": cfg.comparison,
        },
        "file_results": [asdict(r) for r in results],
    }

    write_json(latest_path, result_doc)
    write_json(archive_path, result_doc)
    if args.run_context == "dev" and bool(gate["passed"]):
        write_json(last_passing_path, result_doc)

    logs_archive_path.parent.mkdir(parents=True, exist_ok=True)
    if logs_archive_path.exists():
        shutil.rmtree(logs_archive_path)
    shutil.copytree(cfg.log_root, logs_archive_path)

    summary = {
        "timestamp": ts_iso,
        "project_id": args.project_id,
        "bmt_id": args.bmt_id,
        "run_context": args.run_context,
        "runner": str(cfg.runner_path),
        "template": str(cfg.template_path),
        "dataset_root": str(cfg.dataset_root),
        "sk_root": str(sk_root),
        "jobs_config": str(cfg.jobs_config_path),
        "workers": workers,
        "total_files": len(results),
        "ok_files": len(ok),
        "failed_files": len(failed),
        "aggregate_score": avg,
        "status": status,
        "reason_code": reason_code,
        "latest_json": str(latest_path),
        "archive_json": str(archive_path),
        "last_passing_json": str(last_passing_path),
        "logs_latest": str(cfg.log_root),
        "logs_archive": str(logs_archive_path),
        "file_results": [asdict(r) for r in results],
    }
    summary_path = run_root / args.summary_out
    write_json(summary_path, summary)

    project_summary = maybe_load_json(project_summary_path)
    if not isinstance(project_summary, dict):
        project_summary = {"timestamp": None, "project_id": args.project_id, "passed": None, "bmts": {}}
    bmts = project_summary.get("bmts")
    if not isinstance(bmts, dict):
        bmts = {}
    bmts[args.bmt_id] = {
        "status": status,
        "reason_code": reason_code,
        "aggregate_score": avg,
        "failed_count": len(failed),
        "latest_json": str(latest_path),
    }
    project_summary["timestamp"] = ts_iso
    project_summary["project_id"] = args.project_id
    project_summary["bmts"] = bmts
    project_summary["passed"] = all(isinstance(v, dict) and v.get("status") != "fail" for v in bmts.values())
    write_json(project_summary_path, project_summary)

    ts_print("")
    ts_print(f"OK: {len(ok)}  FAIL: {len(failed)}  AVG: {avg:.6f}  STATUS: {status}")
    ts_print(f"Summary: {summary_path}")
    ts_print(f"Latest: {latest_path}")
    ts_print(f"Archive: {archive_path}")
    ts_print(f"Project Summary: {project_summary_path}")
    ts_print(f"Logs (latest): {cfg.log_root}")
    ts_print(f"Logs (archive): {logs_archive_path}")
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
