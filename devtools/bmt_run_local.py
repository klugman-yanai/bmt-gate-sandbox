#!/usr/bin/env -S uv run --script
"""Local SK batch runner (config-first).

Reads BMT behavior from remote/code/sk/config/bmt_jobs.json and runs
kardome_runner once per wav by creating a transient JSON from the configured
template. CLI flags act as explicit overrides.
"""

from __future__ import annotations

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

import click

_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))
from shared_time_utils import now_iso, now_stamp

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


@dataclass
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


@dataclass
class RunOptions:
    jobs_config: str = "remote/code/sk/config/bmt_jobs.json"
    bmt_id: str = "false_reject_namuh"
    project_id: str = "sk"
    run_context: str = "manual"
    code_root: str = "remote/code"
    runtime_root: str = "remote/runtime"
    sk_root: str = ""
    results_subdir: str = "false_rejects"
    runner: str = ""
    template: str = ""
    dataset_root: str = ""
    output_root: str = ""
    log_root: str = ""
    comparison: str = ""
    run_root: str = "local_batch"
    limit: int = 0
    workers: int = 1
    timeout_sec: int = 0
    summary_out: str = "summary.json"
    set_ref_to_mics: bool = False
    num_source_test: int | None = None


def ts_print(*args: object, **kwargs: Any) -> None:
    with PRINT_LOCK:
        click.echo(" ".join(str(a) for a in args))


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
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as tf:
        tf.write(text)
        temp_path = Path(tf.name)
    temp_path.replace(path)


def counter_regex(bmt_cfg: dict[str, Any]) -> re.Pattern[str]:
    parsing = bmt_cfg.get("parsing", {})
    if not isinstance(parsing, dict):
        return re.compile(DEFAULT_COUNTER_PATTERN)

    if pattern := str(parsing.get("counter_pattern", "")).strip():
        return re.compile(pattern)

    if keyword := str(parsing.get("keyword", "NAMUH")).strip():
        return re.compile(rf"Hi {re.escape(keyword)} counter = (\d+)")

    return re.compile(DEFAULT_COUNTER_PATTERN)


def effective_gate_comparison(bmt_id: str, comparison: str) -> str:
    normalized = comparison.strip().lower()
    if bmt_id.startswith("false_reject") and normalized == "lte":
        return "gte"
    return normalized


def resolve_local_path(path_or_contract: str, code_root: Path, runtime_root: Path) -> Path:
    raw = str(path_or_contract).strip()
    if not raw:
        raise ValueError("Empty path is not allowed")
    if raw.startswith("gs://"):
        raise ValueError(f"Local script requires local path, not gs:// URI: {raw}")

    p = Path(raw).expanduser()
    if p.is_absolute():
        return p.resolve()
    if raw.startswith("sk/config/"):
        return (code_root / raw).resolve()
    if raw.startswith("sk/"):
        return (runtime_root / raw).resolve()
    return (Path.cwd() / p).resolve()


def resolve_config(opts: RunOptions) -> ResolvedConfig:
    if opts.sk_root.strip():
        # Legacy single-root contract where code and runtime lived under one parent.
        legacy_parent = Path(opts.sk_root).expanduser().resolve().parent
        code_root = legacy_parent
        runtime_root = legacy_parent
    else:
        code_root = Path(opts.code_root).expanduser().resolve()
        runtime_root = Path(opts.runtime_root).expanduser().resolve()
    jobs_config_path = Path(opts.jobs_config).expanduser().resolve()
    jobs_cfg = load_json(jobs_config_path)

    bmts = jobs_cfg.get("bmts", {})
    if not isinstance(bmts, dict):
        raise ValueError("jobs config must contain object key: bmts")

    bmt_cfg = bmts.get(opts.bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise ValueError(f"Unknown bmt id: {opts.bmt_id}")
    if not bmt_cfg.get("enabled", True):
        raise ValueError(f"BMT is disabled in config: {opts.bmt_id}")

    paths_cfg = bmt_cfg.get("paths", {})
    runtime_cfg = bmt_cfg.get("runtime", {})
    gate_cfg = bmt_cfg.get("gate", {})
    warning_policy = bmt_cfg.get("warning_policy", {})

    for name, cfg in [
        ("paths", paths_cfg),
        ("runtime", runtime_cfg),
        ("gate", gate_cfg),
        ("warning_policy", warning_policy),
    ]:
        if not isinstance(cfg, dict):
            raise ValueError(f"bmt {name} must be an object")

    runner_cfg = bmt_cfg.get("runner", {})
    runner_contract = runner_cfg.get("uri", "") if isinstance(runner_cfg, dict) else ""

    def get_path(d: Any, k: str, default: str = "") -> str:
        if isinstance(d, dict):
            return str(d.get(k, default)).strip()
        return default

    runner_raw = opts.runner.strip() or runner_contract or "sk/runners/kardome_runner"
    template_raw = opts.template.strip() or get_path(bmt_cfg, "template_uri") or "sk/config/input_template.json"
    dataset_raw = (
        opts.dataset_root.strip() or get_path(paths_cfg, "dataset_prefix") or f"sk/inputs/{opts.results_subdir}"
    )
    output_raw = (
        opts.output_root.strip() or get_path(paths_cfg, "outputs_prefix") or f"sk/outputs/{opts.results_subdir}"
    )
    results_raw = get_path(paths_cfg, "results_prefix") or f"sk/results/{opts.results_subdir}"
    archive_raw = get_path(paths_cfg, "archive_prefix") or "sk/results/archive"

    runner_path = resolve_local_path(runner_raw, code_root, runtime_root)
    template_path = resolve_local_path(template_raw, code_root, runtime_root)
    dataset_root = resolve_local_path(dataset_raw, code_root, runtime_root)
    output_root = resolve_local_path(output_raw, code_root, runtime_root)
    results_dir = resolve_local_path(results_raw, code_root, runtime_root)
    archive_dir = resolve_local_path(archive_raw, code_root, runtime_root)

    if opts.log_root.strip():
        log_root = resolve_local_path(opts.log_root, code_root, runtime_root)
    elif logs_contract := get_path(paths_cfg, "logs_prefix"):
        logs_base = resolve_local_path(logs_contract, code_root, runtime_root)
        log_root = logs_base if logs_base.name == "latest" else logs_base / "latest"
    else:
        log_root = results_dir.parent / "logs" / results_dir.name / "latest"

    comparison = effective_gate_comparison(
        opts.bmt_id,
        opts.comparison.strip() or str(gate_cfg.get("comparison", "gte")),
    )
    if comparison not in {"gte", "lte"}:
        raise ValueError(f"Unsupported comparison: {comparison}")

    num_source_test = opts.num_source_test if opts.num_source_test is not None else runtime_cfg.get("num_source_test")
    num_source_test = int(num_source_test) if num_source_test is not None else None

    enable_overrides = runtime_cfg.get("enable_overrides", {})
    if not isinstance(enable_overrides, dict):
        raise ValueError("runtime.enable_overrides must be an object")

    return ResolvedConfig(
        jobs_config_path=jobs_config_path,
        bmt_id=opts.bmt_id,
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
        counter_re=counter_regex(bmt_cfg),
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
        passed = run_context != "pr"
        return {
            "comparison": comparison,
            "last_score": None,
            "current_score": current_score,
            "passed": passed,
            "reason": "bootstrap_no_previous_result" if passed else "missing_previous_result",
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
    if not gate.get("passed"):
        return "fail", reason
    if reason == "bootstrap_no_previous_result" and warning_policy.get("bootstrap_without_baseline"):
        return "warning", "bootstrap_without_baseline"
    return "pass", reason


def read_counter(log_path: Path, counter_re: re.Pattern[str]) -> int:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = counter_re.findall(text)
    return int(matches[-1]) if matches else 0


def filter_runner_output(text: str) -> str:
    lines = [line for line in text.splitlines() if not TIMESTAMP_NOISE_RE.match(line)]
    return "\n".join(lines) + ("\n" if lines else "")


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

    cursor = cfg
    for key, value in enable_overrides.items():
        for part in str(key).split(".")[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[str(key).split(".")[-1]] = value

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=run_root, delete=False, encoding="utf-8") as tf:
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
        log_path.write_text(filter_runner_output(proc.stdout or ""), encoding="utf-8")
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        err = f"timeout_after_{timeout_sec}s"
        log_path.write_text(filter_runner_output(str(exc.stdout or "")), encoding="utf-8")
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


def write_results(
    cfg: ResolvedConfig,
    opts: RunOptions,
    results: list[FileResult],
    sk_root: Path,
    run_root: Path,
    avg: float,
    status: str,
    reason_code: str,
    gate: dict[str, Any],
) -> None:
    ts_iso = now_iso()
    ts_compact = now_stamp()
    latest_path = cfg.results_dir / "latest.json"
    last_passing_path = cfg.results_dir / "last_passing.json"
    archive_path = cfg.archive_dir / f"{ts_compact}.json"
    logs_archive_path = cfg.log_root.parent / "archive" / ts_compact
    project_summary_path = sk_root / "results" / "sk_bmt_results.json"

    result_doc = {
        "timestamp": ts_iso,
        "project_id": opts.project_id,
        "bmt_id": opts.bmt_id,
        "run_context": opts.run_context,
        "status": status,
        "reason_code": reason_code,
        "aggregate_score": avg,
        "raw_aggregate_score": avg,
        "failed_count": sum(1 for r in results if r.exit_code != 0),
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
    if opts.run_context == "dev" and gate.get("passed"):
        write_json(last_passing_path, result_doc)

    logs_archive_path.parent.mkdir(parents=True, exist_ok=True)
    if logs_archive_path.exists():
        shutil.rmtree(logs_archive_path)
    shutil.copytree(cfg.log_root, logs_archive_path)

    ok = [r for r in results if r.exit_code == 0]
    failed = [r for r in results if r.exit_code != 0]

    summary = {
        "timestamp": ts_iso,
        "project_id": opts.project_id,
        "bmt_id": opts.bmt_id,
        "run_context": opts.run_context,
        "runner": str(cfg.runner_path),
        "template": str(cfg.template_path),
        "dataset_root": str(cfg.dataset_root),
        "sk_root": str(sk_root),
        "jobs_config": str(cfg.jobs_config_path),
        "workers": opts.workers,
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
    write_json(run_root / opts.summary_out, summary)

    project_summary = maybe_load_json(project_summary_path) or {
        "timestamp": None,
        "project_id": opts.project_id,
        "passed": None,
        "bmts": {},
    }
    if not isinstance(project_summary, dict):
        project_summary = {"timestamp": None, "project_id": opts.project_id, "passed": None, "bmts": {}}

    bmts = project_summary.get("bmts", {})
    if not isinstance(bmts, dict):
        bmts = {}
    bmts[opts.bmt_id] = {
        "status": status,
        "reason_code": reason_code,
        "aggregate_score": avg,
        "failed_count": len(failed),
        "latest_json": str(latest_path),
    }
    project_summary.update({"timestamp": ts_iso, "project_id": opts.project_id, "bmts": bmts})
    project_summary["passed"] = all(isinstance(v, dict) and v.get("status") != "fail" for v in bmts.values())
    write_json(project_summary_path, project_summary)


@click.command()
@click.option("--jobs-config", default="remote/code/sk/config/bmt_jobs.json", help="BMT jobs config JSON path")
@click.option("--bmt-id", default="false_reject_namuh", help="BMT id under bmts.<bmt_id> in jobs config")
@click.option("--project-id", default="sk", help="Project id for result metadata")
@click.option("--run-context", type=click.Choice(["manual", "dev", "pr"]), default="manual", help="Run context")
@click.option("--code-root", default="remote/code", help="Code root for sk/config/... contract paths")
@click.option(
    "--runtime-root",
    default="remote/runtime",
    help="Runtime root for sk/runners, sk/inputs, sk/outputs, and sk/results contract paths",
)
@click.option(
    "--sk-root",
    default="",
    help="Legacy unified SK root override (e.g. remote/sk); when set, ignores --code-root/--runtime-root",
)
@click.option("--results-subdir", default="false_rejects", help="Fallback subdir when config paths are missing")
@click.option("--runner", default="", help="Runner path override")
@click.option("--template", default="", help="Template path override")
@click.option("--dataset-root", default="", help="Dataset root override")
@click.option("--output-root", default="", help="Output root override")
@click.option("--log-root", default="", help="Log root override")
@click.option("--comparison", type=click.Choice(["", "gte", "lte"]), default="", help="Gate comparison override")
@click.option("--run-root", default="local_batch", help="Run scratch root (temp json + summary)")
@click.option("--limit", type=int, default=0, help="Limit wav files")
@click.option("--workers", type=int, default=1, help="Parallel workers")
@click.option("--timeout-sec", type=int, default=0, help="Per-file timeout (0 disables)")
@click.option("--summary-out", default="summary.json", help="Summary filename under run-root")
@click.option("--set-ref-to-mics", is_flag=True, help="Force REF_PATH = MICS_PATH")
@click.option("--num-source-test", type=int, default=None, help="Override NUM_SOURCE_TEST")
def main(**kwargs) -> int:
    opts = RunOptions(**kwargs)

    run_root = Path(opts.run_root).expanduser().resolve()
    if opts.sk_root.strip():
        runtime_sk_root = Path(opts.sk_root).expanduser().resolve()
        code_root = runtime_sk_root.parent
        runtime_root = runtime_sk_root.parent
    else:
        code_root = Path(opts.code_root).expanduser().resolve()
        runtime_root = Path(opts.runtime_root).expanduser().resolve()
        runtime_sk_root = runtime_root / "sk"
    cfg = resolve_config(opts)

    if not cfg.runner_path.is_file():
        click.echo(f"::error::Runner not found: {cfg.runner_path}", err=True)
        return 2
    if not os.access(cfg.runner_path, os.X_OK):
        click.echo(f"::error::Runner is not executable: {cfg.runner_path}", err=True)
        return 2
    if not cfg.dataset_root.is_dir():
        click.echo(f"::error::Dataset root not found: {cfg.dataset_root}", err=True)
        return 2

    workers = max(1, min(opts.workers, 256))
    run_root.mkdir(parents=True, exist_ok=True)
    cfg.output_root.mkdir(parents=True, exist_ok=True)
    if cfg.log_root.exists():
        shutil.rmtree(cfg.log_root)
    cfg.log_root.mkdir(parents=True, exist_ok=True)

    template_cfg = load_json(cfg.template_path)
    wav_files = sorted(cfg.dataset_root.rglob("*.wav"))
    if opts.limit > 0:
        wav_files = wav_files[: opts.limit]
    if not wav_files:
        click.echo(f"::error::No wav files found under {cfg.dataset_root}", err=True)
        return 2

    ts_print(f"Jobs config: {cfg.jobs_config_path}")
    ts_print(f"BMT id: {opts.bmt_id}")
    ts_print(f"Runner: {cfg.runner_path}")
    ts_print(f"Template: {cfg.template_path}")
    ts_print(f"Dataset root: {cfg.dataset_root}")
    ts_print(f"Code root: {code_root}")
    ts_print(f"Runtime root: {runtime_root}")
    ts_print(f"SK runtime root: {runtime_sk_root}")
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
                opts.timeout_sec,
                opts.set_ref_to_mics,
                cfg.num_source_test,
                cfg.enable_overrides,
                cfg.counter_re,
            ): wav
            for wav in wav_files
        }
        for idx, fut in enumerate(as_completed(futures), start=1):
            res = fut.result()
            results.append(res)
            ts_print(f"[{idx}/{len(futures)}] rc={res.exit_code} namuh={res.namuh_count} file={res.file}")

    results.sort(key=lambda x: x.file)
    avg = (sum(r.namuh_count for r in results) / len(results)) if results else 0.0
    failed_count = sum(1 for r in results if r.exit_code != 0)

    previous_latest = maybe_load_json(cfg.results_dir / "latest.json")
    previous_score = None
    if isinstance(previous_latest, dict) and previous_latest.get("aggregate_score") is not None:
        try:
            previous_score = float(previous_latest["aggregate_score"])
        except (TypeError, ValueError):
            previous_score = None

    gate = compute_gate(cfg.comparison, float(avg), previous_score, failed_count, opts.run_context)
    status, reason_code = resolve_status(gate, cfg.warning_policy)

    write_results(cfg, opts, results, runtime_sk_root, run_root, avg, status, reason_code, gate)

    ok_count = len(results) - failed_count
    ts_print("")
    ts_print(f"OK: {ok_count}  FAIL: {failed_count}  AVG: {avg:.6f}  STATUS: {status}")
    ts_print(f"Summary: {run_root / opts.summary_out}")
    ts_print(f"Latest: {cfg.results_dir / 'latest.json'}")
    ts_print(f"Archive: {cfg.archive_dir}")
    ts_print(f"Logs: {cfg.log_root}")

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
