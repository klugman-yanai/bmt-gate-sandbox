"""Compatibility adapter for current kardome per-file stdout parsing."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gcp.image.config.constants import ENV_BMT_KARDOME_CASE_TIMEOUT_SEC
from gcp.image.runtime.sdk.results import CaseResult, ExecutionResult
from gcp.image.runtime.stdout_counter_parse import counter_pattern_from_parsing_dict, read_counter_from_log

logger = logging.getLogger(__name__)

# Placeholder prefix used in input_template.json; paths starting with this are rewritten per-WAV.
_TEMPLATE_PLACEHOLDER_PREFIX = (Path(tempfile.gettempdir()) / "dummy").as_posix()

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


def _set_dotted(config: dict[str, Any], dotted_key: str, value: Any) -> None:
    cursor: dict[str, Any] = config
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


def _walk_and_rewrite_paths(node: Any, wav_value: str, protected_keys: set[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_and_rewrite_paths(item, wav_value, protected_keys)
        return
    if not isinstance(node, dict):
        return
    for key, value in list(node.items()):
        if not isinstance(key, str):
            continue
        if isinstance(value, dict | list):
            _walk_and_rewrite_paths(value, wav_value, protected_keys)
            continue
        if key in protected_keys or not isinstance(value, str) or not key.endswith("_PATH"):
            continue
        stripped = value.strip()
        if not stripped or stripped.startswith(_TEMPLATE_PLACEHOLDER_PREFIX):
            node[key] = wav_value


def _rewrite_json_paths_for_wav(config: dict[str, Any], wav_path: Path, output_path: Path) -> None:
    wav_value = str(wav_path.resolve())
    output_value = str(output_path.resolve())

    config["MICS_PATH"] = wav_value
    config["KARDOME_OUTPUT_PATH"] = output_value
    if "USER_OUTPUT_PATH" in config:
        config["USER_OUTPUT_PATH"] = output_value

    for key in _FORCED_WAV_PATH_KEYS:
        if key in config:
            config[key] = wav_value

    _walk_and_rewrite_paths(
        config,
        wav_value,
        {"MICS_PATH", "KARDOME_OUTPUT_PATH", "USER_OUTPUT_PATH"},
    )


def _subprocess_timeout_sec() -> float | None:
    raw = (os.environ.get(ENV_BMT_KARDOME_CASE_TIMEOUT_SEC) or "").strip()
    if not raw:
        return None
    try:
        sec = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; ignoring per-case timeout", ENV_BMT_KARDOME_CASE_TIMEOUT_SEC, raw)
        return None
    if sec <= 0:
        return None
    return float(sec)


@dataclass(frozen=True, slots=True)
class LegacyKardomeStdoutConfig:
    runner_path: Path
    template_path: Path
    dataset_root: Path
    runtime_root: Path
    outputs_root: Path
    logs_root: Path
    parsing: dict[str, Any] = field(default_factory=dict)
    enable_overrides: dict[str, Any] = field(default_factory=dict)
    num_source_test: int | None = None
    runner_env: dict[str, str] = field(default_factory=dict)


class LegacyKardomeStdoutExecutor:
    def __init__(self, config: LegacyKardomeStdoutConfig) -> None:
        self.config = config

    def _case_for_wav(
        self,
        wav_path: Path,
        rel: Path,
        template: dict[str, Any],
        counter_re: re.Pattern[str],
        runner_path: Path,
    ) -> CaseResult:
        log_path = self.config.logs_root / rel.with_suffix(rel.suffix + ".log")
        output_path = self.config.outputs_root / rel
        log_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cfg = copy.deepcopy(template)
        _rewrite_json_paths_for_wav(cfg, wav_path, output_path)
        if self.config.num_source_test is not None:
            cfg["NUM_SOURCE_TEST"] = int(self.config.num_source_test)
        for dotted_key, value in self.config.enable_overrides.items():
            _set_dotted(cfg, dotted_key, value)

        with tempfile.NamedTemporaryFile(
            suffix=".json",
            dir=self.config.runtime_root,
            delete=False,
        ) as handle:
            Path(handle.name).write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
            config_path = Path(handle.name)
        try:
            proc = None
            timeout_sec = _subprocess_timeout_sec()
            try:
                log_stream = log_path.open("w", encoding="utf-8")
            except OSError as exc:
                return CaseResult(
                    case_id=rel.as_posix(),
                    input_path=wav_path,
                    exit_code=-1,
                    status="failed",
                    metrics={"namuh_count": 0.0},
                    artifacts={
                        "log_path": str(log_path),
                        "output_path": str(output_path),
                    },
                    error=f"log_open_failed:{type(exc).__name__}:{exc}",
                )
            try:
                try:
                    proc = subprocess.run(
                        [str(runner_path), str(config_path)],
                        cwd=str(self.config.runtime_root),
                        env=self._runner_env(),
                        stdout=log_stream,
                        stderr=subprocess.STDOUT,
                        check=False,
                        timeout=timeout_sec,
                    )
                except subprocess.TimeoutExpired:
                    return CaseResult(
                        case_id=rel.as_posix(),
                        input_path=wav_path,
                        exit_code=-1,
                        status="failed",
                        metrics={"namuh_count": 0.0},
                        artifacts={
                            "log_path": str(log_path),
                            "output_path": str(output_path),
                        },
                        error=(
                            f"kardome_runner_timeout_after_{int(timeout_sec)}s"
                            if timeout_sec is not None
                            else "kardome_runner_timeout"
                        ),
                    )
                except OSError as exc:
                    return CaseResult(
                        case_id=rel.as_posix(),
                        input_path=wav_path,
                        exit_code=-1,
                        status="failed",
                        metrics={"namuh_count": 0.0},
                        artifacts={
                            "log_path": str(log_path),
                            "output_path": str(output_path),
                        },
                        error=f"runner_os_error:{type(exc).__name__}:{exc}",
                    )
                assert proc is not None
                counter = read_counter_from_log(log_path, counter_re)
                counter_found = counter is not None
                ok = proc.returncode == 0 and counter_found
                error = (
                    "" if ok else "counter_not_found" if proc.returncode == 0 else f"runner_exit_{proc.returncode}"
                )
                return CaseResult(
                    case_id=rel.as_posix(),
                    input_path=wav_path,
                    exit_code=proc.returncode,
                    status="ok" if ok else "failed",
                    metrics={"namuh_count": float(counter if counter is not None else 0)},
                    artifacts={
                        "log_path": str(log_path),
                        "output_path": str(output_path),
                    },
                    error=error,
                )
            finally:
                log_stream.close()
        finally:
            config_path.unlink(missing_ok=True)

    def run(self) -> ExecutionResult:
        if not self.config.dataset_root.is_dir():
            logger.error("dataset_root does not exist or is not a directory: %s", self.config.dataset_root)
            return ExecutionResult(
                execution_mode_used="kardome_legacy_stdout",
                case_results=[
                    CaseResult(
                        case_id="_dataset_",
                        input_path=self.config.dataset_root,
                        exit_code=-1,
                        status="failed",
                        metrics={},
                        artifacts={},
                        error="dataset_root_missing_or_not_a_directory",
                    )
                ],
            )
        runner_path = self.config.runner_path
        _tmp_runner_dir: str | None = None
        if not os.access(runner_path, os.X_OK):
            _tmp_runner_dir = tempfile.mkdtemp(prefix="bmt-runner-")
            # Copy the entire bundle dir so RPATH-relative .so files are found
            src_bundle = runner_path.parent
            tmp_bundle = Path(_tmp_runner_dir) / src_bundle.name
            shutil.copytree(src_bundle, tmp_bundle)
            runner_path = tmp_bundle / runner_path.name
            runner_path.chmod(0o755)
            logger.info("Copied runner bundle to %s (GCSFuse execute-bit workaround)", runner_path)
        try:
            template = json.loads(self.config.template_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.exception("Failed to read kardome input template %s", self.config.template_path)
            return ExecutionResult(
                execution_mode_used="kardome_legacy_stdout",
                case_results=[
                    CaseResult(
                        case_id="_template_",
                        input_path=self.config.template_path,
                        exit_code=-1,
                        status="failed",
                        metrics={},
                        artifacts={},
                        error=f"template_load_failed:{type(exc).__name__}:{exc}",
                    )
                ],
            )
        counter_re = counter_pattern_from_parsing_dict(self.config.parsing)
        results: list[CaseResult] = []
        try:
            for wav_path in sorted(self.config.dataset_root.rglob("*.wav")):
                rel = wav_path.relative_to(self.config.dataset_root)
                results.append(self._case_for_wav(wav_path, rel, template, counter_re, runner_path))
        finally:
            if _tmp_runner_dir:
                shutil.rmtree(_tmp_runner_dir, ignore_errors=True)

        return ExecutionResult(execution_mode_used="kardome_legacy_stdout", case_results=results)

    def _runner_env(self) -> dict[str, str]:
        env = dict(os.environ)
        runner_dir = self.config.runner_path.parent.resolve()
        ld_dirs = [str(runner_dir)]
        lib_dir = runner_dir / "lib"
        if lib_dir.is_dir():
            ld_dirs.append(str(lib_dir))
        # Merge extra env from plugin (e.g. deps_root) — treat runner_env as additions,
        # not a replacement for os.environ. Accumulate extra LD_LIBRARY_PATH entries.
        env.update(
            {k: v for k, v in self.config.runner_env.items() if k != "LD_LIBRARY_PATH"},
        )
        extra_ld = self.config.runner_env.get("LD_LIBRARY_PATH", "").strip()
        if extra_ld:
            ld_dirs.append(extra_ld)
        existing = env.get("LD_LIBRARY_PATH", "").strip()
        env["LD_LIBRARY_PATH"] = ":".join(ld_dirs + ([existing] if existing else []))
        return env
