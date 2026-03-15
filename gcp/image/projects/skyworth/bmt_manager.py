#!/usr/bin/env python3
"""Skyworth project BMT manager (minimal example).

Implements the same contract as SK: paths, runner, template, and gate from
bmt_jobs.json; override _evaluate_gate if you need custom gate logic.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from gcp.image.config.constants import EXECUTABLE_MODE
from gcp.image.projects.shared.bmt_manager_base import (
    BmtManagerBase,
    _gate_result,
    _gcloud_cp,
    _gcloud_rsync,
    _load_json,
    _normalize_comparison,
    parse_args as _base_parse_args,
)
from gcp.image.utils import _bucket_uri, _runtime_bucket_root


def _counter_regex(parsing: dict[str, Any]) -> re.Pattern[str]:
    pattern = str(parsing.get("counter_pattern", "")).strip()
    if pattern:
        return re.compile(pattern)
    keyword = str(parsing.get("keyword", "NAMUH")).strip()
    return re.compile(rf"Hi {re.escape(keyword)} counter = (\d+)")


class SkyworthBmtManager(BmtManagerBase):
    """Minimal BMT manager for Skyworth: runner + template from GCS, gate from config."""

    def __init__(self, args: argparse.Namespace, bmt_cfg: dict[str, Any]) -> None:
        super().__init__(args, bmt_cfg)
        paths = bmt_cfg.get("paths", {}) or {}
        self._dataset_prefix = str(paths.get("dataset_prefix", "skyworth/inputs/default")).rstrip("/")
        runner_cfg = bmt_cfg.get("runner", {}) or {}
        self._runner_uri = ""
        if isinstance(runner_cfg, dict) and runner_cfg.get("uri"):
            self._runner_uri = _bucket_uri(
                _runtime_bucket_root(args.bucket),
                str(runner_cfg["uri"]).strip(),
            )
        else:
            self._runner_uri = _bucket_uri(
                _runtime_bucket_root(args.bucket),
                "skyworth/runners/skyworth_gcc_release/kardome_runner",
            )
        self._inputs_root = None
        self._runner_path = None
        self._counter_pattern = _counter_regex(bmt_cfg.get("parsing", {}) or {})

    def setup_assets(self) -> None:
        runtime_root = _runtime_bucket_root(self.bucket)
        staging = self.staging_dir
        staging.mkdir(parents=True, exist_ok=True)
        inputs_dir = staging / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        dataset_uri = _bucket_uri(runtime_root, f"{self._dataset_prefix}/")
        try:
            _gcloud_rsync(dataset_uri, inputs_dir)
        except Exception:
            pass
        self._inputs_root = inputs_dir
        runner_dir = self.run_root / "runner"
        runner_dir.mkdir(parents=True, exist_ok=True)
        runner_dest = runner_dir / "kardome_runner"
        if not runner_dest.exists():
            _gcloud_cp(self._runner_uri, runner_dest)
        runner_dest.chmod(runner_dest.stat().st_mode | EXECUTABLE_MODE)
        self._runner_path = runner_dest

    def collect_input_files(self, inputs_root: Path) -> list[Path]:
        return sorted(inputs_root.rglob("*.wav"))

    def run_file(self, input_file: Path, inputs_root: Path) -> dict[str, Any]:
        out_dir = self.outputs_dir / input_file.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = out_dir / "config.json"
        cfg_path.write_text(
            json.dumps({"input": str(input_file), "output": str(out_dir / "out.wav")}),
            encoding="utf-8",
        )
        cmd = [str(self._runner_path), str(input_file), str(cfg_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(self.run_root))
        stdout = proc.stdout or ""
        match = self._counter_pattern.search(stdout)
        counter = int(match.group(1)) if match else 0
        return {
            "file": input_file.name,
            "exit_code": proc.returncode,
            "status": "ok" if proc.returncode == 0 else "failed",
            "error": (proc.stderr or "").strip(),
            "counter": counter,
        }

    def compute_score(self, file_results: list[dict[str, Any]]) -> float:
        if not file_results:
            return 0.0
        total = sum(
            int(r.get("counter", 0)) for r in file_results if int(r.get("exit_code", 1)) == 0
        )
        return total / len(file_results)

    def get_runner_identity(self) -> dict[str, Any]:
        return {"name": "skyworth_runner", "source": "skyworth"}

    def _evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Skyworth example: baseline gte/lte from bmt_cfg gate (same pattern as SK)."""
        gate_cfg = self.bmt_cfg.get("gate", {}) or {}
        comparison = _normalize_comparison(str(gate_cfg.get("comparison", "gte")))
        tolerance_abs = float(gate_cfg.get("tolerance_abs", 0.0) or 0.0)
        return _gate_result(
            comparison, aggregate_score, last_score, failed_count, self.run_context, tolerance_abs
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Skyworth BMT manager")
    _base_parse_args(parser)
    _ = parser.add_argument("--jobs-config", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    jobs_cfg = _load_json(Path(args.jobs_config))
    bmts = jobs_cfg.get("bmts", {})
    bmt_cfg = bmts.get(args.bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise SystemExit(2)
    if not bmt_cfg.get("enabled", True):
        raise SystemExit(2)
    manager = SkyworthBmtManager(args, bmt_cfg)
    return manager.run()


if __name__ == "__main__":
    raise SystemExit(main())
