#!/usr/bin/env python3
"""SK project BMT manager.

Runs per-file runner invocations by creating transient JSON configs from
project template and applying BMT-specific runtime overrides.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from whenever import Instant

from gcp.image.config.constants import EXECUTABLE_MODE
from gcp.image.projects.shared.bmt_manager_base import (
    BmtManagerBase,
    _gate_result,
    _gcloud_cp,
    _gcloud_ls_json,
    _gcloud_rsync,
    _gcs_exists,
    _gcs_object_meta,
    _load_json,
    _manifest_digest,
    _mark_cache,
    _normalize_comparison,
    _write_json,
    _write_runner_config,
    parse_args as _base_parse_args,
)
from gcp.image.utils import _bucket_uri, _now_iso


class SKManagerError(RuntimeError):
    """Raised for manager execution/config errors."""


_FORCED_WAV_PATH_KEYS = {
    "REF_PATH",
    "QUIET_PATH",
    "ZONE1_PATH",
    "ZONE2_PATH",
    "ZONE3_PATH",
    "ZONE4_PATH",
    "ZONE5_PATH",
    "ZONE6_PATH",
    "CALIB_BIN_PATH",
}


# ---------------------------------------------------------------------------
# SK-specific helpers
# ---------------------------------------------------------------------------


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
        return re.compile(rf"Hi {re.escape(keyword)} counter = (\d+)")
    return re.compile(r"Hi NAMUH counter = (\d+)")


def _walk_and_rewrite_paths(node: Any, wav_value: str, protected: set[str]) -> None:
    """Recursively rewrite placeholder _PATH values to wav_value, skipping protected keys."""
    if isinstance(node, list):
        for item in node:
            _walk_and_rewrite_paths(item, wav_value, protected)
        return
    if not isinstance(node, dict):
        return
    for key, value in list(node.items()):
        if isinstance(value, (dict, list)):
            _walk_and_rewrite_paths(value, wav_value, protected)
            continue
        if key in protected or not isinstance(value, str) or not key.endswith("_PATH"):
            continue
        stripped = value.strip()
        if not stripped or stripped.startswith((Path(tempfile.gettempdir()) / "dummy").as_posix()):
            node[key] = wav_value


def _rewrite_json_paths_for_wav(cfg: dict[str, Any], wav_path: Path, output_path: Path) -> None:
    wav_value = str(wav_path.resolve())
    output_value = str(output_path.resolve())

    cfg["MICS_PATH"] = wav_value
    cfg["KARDOME_OUTPUT_PATH"] = output_value
    if "USER_OUTPUT_PATH" in cfg:
        cfg["USER_OUTPUT_PATH"] = output_value

    for key in _FORCED_WAV_PATH_KEYS:
        if key in cfg:
            cfg[key] = wav_value

    protected = {"MICS_PATH", "KARDOME_OUTPUT_PATH", "USER_OUTPUT_PATH"}
    _walk_and_rewrite_paths(cfg, wav_value, protected)


def _read_counter(log_path: Path, counter_re: re.Pattern[str]) -> int:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = counter_re.findall(text)
    if not matches:
        return 0
    return int(matches[-1])


# ---------------------------------------------------------------------------
# parse_args (SK extension of base args)
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SK project BMT manager")
    _ = parser.add_argument("--jobs-config", required=True)
    return _base_parse_args(parser)


# ---------------------------------------------------------------------------
# SK manager class
# ---------------------------------------------------------------------------


class SKBmtManager(BmtManagerBase):
    """Concrete BMT manager for the SK project."""

    def __init__(self, args: argparse.Namespace, bmt_cfg: dict[str, Any]) -> None:
        super().__init__(args, bmt_cfg)

        paths_cfg = bmt_cfg.get("paths", {})
        if not isinstance(paths_cfg, dict):
            raise SKManagerError("paths must be an object")
        runner_cfg = bmt_cfg.get("runner", {})
        if not isinstance(runner_cfg, dict):
            raise SKManagerError("runner must be an object")

        self.runner_uri: str = _bucket_uri(self.runtime_bucket_root, str(runner_cfg["uri"]))
        self.runner_deps_prefix: str = str(runner_cfg.get("deps_prefix", "")).strip()
        self.template_uri: str = _bucket_uri(self.code_bucket_root, str(bmt_cfg["template_uri"]))
        self.dataset_uri: str = _bucket_uri(self.runtime_bucket_root, str(paths_cfg["dataset_prefix"]))
        self.outputs_prefix: str = str(paths_cfg["outputs_prefix"]).rstrip("/")
        self.results_prefix: str = str(paths_cfg["results_prefix"]).rstrip("/")
        self.logs_prefix: str = str(paths_cfg.get("logs_prefix", f"{self.results_prefix}/logs")).rstrip("/")

        # Cache paths
        dataset_ttl_sec = int(self.cache_cfg.get("dataset_ttl_sec", 300) or 300)
        self.dataset_ttl_sec: int = dataset_ttl_sec
        self.cache_runner_dir: Path = self.cache_base / "runner_bundle"
        self.cache_template_path: Path = self.cache_base / "input_template.json"
        self.cache_dataset_dir: Path = self.cache_base / "dataset"

        # Set at setup_assets time
        self.runner_path: Path = self.cache_runner_dir / Path(self.runner_uri).name
        self.runner_build_id: str = "unknown"
        self._template_cfg: dict[str, Any] = {}
        self._counter_re: re.Pattern[str] = _counter_regex(bmt_cfg)
        self._runner_env: dict[str, str] = {}
        self._inputs_root: Path = self.cache_dataset_dir

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def _setup_runner_assets(self) -> None:
        """Download/cache runner bundle and set runner_build_id."""
        runner_uri = self.runner_uri
        runner_deps_prefix = self.runner_deps_prefix
        runner_bundle_uri = runner_uri.rsplit("/", 1)[0].rstrip("/")
        runner_manifest_path = self.cache_meta_dir / "runner_bundle_meta.json"
        runner_manifest_entries = _gcloud_ls_json(f"{runner_bundle_uri}/", recursive=True)
        if runner_deps_prefix:
            deps_uri = _bucket_uri(self.runtime_bucket_root, runner_deps_prefix).rstrip("/") + "/"
            runner_manifest_entries.extend(_gcloud_ls_json(deps_uri, recursive=True))
        runner_digest = _manifest_digest(runner_manifest_entries)
        runner_hit = False
        runner_rel_name = Path(runner_uri).name
        runner_path = self.runner_path
        if self.cache_enabled and runner_manifest_path.is_file() and runner_path.is_file():
            manifest = _load_json(runner_manifest_path)
            runner_hit = str(manifest.get("digest", "")) == runner_digest
        if not runner_hit:
            t0 = time.monotonic()
            _gcloud_rsync(f"{runner_bundle_uri}/", self.cache_runner_dir)
            if runner_deps_prefix:
                deps_uri = _bucket_uri(self.runtime_bucket_root, runner_deps_prefix).rstrip("/") + "/"
                _gcloud_rsync(deps_uri, self.cache_runner_dir)
            if not runner_path.is_file():
                _gcloud_cp(runner_uri, runner_path)
            self.sync_durations_sec["runner_bundle_sync"] = round(time.monotonic() - t0, 3)
            _write_json(
                runner_manifest_path,
                {
                    "timestamp": _now_iso(),
                    "digest": runner_digest,
                    "runner_uri": runner_uri,
                    "runner_bundle_uri": runner_bundle_uri,
                    "deps_prefix": runner_deps_prefix,
                },
            )
        _mark_cache(self.cache_stats, "runner_bundle", hit=runner_hit)
        for _entry in runner_manifest_entries:
            _entry_name = str(_entry.get("name") or "")
            if Path(_entry_name).name == runner_rel_name:
                _gen = str(_entry.get("generation") or "").strip()
                if _gen:
                    self.runner_build_id = _gen
                break

    def _setup_template_assets(self) -> None:
        """Download/cache template JSON."""
        template_meta_path = self.cache_meta_dir / "template_meta.json"
        template_remote_meta = _gcs_object_meta(self.template_uri)
        if template_remote_meta is None:
            raise SKManagerError(f"Template object missing: {self.template_uri}")
        template_hit = False
        if self.cache_enabled and template_meta_path.is_file() and self.cache_template_path.is_file():
            cached_meta = _load_json(template_meta_path)
            template_hit = (
                str(cached_meta.get("generation", "")) == str(template_remote_meta.get("generation", ""))
                and int(cached_meta.get("size", -1)) == int(template_remote_meta.get("size", -2))
            )
        if not template_hit:
            t0 = time.monotonic()
            _gcloud_cp(self.template_uri, self.cache_template_path)
            self.sync_durations_sec["template_sync"] = round(time.monotonic() - t0, 3)
            _write_json(
                template_meta_path,
                {
                    "timestamp": _now_iso(),
                    "generation": str(template_remote_meta.get("generation", "")),
                    "size": int(template_remote_meta.get("size", 0)),
                    "template_uri": self.template_uri,
                },
            )
        _mark_cache(self.cache_stats, "template", hit=template_hit)

    def _setup_dataset_assets(self) -> None:
        """Set _inputs_root from BMT_DATASET_LOCAL_PATH or sync dataset from GCS."""
        dataset_local = os.environ.get("BMT_DATASET_LOCAL_PATH")
        if dataset_local:
            local_path = Path(dataset_local).resolve()
            if not local_path.is_dir():
                raise SKManagerError(f"BMT_DATASET_LOCAL_PATH is not a directory: {local_path}")
            self._inputs_root = local_path
            _mark_cache(self.cache_stats, "dataset", hit=True)
            return
        dataset_meta_path = self.cache_meta_dir / "dataset_meta.json"
        dataset_hit = False
        if self.cache_enabled and dataset_meta_path.is_file() and self.cache_dataset_dir.is_dir():
            dataset_meta = _load_json(dataset_meta_path)
            last_sync_epoch = float(dataset_meta.get("last_sync_epoch", 0.0) or 0.0)
            age = Instant.now().timestamp() - last_sync_epoch
            dataset_hit = (
                str(dataset_meta.get("source_uri", "")) == self.dataset_uri
                and age <= float(self.dataset_ttl_sec)
            )
        dataset_uri = self.dataset_uri
        if self.cache_enabled:
            if not dataset_hit:
                t0 = time.monotonic()
                _gcloud_rsync(dataset_uri.rstrip("/") + "/", self.cache_dataset_dir)
                self.sync_durations_sec["dataset_sync"] = round(time.monotonic() - t0, 3)
                _write_json(
                    dataset_meta_path,
                    {
                        "timestamp": _now_iso(),
                        "source_uri": dataset_uri,
                        "last_sync_epoch": Instant.now().timestamp(),
                        "dataset_ttl_sec": self.dataset_ttl_sec,
                    },
                )
            self._inputs_root = self.cache_dataset_dir
        else:
            inputs_root = self.staging_dir / "inputs"
            t0 = time.monotonic()
            _gcloud_rsync(dataset_uri.rstrip("/") + "/", inputs_root)
            self.sync_durations_sec["dataset_sync"] = round(time.monotonic() - t0, 3)
            self._inputs_root = inputs_root
        _mark_cache(self.cache_stats, "dataset", hit=dataset_hit)

    def _finalize_assets(self) -> None:
        """Validate runner/template exist, chmod, set _runner_env and _template_cfg."""
        runner_path = self.runner_path
        if not runner_path.is_file():
            raise SKManagerError(f"Runner binary missing after sync: {runner_path}")
        if not self.cache_template_path.is_file():
            raise SKManagerError(f"Template missing after sync: {self.cache_template_path}")
        runner_path.chmod(runner_path.stat().st_mode | EXECUTABLE_MODE)
        custom_loader = runner_path.parent / "ld-linux-x86-64.so.2"
        if custom_loader.is_file():
            custom_loader.chmod(custom_loader.stat().st_mode | EXECUTABLE_MODE)
        runtime_env = dict(os.environ)
        env_overrides = (
            self.runtime_cfg.get("env_overrides", {}) if isinstance(self.runtime_cfg.get("env_overrides"), dict) else {}
        )
        if not isinstance(env_overrides, dict):
            raise SKManagerError("runtime.env_overrides must be an object")
        for key, value in env_overrides.items():
            runtime_env[str(key)] = str(value)
        staged_lib_path = str(runner_path.parent.resolve())
        existing_ld = str(runtime_env.get("LD_LIBRARY_PATH", "")).strip()
        runtime_env["LD_LIBRARY_PATH"] = f"{staged_lib_path}:{existing_ld}" if existing_ld else staged_lib_path
        self._runner_env = runtime_env
        self._template_cfg = _load_json(self.cache_template_path)

    def setup_assets(self) -> None:
        """Download/cache runner bundle, template, and dataset."""
        self._setup_runner_assets()
        self._setup_template_assets()
        self._setup_dataset_assets()
        self._finalize_assets()

    def collect_input_files(self, inputs_root: Path) -> list[Path]:
        wav_files = sorted(inputs_root.rglob("*.wav"))
        if self.limit > 0:
            wav_files = wav_files[: self.limit]
        if not wav_files:
            raise SKManagerError(f"No wav files found under dataset: {self.dataset_uri}")
        return wav_files

    def run_file(self, input_file: Path, inputs_root: Path) -> dict[str, Any]:
        wav_path = input_file
        num_source_test = self.runtime_cfg.get("num_source_test")
        enable_overrides = self.runtime_cfg.get("enable_overrides", {})
        if not isinstance(enable_overrides, dict):
            raise SKManagerError("runtime.enable_overrides must be an object")

        rel = wav_path.relative_to(inputs_root)
        output_path = self.outputs_dir / rel
        log_path = self.logs_dir / rel.with_suffix(rel.suffix + ".log")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        cfg = copy.deepcopy(self._template_cfg)
        _rewrite_json_paths_for_wav(cfg, wav_path, output_path)
        if num_source_test is not None:
            cfg["NUM_SOURCE_TEST"] = int(num_source_test)

        for dotted_key, value in enable_overrides.items():
            _set_dotted(cfg, dotted_key, value)

        runner_path = self.runner_path
        fd, temp_path_str = tempfile.mkstemp(suffix=".json", dir=self.runtime_dir)
        os.close(fd)
        temp_path = Path(temp_path_str)
        try:
            _write_runner_config(temp_path, cfg)
            exit_code = 1
            error: str = ""
            runner_cmd = [str(runner_path), str(temp_path)]
            custom_loader = runner_path.parent / "ld-linux-x86-64.so.2"
            if custom_loader.is_file():
                runner_cmd = [
                    str(custom_loader),
                    "--library-path",
                    str(runner_path.parent.resolve()),
                    str(runner_path),
                    str(temp_path),
                ]
            with log_path.open("w", encoding="utf-8") as log_file:
                proc = subprocess.run(
                    runner_cmd,
                    cwd=str(self.runtime_dir),
                    env=self._runner_env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                exit_code = proc.returncode
        finally:
            temp_path.unlink(missing_ok=True)

        counter = _read_counter(log_path, self._counter_re)
        return {
            "file": str(rel),
            "exit_code": exit_code,
            "namuh_count": counter,
            "status": "ok" if exit_code == 0 else "failed",
            "log": str(log_path),
            "output": str(output_path),
            "error": error,
        }

    def compute_score(self, file_results: list[dict[str, Any]]) -> float:
        if not file_results:
            return 0.0
        return sum(int(item["namuh_count"]) for item in file_results) / len(file_results)

    def get_runner_identity(self) -> dict[str, Any]:
        return {
            "name": Path(self.runner_uri).name,
            "build_id": self.runner_build_id,
            "source_ref": "",
        }

    def _evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """SK pass/fail: baseline comparison from bmt_cfg gate (gte for false_reject, lte for false_alarm)."""
        gate_cfg = self.bmt_cfg.get("gate", {}) or {}
        comparison = _normalize_comparison(str(gate_cfg.get("comparison", "gte")))
        tolerance_abs = float(gate_cfg.get("tolerance_abs", 0.0) or 0.0)
        return _gate_result(comparison, aggregate_score, last_score, failed_count, self.run_context, tolerance_abs)

    def _artifact_uris(self) -> dict[str, str]:
        return {
            "runner_uri": self.runner_uri,
            "template_uri": self.template_uri,
            "dataset_uri": self.dataset_uri,
            "results_prefix": self.results_prefix,
            "logs_prefix": self.logs_prefix,
            "outputs_prefix": self.outputs_prefix,
        }

    def _print_result_line(self, status: str, aggregate_score: float, raw_score: float) -> None:
        status.upper()


# ---------------------------------------------------------------------------
# Compatibility aliases (used by tests and external monkeypatching)
# ---------------------------------------------------------------------------


def bucket_uri(bucket_root: str, path_or_uri: str) -> str:
    return _bucket_uri(bucket_root, path_or_uri)


def gcs_exists(uri: str) -> bool:
    return _gcs_exists(uri)


def gcloud_cp(src: str, dst: Path | str) -> None:
    _gcloud_cp(src, dst)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    jobs_cfg = _load_json(Path(args.jobs_config))
    bmts = jobs_cfg.get("bmts", {})
    bmt_cfg = bmts.get(args.bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise SKManagerError(f"Unknown BMT id: {args.bmt_id}")
    if not bool(bmt_cfg.get("enabled", True)):
        raise SKManagerError(f"BMT is disabled: {args.bmt_id}")
    manager = SKBmtManager(args, bmt_cfg)
    return manager.run()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SKManagerError:
        raise SystemExit(2) from None
