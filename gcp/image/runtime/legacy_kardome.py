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

from gcp.image.runtime.sdk.results import CaseResult, ExecutionResult

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


def _counter_regex(parsing: dict[str, Any]) -> re.Pattern[str]:
    pattern = str(parsing.get("counter_pattern", "")).strip()
    if pattern:
        return re.compile(pattern)
    keyword = str(parsing.get("keyword", "NAMUH")).strip()
    return re.compile(rf"Hi {re.escape(keyword)} counter = (\d+)")


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


def _read_counter(log_path: Path, counter_re: re.Pattern[str]) -> int | None:
    """Return counter value from log, or None if not found.

    None means the runner did not produce the expected counter line — callers
    should treat this as a failure regardless of the process exit code.
    """
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if "\ufffd" in text:
        logger.warning("Log file %s contains encoding replacement characters", log_path)
    matches = counter_re.findall(text)
    if not matches:
        logger.warning("Counter pattern %r not found in %s", counter_re.pattern, log_path)
        return None
    return int(matches[-1])


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

    def run(self) -> ExecutionResult:
        if not self.config.dataset_root.is_dir():
            raise RuntimeError(f"dataset_root does not exist or is not a directory: {self.config.dataset_root}")
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
        template = json.loads(self.config.template_path.read_text(encoding="utf-8"))
        counter_re = _counter_regex(self.config.parsing)
        results: list[CaseResult] = []
        try:
            for wav_path in sorted(self.config.dataset_root.rglob("*.wav")):
                rel = wav_path.relative_to(self.config.dataset_root)
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
                    with log_path.open("w", encoding="utf-8") as log_file:
                        proc = subprocess.run(
                            [str(runner_path), str(config_path)],
                            cwd=str(self.config.runtime_root),
                            env=self._runner_env(),
                            stdout=log_file,
                            stderr=subprocess.STDOUT,
                            check=False,
                        )
                    counter = _read_counter(log_path, counter_re)
                    counter_found = counter is not None
                    ok = proc.returncode == 0 and counter_found
                    error = (
                        "" if ok else "counter_not_found" if proc.returncode == 0 else f"runner_exit_{proc.returncode}"
                    )
                    results.append(
                        CaseResult(
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
                    )
                finally:
                    config_path.unlink(missing_ok=True)
        finally:
            if _tmp_runner_dir:
                shutil.rmtree(_tmp_runner_dir, ignore_errors=True)

        return ExecutionResult(execution_mode_used="kardome_legacy_stdout", case_results=results)

    def _runner_env(self) -> dict[str, str]:
        if self.config.runner_env:
            return dict(self.config.runner_env)
        env = dict(os.environ)
        runner_dir = self.config.runner_path.parent.resolve()
        ld_dirs = [str(runner_dir)]
        lib_dir = runner_dir / "lib"
        if lib_dir.is_dir():
            ld_dirs.append(str(lib_dir))
        existing = env.get("LD_LIBRARY_PATH", "").strip()
        env["LD_LIBRARY_PATH"] = ":".join(ld_dirs + ([existing] if existing else []))
        return env
