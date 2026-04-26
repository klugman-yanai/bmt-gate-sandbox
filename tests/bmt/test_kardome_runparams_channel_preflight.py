"""Leg-level channel handling for ``KardomeRunparamsExecutor``.

When ``expected_channels`` is set (SK manifests), only ``*.wav`` files whose RIFF
``NumChannels`` match are executed; other channel layouts are skipped with a warning so
mixed 4ch/8ch folders can still run the 8ch leg. When ``expected_channels`` is unset, every
``.wav`` is considered and heterogeneous channel counts fail the leg before
``kardome_runner`` runs.
"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime import kardome_runparams
from runtime.kardome_runparams import (
    KardomeRunparamsConfig,
    KardomeRunparamsExecutor,
    _probe_wav_channels,
)
from tests.sk_runner_repo_paths import KARDOME_INPUT_TEMPLATE, SK_KARDOME_RUNNER

pytestmark = pytest.mark.unit


def _write_wav(path: Path, *, channels: int, sample_rate: int = 16000) -> None:
    """Write a minimal RIFF/WAVE PCM16 header — enough bytes for the header probe.

    The 44-byte canonical PCM header carries NumChannels at offset 22 (u16 LE); our probe
    only reads that offset, so a zero-length data section suffices.
    """
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    header = (
        b"RIFF"
        + struct.pack("<I", 36)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + struct.pack("<H", 1)
        + struct.pack("<H", channels)
        + struct.pack("<I", sample_rate)
        + struct.pack("<I", byte_rate)
        + struct.pack("<H", block_align)
        + struct.pack("<H", bits_per_sample)
        + b"data"
        + struct.pack("<I", 0)
    )
    path.write_bytes(header)


def _dirs(tmp: Path) -> tuple[Path, Path, Path, Path]:
    ds = tmp / "ds"
    runtime = tmp / "runtime"
    outputs = tmp / "outputs"
    logs = tmp / "logs"
    for p in (ds, runtime, outputs, logs):
        p.mkdir(parents=True, exist_ok=True)
    return ds, runtime, outputs, logs


def _executor(
    tmp: Path,
    ds: Path,
    runtime: Path,
    outputs: Path,
    logs: Path,
    *,
    expected_channels: int | None,
) -> KardomeRunparamsExecutor:
    return KardomeRunparamsExecutor(
        KardomeRunparamsConfig(
            runner_path=SK_KARDOME_RUNNER,
            template_path=KARDOME_INPUT_TEMPLATE,
            dataset_root=ds,
            runtime_root=runtime,
            outputs_root=outputs,
            logs_root=logs,
            expected_channels=expected_channels,
        )
    )


def test_probe_reads_channels_from_standard_header(tmp_path: Path) -> None:
    wav = tmp_path / "a.wav"
    _write_wav(wav, channels=8)
    assert _probe_wav_channels(wav) == 8


def test_probe_returns_none_on_short_file(tmp_path: Path) -> None:
    wav = tmp_path / "tiny.wav"
    wav.write_bytes(b"RIFF")
    assert _probe_wav_channels(wav) is None


def test_probe_returns_none_on_non_wav(tmp_path: Path) -> None:
    wav = tmp_path / "garbage.wav"
    wav.write_bytes(b"\x00" * 64)
    assert _probe_wav_channels(wav) is None


def test_all_probes_inconclusive_no_expected_filter_runs_per_file(tmp_path: Path) -> None:
    """Without ``expected_channels``, inconclusive probes do not pre-filter the run list."""
    ds, runtime, outputs, logs = _dirs(tmp_path)
    (ds / "a.wav").write_bytes(b"\x00" * 32)
    (ds / "b.wav").write_bytes(b"RIFF")
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=None)

    class _FakeProc:
        returncode = 0

    with patch.object(kardome_runparams.subprocess, "run", return_value=_FakeProc()) as run_mock:
        result = ex.run()

    assert run_mock.call_count == 2
    assert all(r.case_id != "_channel_mismatch_" for r in result.case_results)


def test_all_probes_inconclusive_with_expected_filter_fails_leg(tmp_path: Path) -> None:
    """With ``expected_channels``, inconclusive files are skipped and none may remain."""
    ds, runtime, outputs, logs = _dirs(tmp_path)
    (ds / "a.wav").write_bytes(b"\x00" * 32)
    (ds / "b.wav").write_bytes(b"RIFF")
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=8)

    with patch.object(kardome_runparams.subprocess, "run") as run_mock:
        result = ex.run()

    assert run_mock.call_count == 0
    assert len(result.case_results) == 1
    assert "no_wavs_match_expected_channels" in (result.case_results[0].error or "")


def test_heterogeneous_channel_layout_fails_leg_without_subprocess(tmp_path: Path) -> None:
    ds, runtime, outputs, logs = _dirs(tmp_path)
    _write_wav(ds / "eight.wav", channels=8)
    _write_wav(ds / "four.wav", channels=4)
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=None)

    with patch.object(kardome_runparams.subprocess, "run") as run_mock:
        result = ex.run()

    assert run_mock.call_count == 0
    assert len(result.case_results) == 1
    case = result.case_results[0]
    assert case.case_id == "_channel_mismatch_"
    assert case.status == "failed"
    assert "channel_layout_heterogeneous" in (case.error or "")
    assert "4ch:1wav" in (case.error or "")
    assert "8ch:1wav" in (case.error or "")


def test_mixed_folder_runs_only_expected_channel_wavs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """``expected_channels=8`` skips 4ch files and runs the rest."""
    ds, runtime, outputs, logs = _dirs(tmp_path)
    _write_wav(ds / "a_first.wav", channels=8)
    _write_wav(ds / "b_second.wav", channels=4)
    _write_wav(ds / "c_third.wav", channels=8)
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=8)

    class _FakeProc:
        returncode = 0

    with (
        caplog.at_level("WARNING"),
        patch.object(kardome_runparams.subprocess, "run", return_value=_FakeProc()) as run_mock,
    ):
        result = ex.run()

    assert run_mock.call_count == 2
    assert len(result.case_results) == 2
    assert all(r.case_id != "_channel_mismatch_" for r in result.case_results)
    assert "b_second.wav" in caplog.text
    assert "not running this file" in caplog.text


def test_channel_match_runs_normally(tmp_path: Path) -> None:
    ds, runtime, outputs, logs = _dirs(tmp_path)
    _write_wav(ds / "a.wav", channels=4)
    _write_wav(ds / "b.wav", channels=4)
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=4)

    class _FakeProc:
        returncode = 0

    with patch.object(kardome_runparams.subprocess, "run", return_value=_FakeProc()) as run_mock:
        result = ex.run()

    assert run_mock.call_count == 2
    assert len(result.case_results) == 2
    assert all(r.case_id != "_channel_mismatch_" for r in result.case_results)


def test_homogeneous_dataset_runs_even_without_manifest_hint(tmp_path: Path) -> None:
    ds, runtime, outputs, logs = _dirs(tmp_path)
    _write_wav(ds / "a.wav", channels=8)
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=None)

    class _FakeProc:
        returncode = 0

    with patch.object(kardome_runparams.subprocess, "run", return_value=_FakeProc()) as run_mock:
        result = ex.run()

    assert run_mock.call_count == 1
    assert result.case_results[0].case_id != "_channel_mismatch_"


def test_no_wavs_match_expected_channels_fails_leg(tmp_path: Path) -> None:
    ds, runtime, outputs, logs = _dirs(tmp_path)
    _write_wav(ds / "a.wav", channels=8)
    _write_wav(ds / "b.wav", channels=8)
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=4)

    with patch.object(kardome_runparams.subprocess, "run") as run_mock:
        result = ex.run()

    assert run_mock.call_count == 0
    assert len(result.case_results) == 1
    assert "no_wavs_match_expected_channels:expected=4" in (result.case_results[0].error or "")


def test_unreadable_first_wav_skipped_when_expected_set(tmp_path: Path) -> None:
    """Inconclusive probe skips under ``expected_channels``; valid 4ch files still run when expected is 4."""
    ds, runtime, outputs, logs = _dirs(tmp_path)
    (ds / "first.wav").write_bytes(b"RIFF")
    _write_wav(ds / "second.wav", channels=4)
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=4)

    class _FakeProc:
        returncode = 0

    with patch.object(kardome_runparams.subprocess, "run", return_value=_FakeProc()) as run_mock:
        result = ex.run()

    assert run_mock.call_count == 1
    assert all(r.case_id != "_channel_mismatch_" for r in result.case_results)
    assert result.case_results[0].case_id == "second.wav"


def test_committed_sk_leg_configs_declare_eight_channels() -> None:
    """SK manifests keep ``expected_channels`` so mixed folders can filter to 8ch runs."""
    import json as _json

    repo_root = Path(__file__).resolve().parents[2]
    for leg in ("false_alarms", "false_rejects"):
        data = _json.loads((repo_root / "plugins/projects/sk" / f"{leg}.json").read_text(encoding="utf-8"))
        assert data["plugin_config"].get("expected_channels") == 8, leg
