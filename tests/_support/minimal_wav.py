"""Tiny valid PCM WAV files for runner integration tests (stdlib only)."""

from __future__ import annotations

import io
import wave
from pathlib import Path


def write_silence_wav(path: Path, *, frames: int = 800, sample_rate: int = 16_000) -> None:
    """Write a minimal mono 16-bit PCM WAV kardome_runner can open (tinywav / pipeline)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * frames)
    path.write_bytes(buf.getvalue())
