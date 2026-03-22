#!/usr/bin/env python3
"""Run kardome_runner over WAV files for sandbox validation.

This helper expands a shared input template for each WAV, executes the native
runner, parses NAMUH counters from logs, and writes JSON/CSV summaries.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

COUNTER_RE = re.compile(r"Hi NAMUH counter = (\d+)")


@dataclass
class FileResult:
    file: str
    status: str
    exit_code: int
    namuh_count: int
    duration_sec: float
    log_path: str
    output_wav: str


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrite_template(cfg: dict[str, Any], wav_path: Path, output_wav: Path) -> dict[str, Any]:
    cfg = dict(cfg)
    wav_value = str(wav_path.resolve())
    out_value = str(output_wav.resolve())
    cfg["MICS_PATH"] = wav_value
    cfg["REF_PATH"] = wav_value
    cfg["KARDOME_OUTPUT_PATH"] = out_value
    cfg["USER_OUTPUT_PATH"] = out_value
    cfg["QUIET_PATH"] = wav_value
    for idx in range(1, 7):
        cfg[f"ZONE{idx}_PATH"] = wav_value
    cfg["NUM_SOURCE_TEST"] = 0
    return cfg


def _read_counter(log_path: Path) -> int:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = COUNTER_RE.findall(text)
    if not matches:
        return 0
    return int(matches[-1])


def _runner_env(runner_path: Path, deps_dir: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    staged_root = runner_path.parent.resolve()
    ld_parts: list[str] = [str(staged_root)]
    for sub in ("lib", "lib64"):
        candidate = staged_root / sub
        if candidate.is_dir():
            ld_parts.append(str(candidate))
    if deps_dir is not None and deps_dir.is_dir():
        ld_parts.append(str(deps_dir.resolve()))
    existing = str(env.get("LD_LIBRARY_PATH", "")).strip()
    if existing:
        ld_parts.append(existing)
    env["LD_LIBRARY_PATH"] = ":".join(ld_parts)
    return env


def _runner_cmd(runner_path: Path, config_path: Path) -> list[str]:
    custom_loader = runner_path.parent / "ld-linux-x86-64.so.2"
    if custom_loader.is_file():
        return [
            str(custom_loader),
            "--library-path",
            str(runner_path.parent.resolve()),
            str(runner_path),
            str(config_path),
        ]
    return [str(runner_path), str(config_path)]


def run_all(
    *,
    runner: Path,
    template: Path,
    wav_root: Path,
    out_root: Path,
    deps_dir: Path | None,
    limit: int,
) -> tuple[list[FileResult], dict[str, Any]]:
    if not runner.is_file():
        raise FileNotFoundError(f"Runner not found: {runner}")
    if not template.is_file():
        raise FileNotFoundError(f"Template not found: {template}")
    if not wav_root.is_dir():
        raise FileNotFoundError(f"WAV root not found: {wav_root}")

    runner.chmod(runner.stat().st_mode | 0o111)
    template_cfg = _read_json(template)
    env = _runner_env(runner, deps_dir)

    wavs = sorted(wav_root.rglob("*.wav"))
    if limit > 0:
        wavs = wavs[:limit]
    if not wavs:
        raise RuntimeError(f"No wav files found under: {wav_root}")

    logs_dir = out_root / "logs"
    wav_out_dir = out_root / "wav_outputs"
    cfg_dir = out_root / "configs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    wav_out_dir.mkdir(parents=True, exist_ok=True)
    cfg_dir.mkdir(parents=True, exist_ok=True)

    results: list[FileResult] = []
    for wav_path in wavs:
        rel = wav_path.relative_to(wav_root)
        log_path = logs_dir / rel.with_suffix(rel.suffix + ".log")
        out_wav = wav_out_dir / rel.with_suffix(".out.wav")
        cfg_path = cfg_dir / rel.with_suffix(".json")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)

        cfg = _rewrite_template(template_cfg, wav_path, out_wav)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        cmd = _runner_cmd(runner, cfg_path)

        t0 = time.monotonic()
        with log_path.open("w", encoding="utf-8") as handle:
            proc = subprocess.run(
                cmd,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        duration_sec = round(time.monotonic() - t0, 3)
        namuh = _read_counter(log_path)

        results.append(
            FileResult(
                file=str(rel),
                status="ok" if proc.returncode == 0 else "failed",
                exit_code=proc.returncode,
                namuh_count=namuh,
                duration_sec=duration_sec,
                log_path=str(log_path),
                output_wav=str(out_wav),
            )
        )

    total = len(results)
    ok_count = sum(1 for r in results if r.status == "ok")
    fail_count = total - ok_count
    avg_namuh = round(sum(r.namuh_count for r in results) / total, 3)
    summary = {
        "total_files": total,
        "ok_count": ok_count,
        "fail_count": fail_count,
        "avg_namuh": avg_namuh,
        "started_at_epoch": time.time(),
    }
    return results, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Sandbox kardome runner over audio/sk WAV files.")
    parser.add_argument("--runner", type=Path, required=True, help="Path to kardome_runner binary.")
    parser.add_argument("--template", type=Path, required=True, help="Path to input_template.json.")
    parser.add_argument("--wav-root", type=Path, required=True, help="Root folder to scan for *.wav.")
    parser.add_argument(
        "--out-root",
        type=Path,
        default=None,
        help="Output root (default: <tempdir>/kardome-sandbox-out).",
    )
    parser.add_argument("--deps-dir", type=Path, default=None, help="Optional shared dependency directory.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max WAV files (0 = all).")
    parser.add_argument("--summary-json", type=Path, default=None, help="Summary JSON path.")
    parser.add_argument("--summary-csv", type=Path, default=None, help="Summary CSV path.")
    parser.add_argument(
        "--fail-on-runner-error",
        action="store_true",
        help="Exit non-zero when one or more files fail.",
    )
    args = parser.parse_args()

    out_root = args.out_root if args.out_root is not None else Path(tempfile.gettempdir()) / "kardome-sandbox-out"
    out_root.mkdir(parents=True, exist_ok=True)
    summary_json = args.summary_json or (out_root / "summary.json")
    summary_csv = args.summary_csv or (out_root / "summary.csv")

    results, summary = run_all(
        runner=args.runner,
        template=args.template,
        wav_root=args.wav_root,
        out_root=out_root,
        deps_dir=args.deps_dir,
        limit=args.limit,
    )
    payload = {"summary": summary, "results": [asdict(r) for r in results]}
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    summary_csv.parent.mkdir(parents=True, exist_ok=True)
    with summary_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "status", "exit_code", "namuh_count", "duration_sec", "log_path", "output_wav"])
        for row in results:
            writer.writerow(
                [row.file, row.status, row.exit_code, row.namuh_count, row.duration_sec, row.log_path, row.output_wav]
            )

    print(json.dumps(summary, indent=2))
    if args.fail_on_runner_error and summary["fail_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
