"""Unit tests for graceful failures in LegacyKardomeStdoutExecutor."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from backend.runtime import legacy_kardome
from backend.runtime.legacy_kardome import LegacyKardomeStdoutConfig, LegacyKardomeStdoutExecutor

pytestmark = pytest.mark.unit


def _minimal_dirs(tmp: Path) -> tuple[Path, Path, Path]:
    runtime = tmp / "runtime"
    outputs = tmp / "outputs"
    logs = tmp / "logs"
    for p in (runtime, outputs, logs):
        p.mkdir(parents=True, exist_ok=True)
    return runtime, outputs, logs


def test_dataset_not_directory_returns_single_failed_case(tmp_path: Path) -> None:
    bad = tmp_path / "not_a_dir"
    bad.write_text("x", encoding="utf-8")
    runtime, outputs, logs = _minimal_dirs(tmp_path)
    runner = tmp_path / "kardome_runner"
    runner.write_text("#!/bin/sh\necho\n", encoding="utf-8")
    runner.chmod(0o755)
    tpl = tmp_path / "t.json"
    tpl.write_text("{}", encoding="utf-8")
    ex = LegacyKardomeStdoutExecutor(
        LegacyKardomeStdoutConfig(
            runner_path=runner,
            template_path=tpl,
            dataset_root=bad,
            runtime_root=runtime,
            outputs_root=outputs,
            logs_root=logs,
        )
    )
    result = ex.run()
    assert len(result.case_results) == 1
    assert result.case_results[0].case_id == "_dataset_"
    assert "dataset_root" in result.case_results[0].error


def test_invalid_template_json_returns_single_failed_case(tmp_path: Path) -> None:
    ds = tmp_path / "ds"
    ds.mkdir()
    runtime, outputs, logs = _minimal_dirs(tmp_path)
    runner = tmp_path / "kardome_runner"
    runner.write_text("#!/bin/sh\necho\n", encoding="utf-8")
    runner.chmod(0o755)
    tpl = tmp_path / "bad.json"
    tpl.write_text("{not json", encoding="utf-8")
    ex = LegacyKardomeStdoutExecutor(
        LegacyKardomeStdoutConfig(
            runner_path=runner,
            template_path=tpl,
            dataset_root=ds,
            runtime_root=runtime,
            outputs_root=outputs,
            logs_root=logs,
        )
    )
    result = ex.run()
    assert len(result.case_results) == 1
    assert result.case_results[0].case_id == "_template_"
    assert "template_load_failed" in result.case_results[0].error


def _executor_with_one_wav(tmp_path: Path) -> LegacyKardomeStdoutExecutor:
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "a.wav").write_bytes(b"RIFF")
    runtime, outputs, logs = _minimal_dirs(tmp_path)
    runner = tmp_path / "kardome_runner"
    runner.write_text("#!/bin/sh\necho\n", encoding="utf-8")
    runner.chmod(0o755)
    tpl = tmp_path / "t.json"
    tpl.write_text("{}", encoding="utf-8")
    return LegacyKardomeStdoutExecutor(
        LegacyKardomeStdoutConfig(
            runner_path=runner,
            template_path=tpl,
            dataset_root=ds,
            runtime_root=runtime,
            outputs_root=outputs,
            logs_root=logs,
        )
    )


def test_subprocess_timeout_yields_failed_case(tmp_path: Path) -> None:
    ex = _executor_with_one_wav(tmp_path)

    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="runner", timeout=1)

    with patch.object(legacy_kardome.subprocess, "run", side_effect=_boom):
        result = ex.run()
    assert len(result.case_results) == 1
    assert "timeout" in result.case_results[0].error.lower()


def test_subprocess_oserror_yields_failed_case(tmp_path: Path) -> None:
    ex = _executor_with_one_wav(tmp_path)
    with patch.object(legacy_kardome.subprocess, "run", side_effect=OSError("exec failed")):
        result = ex.run()
    assert len(result.case_results) == 1
    assert "runner_os_error" in result.case_results[0].error


def test_log_open_oserror_yields_failed_case(tmp_path: Path) -> None:
    ex = _executor_with_one_wav(tmp_path)
    real_open = Path.open

    def _open(
        self: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ):
        if mode == "w" and self.suffix == ".log":
            raise OSError("permission denied")
        return real_open(self, mode, buffering, encoding, errors, newline)

    with patch.object(Path, "open", _open):
        result = ex.run()
    assert len(result.case_results) == 1
    assert "log_open_failed" in result.case_results[0].error
