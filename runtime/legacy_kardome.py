"""Compatibility adapter for current kardome per-file stdout parsing."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bmt_sdk.results import CaseResult, ExecutionResult

from runtime.config.constants import ENV_BMT_KARDOME_CASE_TIMEOUT_SEC
from runtime.stdout_counter_parse import counter_pattern_from_parsing_dict, read_counter_from_log

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


def _rewrite_json_paths_for_wav(
    config: dict[str, Any],
    wav_path: Path,
    output_path: Path,
    forced_key_excludes: frozenset[str] = frozenset(),
) -> None:
    """Rewrite ``*_PATH`` entries in the runner input so they point at the current case's WAV.

    ``forced_key_excludes`` lets a manifest opt specific keys out of the forced WAV-path
    rewrite (and the placeholder-based walk). The excluded keys keep their template value,
    which is how SK asks the harness to leave ``REF_PATH`` at the dummy placeholder so
    ``tinywav_open_read`` fails with ``is_ref == -1`` and the C-side refs channel guard
    short-circuits instead of refusing to run every 8-channel WAV against a 2-ref buffer.
    """
    wav_value = str(wav_path.resolve())
    output_value = str(output_path.resolve())

    config["MICS_PATH"] = wav_value
    config["KARDOME_OUTPUT_PATH"] = output_value
    if "USER_OUTPUT_PATH" in config:
        config["USER_OUTPUT_PATH"] = output_value

    for key in _FORCED_WAV_PATH_KEYS:
        if key in forced_key_excludes:
            continue
        if key in config:
            config[key] = wav_value

    protected: set[str] = {"MICS_PATH", "KARDOME_OUTPUT_PATH", "USER_OUTPUT_PATH"}
    protected.update(forced_key_excludes)
    _walk_and_rewrite_paths(config, wav_value, protected)


_WAV_NUM_CHANNELS_OFFSET = 22
_WAV_MIN_HEADER_BYTES = 24


def _probe_wav_channels(wav_path: Path) -> int | None:
    """Return the ``NumChannels`` field from a canonical RIFF/WAVE PCM header, or ``None``.

    Reads at most 24 bytes and does not decode samples; a ``None`` return means the file is
    too short, the RIFF/WAVE magic is absent, or a read error occurred. Callers treat
    ``None`` as "probe inconclusive" and skip the channel gate rather than blocking the leg.
    """
    try:
        with wav_path.open("rb") as fh:
            header = fh.read(_WAV_MIN_HEADER_BYTES)
    except OSError:
        return None
    if len(header) < _WAV_MIN_HEADER_BYTES or header[0:4] != b"RIFF" or header[8:12] != b"WAVE":
        return None
    (channels,) = struct.unpack_from("<H", header, _WAV_NUM_CHANNELS_OFFSET)
    return int(channels) if channels > 0 else None


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


def _copy_shared_libraries(src_dir: Path, dst_dir: Path) -> list[Path]:
    copied: list[Path] = []
    if not src_dir.is_dir():
        return copied
    dst_dir.mkdir(parents=True, exist_ok=True)
    for child in sorted(src_dir.iterdir()):
        if not child.is_file() or ".so" not in child.name:
            continue
        target = dst_dir / child.name
        shutil.copy2(child, target)
        copied.append(target)
    return copied


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
    deps_root: Path | None = None
    runner_env: dict[str, str] = field(default_factory=dict)
    # When set, probe the first wav's RIFF header once and fail the leg with a single
    # ``_channel_mismatch_`` case if its ``NumChannels`` differs from this value. Project
    # runners are built for a fixed mic count; mismatched inputs heap-corrupt the native
    # side, so we reject them up front instead of spraying per-file crash logs.
    expected_channels: int | None = None
    # Keys from ``_FORCED_WAV_PATH_KEYS`` that this leg wants *excluded* from the per-case
    # WAV-path rewrite. Used by SK to keep ``REF_PATH`` pointed at the dummy placeholder so
    # the runner's refs channel guard short-circuits (``is_ref == -1``) instead of refusing
    # to run every case because ``num_of_refs * 3`` can't hold an 8-channel mics WAV.
    forced_wav_path_keys_exclude: frozenset[str] = frozenset()


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
        runner_env: dict[str, str],
    ) -> CaseResult:
        log_path = self.config.logs_root / rel.with_suffix(rel.suffix + ".log")
        output_path = self.config.outputs_root / rel
        log_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cfg = copy.deepcopy(template)
        _rewrite_json_paths_for_wav(
            cfg,
            wav_path,
            output_path,
            forced_key_excludes=self.config.forced_wav_path_keys_exclude,
        )
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
                        env=runner_env,
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
                error = "" if ok else "counter_not_found" if proc.returncode == 0 else f"runner_exit_{proc.returncode}"
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

    def _check_manifest_completeness(self) -> list[str]:
        """Return relative paths of files listed in dataset_manifest.json that are not present on disk.

        Returns an empty list if the manifest is absent (no check performed) or all files are present.
        """
        manifest_path = self.config.dataset_root / "dataset_manifest.json"
        if not manifest_path.is_file():
            return []
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            logger.warning("Could not read dataset_manifest.json at %s — skipping completeness check", manifest_path)
            return []
        return [
            entry["name"]
            for entry in data.get("files", [])
            if isinstance(entry, dict) and not (self.config.dataset_root / str(entry.get("name", ""))).is_file()
        ]

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
        missing = self._check_manifest_completeness()
        if missing:
            logger.error(
                "Dataset incomplete: %d file(s) listed in dataset_manifest.json are not present on disk: %s",
                len(missing),
                missing,
            )
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
                        error=f"dataset_incomplete:{len(missing)}_missing:{missing[0]}",
                    )
                ],
            )
        runner_path = self.config.runner_path
        deps_root = self.config.deps_root if self.config.deps_root and self.config.deps_root.is_dir() else None
        _tmp_runner_dir: str | None = None
        if not os.access(runner_path, os.X_OK) or deps_root is not None:
            _tmp_runner_dir = tempfile.mkdtemp(prefix="bmt-runner-")
            # Copy only the native runtime bundle, not the whole project tree. Large input trees
            # under the runner directory would exhaust local disk, but native libs loaded straight
            # from GCSFuse have been a recurring source of Cloud Run instability.
            tmp_bundle = Path(_tmp_runner_dir) / runner_path.parent.name
            tmp_bundle.mkdir(parents=True, exist_ok=True)
            shutil.copy2(runner_path, tmp_bundle / runner_path.name)
            _copy_shared_libraries(runner_path.parent, tmp_bundle)
            src_lib = runner_path.parent / "lib"
            staged_lib = tmp_bundle / "lib"
            if src_lib.is_dir():
                shutil.copytree(src_lib, staged_lib, dirs_exist_ok=True)
            if deps_root is not None:
                _copy_shared_libraries(deps_root, staged_lib)
            runner_path = tmp_bundle / runner_path.name
            runner_path.chmod(0o755)
            logger.info("Staged runner bundle locally at %s (deps_root=%s)", runner_path.parent, deps_root or "<none>")
        runner_env = self._runner_env(runner_path)
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
            wavs = sorted(self.config.dataset_root.rglob("*.wav"))
            mismatch = self._channel_mismatch_if_any(wavs)
            if mismatch is not None:
                return ExecutionResult(execution_mode_used="kardome_legacy_stdout", case_results=[mismatch])
            for wav_path in wavs:
                rel = wav_path.relative_to(self.config.dataset_root)
                results.append(self._case_for_wav(wav_path, rel, template, counter_re, runner_path, runner_env))
        finally:
            if _tmp_runner_dir:
                shutil.rmtree(_tmp_runner_dir, ignore_errors=True)

        return ExecutionResult(execution_mode_used="kardome_legacy_stdout", case_results=results)

    def _channel_mismatch_if_any(self, wavs: list[Path]) -> CaseResult | None:
        """Probe the first wav once; return a failing CaseResult if its channel count differs.

        Returns ``None`` when no ``expected_channels`` is declared, the dataset is empty, or
        the probe is inconclusive (short/non-RIFF file). The first wav is treated as
        representative — leg datasets are built homogeneous by convention.
        """
        expected = self.config.expected_channels
        if expected is None or not wavs:
            return None
        first = wavs[0]
        actual = _probe_wav_channels(first)
        if actual is None:
            logger.warning("Channel probe inconclusive for %s — skipping channel gate for this leg", first)
            return None
        if actual == expected:
            return None
        rel = first.relative_to(self.config.dataset_root).as_posix()
        logger.error(
            "Channel mismatch on first wav: expected=%d got=%d probe=%s — failing leg without running kardome_runner",
            expected,
            actual,
            rel,
        )
        return CaseResult(
            case_id="_channel_mismatch_",
            input_path=first,
            exit_code=-1,
            status="failed",
            metrics={},
            artifacts={},
            error=f"channel_mismatch:expected={expected}:got={actual}:probe={rel}",
        )

    def _runner_env(self, runner_path: Path) -> dict[str, str]:
        env = dict(os.environ)
        runner_dir = runner_path.parent.resolve()
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
            ld_dirs.extend(path for path in extra_ld.split(":") if path)
        existing = env.get("LD_LIBRARY_PATH", "").strip()
        if existing:
            ld_dirs.extend(path for path in existing.split(":") if path)
        env["LD_LIBRARY_PATH"] = ":".join(dict.fromkeys(ld_dirs))
        return env
