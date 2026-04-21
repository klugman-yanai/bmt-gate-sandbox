"""Leg-level channel pre-flight: probe the first wav once, fail the leg cleanly on mismatch.

Rationale: The SK ``kardome_runner`` is built for a fixed channel count (4 mics). Feeding it
an 8-channel wav heap-corrupts its input buffers and aborts the process. We avoid ever
converting dataset files (the WAV ground truth is sacrosanct) and instead probe the first
wav's header once per leg against an ``expected_channels`` constraint declared in the leg
config. A mismatch surfaces as a single ``_channel_mismatch_`` case so the leg fails with a
human-readable error instead of spraying per-file crash logs.
"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime import legacy_kardome
from runtime.legacy_kardome import (
    LegacyKardomeStdoutConfig,
    LegacyKardomeStdoutExecutor,
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
) -> LegacyKardomeStdoutExecutor:
    return LegacyKardomeStdoutExecutor(
        LegacyKardomeStdoutConfig(
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


def test_channel_mismatch_fails_leg_with_single_case(tmp_path: Path) -> None:
    ds, runtime, outputs, logs = _dirs(tmp_path)
    _write_wav(ds / "first.wav", channels=8)
    (ds / "second.wav").write_bytes(b"RIFF")
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=4)

    with patch.object(legacy_kardome.subprocess, "run") as run_mock:
        result = ex.run()

    assert run_mock.call_count == 0, "subprocess must not run when channel mismatch is detected"
    assert len(result.case_results) == 1
    case = result.case_results[0]
    assert case.case_id == "_channel_mismatch_"
    assert case.status == "failed"
    assert "channel_mismatch" in case.error
    assert "expected=4" in case.error
    assert "got=8" in case.error


def test_channel_match_runs_normally(tmp_path: Path) -> None:
    ds, runtime, outputs, logs = _dirs(tmp_path)
    _write_wav(ds / "a.wav", channels=4)
    _write_wav(ds / "b.wav", channels=4)
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=4)

    class _FakeProc:
        returncode = 0

    with patch.object(legacy_kardome.subprocess, "run", return_value=_FakeProc()) as run_mock:
        result = ex.run()

    assert run_mock.call_count == 2
    assert len(result.case_results) == 2
    assert all(r.case_id != "_channel_mismatch_" for r in result.case_results)


def test_no_expected_channels_skips_probe(tmp_path: Path) -> None:
    ds, runtime, outputs, logs = _dirs(tmp_path)
    _write_wav(ds / "a.wav", channels=8)
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=None)

    class _FakeProc:
        returncode = 0

    with patch.object(legacy_kardome.subprocess, "run", return_value=_FakeProc()):
        result = ex.run()

    assert len(result.case_results) == 1
    assert result.case_results[0].case_id != "_channel_mismatch_"


def test_unreadable_first_wav_is_not_blocking(tmp_path: Path) -> None:
    """A probe that can't parse the header must not gate the leg — per-file crashes still
    yield clear ``runner_exit_*`` errors and the dataset may have a stray short file."""
    ds, runtime, outputs, logs = _dirs(tmp_path)
    (ds / "first.wav").write_bytes(b"RIFF")
    _write_wav(ds / "second.wav", channels=4)
    ex = _executor(tmp_path, ds, runtime, outputs, logs, expected_channels=4)

    class _FakeProc:
        returncode = 0

    with patch.object(legacy_kardome.subprocess, "run", return_value=_FakeProc()):
        result = ex.run()

    assert all(r.case_id != "_channel_mismatch_" for r in result.case_results)
    assert len(result.case_results) == 2


def test_committed_sk_leg_configs_declare_eight_channels() -> None:
    """SK datasets in the bucket are 8-channel; the leg JSON must keep the pre-flight
    declaration aligned so the runner receives matching inputs instead of tripping a
    channel-mismatch short-circuit.

    Historical note: these manifests declared ``expected_channels=4`` while the
    bucket datasets were 8-channel, which (by design) made every SK leg short-circuit
    to a ``_channel_mismatch_`` failure before `kardome_runner` ever executed — the
    pre-flight's intended behaviour for genuine mismatches, but not a runnable
    pipeline. Once the SK runner/libKardome.so rebuilt from
    ``core-main/SK_gcc_Release`` was confirmed to accept 8-channel inputs, the
    declaration was bumped to 8 to match the bucket's dataset reality. Flip both
    this assertion and the JSON fields together if/when the mic count changes in
    the runner again.
    """
    import json as _json

    repo_root = Path(__file__).resolve().parents[2]
    for leg in ("false_alarms", "false_rejects"):
        data = _json.loads((repo_root / "plugins/projects/sk" / f"{leg}.json").read_text(encoding="utf-8"))
        assert data["plugin_config"].get("expected_channels") == 8, leg
