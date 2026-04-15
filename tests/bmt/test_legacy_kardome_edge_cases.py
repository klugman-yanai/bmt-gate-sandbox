"""Unit tests for graceful failures in LegacyKardomeStdoutExecutor."""

from __future__ import annotations

import subprocess
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime import legacy_kardome
from runtime.legacy_kardome import LegacyKardomeStdoutConfig, LegacyKardomeStdoutExecutor

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


def _make_executor(dataset_root: Path, tmp_path: Path) -> LegacyKardomeStdoutExecutor:
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
            dataset_root=dataset_root,
            runtime_root=runtime,
            outputs_root=outputs,
            logs_root=logs,
        )
    )


def _write_manifest(ds: Path, names: list[str]) -> None:
    import json

    manifest = {
        "schema_version": 1,
        "project": "test",
        "dataset": "test_ds",
        "bucket": "test-bucket",
        "prefix": "projects/test/inputs/test_ds",
        "generated_at": "2024-01-01T00:00:00Z",
        "files": [{"name": n, "size_bytes": 4, "sha256": "", "updated": ""} for n in names],
    }
    (ds / "dataset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_manifest_missing_files_returns_dataset_incomplete_error(tmp_path: Path) -> None:
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "present.wav").write_bytes(b"RIFF")
    _write_manifest(ds, ["present.wav", "missing.wav"])

    result = _make_executor(ds, tmp_path).run()

    assert len(result.case_results) == 1
    assert result.case_results[0].case_id == "_dataset_"
    assert "dataset_incomplete" in result.case_results[0].error
    assert "missing.wav" in result.case_results[0].error


def test_manifest_all_files_present_proceeds_past_completeness_check(tmp_path: Path) -> None:
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "a.wav").write_bytes(b"RIFF")
    (ds / "b.wav").write_bytes(b"RIFF")
    _write_manifest(ds, ["a.wav", "b.wav"])

    ex = _make_executor(ds, tmp_path)
    assert ex._check_manifest_completeness() == []


def test_no_manifest_proceeds_without_check(tmp_path: Path) -> None:
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "a.wav").write_bytes(b"RIFF")
    # No dataset_manifest.json written

    ex = _make_executor(ds, tmp_path)
    assert ex._check_manifest_completeness() == []


def test_corrupt_manifest_logs_warning_and_proceeds(tmp_path: Path) -> None:
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "a.wav").write_bytes(b"RIFF")
    (ds / "dataset_manifest.json").write_text("{not json}", encoding="utf-8")

    ex = _make_executor(ds, tmp_path)
    assert ex._check_manifest_completeness() == []


def test_gcsfuse_workaround_copies_binary_and_so_not_inputs(tmp_path: Path) -> None:
    """Runner lacks execute bit (GCSFuse mount): only binary + .so copied, not inputs/ dir."""
    # Simulate projects/sk/ structure: runner + libKardome.so + huge inputs/ subdir
    sk_dir = tmp_path / "sk"
    sk_dir.mkdir()
    runner = sk_dir / "kardome_runner"
    runner.write_bytes(b"#!/bin/sh\n")
    # Explicitly remove execute bit so os.access returns False
    runner.chmod(0o644)
    (sk_dir / "libKardome.so").write_bytes(b"ELF")
    inputs_dir = sk_dir / "inputs"
    inputs_dir.mkdir()
    (inputs_dir / "huge.wav").write_bytes(b"x" * 100)

    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "a.wav").write_bytes(b"RIFF")
    runtime, outputs, logs = _minimal_dirs(tmp_path)
    tpl = tmp_path / "t.json"
    tpl.write_text("{}", encoding="utf-8")

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

    # Capture the temp bundle directory contents while it still exists (before finally-cleanup)
    captured: dict[str, object] = {}

    def _mock_run(cmd: list[str], **_kwargs: object) -> object:
        runner_used = Path(cmd[0])
        tmp_bundle_dir = runner_used.parent
        captured["runner_used"] = runner_used
        captured["inputs_exists"] = (tmp_bundle_dir / "inputs").exists()
        captured["so_exists"] = (tmp_bundle_dir / "libKardome.so").exists()
        return types.SimpleNamespace(returncode=0)

    with patch.object(legacy_kardome.subprocess, "run", side_effect=_mock_run):
        ex.run()

    assert captured, "subprocess.run was not called"
    # Runner was copied to a temp location (not invoked from the original GCSFuse path)
    assert captured["runner_used"] != runner
    # inputs/ must NOT have been copied — that would exhaust container disk
    assert not captured["inputs_exists"], "inputs/ must not be copied to temp"
    # The shared library alongside the binary should be copied for RPATH/$ORIGIN resolution
    assert captured["so_exists"], "libKardome.so must be copied to temp"
