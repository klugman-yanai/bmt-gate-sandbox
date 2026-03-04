"""Tests for deduplicated runner uploads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli.commands import upload_runner


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _set_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    runner_dir = tmp_path / "artifact" / "Runners"
    lib_dir = tmp_path / "artifact" / "Kardome"
    _write(runner_dir / "kardome_runner", b"runner-binary-v1")
    _write(lib_dir / "libKardome.so", b"lib-binary-v1")

    monkeypatch.setenv("GCS_BUCKET", "bucket-a")
    monkeypatch.setenv("PROJECT", "sk")
    monkeypatch.setenv("PRESET", "sk_gcc_release")
    monkeypatch.setenv("SOURCE_REF", "abc123")
    monkeypatch.setenv("RUNNER_DIR", str(runner_dir))
    monkeypatch.setenv("LIB_DIR", str(lib_dir))
    return runner_dir, lib_dir


def _sha(path: Path) -> str:
    return upload_runner._sha256_file(path)


def test_upload_runner_uploads_all_when_remote_meta_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner_dir, lib_dir = _set_env(monkeypatch, tmp_path)

    monkeypatch.setattr(upload_runner.gcloud, "run_capture", lambda _cmd: (1, "not found"))
    cp_calls: list[list[str]] = []
    monkeypatch.setattr(
        upload_runner.gcloud,
        "run_capture_retry",
        lambda cmd: (cp_calls.append(cmd) or (0, "")),
    )

    upload_runner.run()

    assert len(cp_calls) == 3
    assert any(str(runner_dir / "kardome_runner") in call for call in cp_calls)
    assert any(str(lib_dir / "libKardome.so") in call for call in cp_calls)
    assert any("runner_meta.json" in " ".join(call) for call in cp_calls)


def test_upload_runner_skips_when_remote_hashes_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner_dir, lib_dir = _set_env(monkeypatch, tmp_path)
    runner_path = runner_dir / "kardome_runner"
    lib_path = lib_dir / "libKardome.so"
    remote_meta = {
        "files": [
            {"name": "kardome_runner", "size": runner_path.stat().st_size, "sha256": _sha(runner_path)},
            {"name": "libKardome.so", "size": lib_path.stat().st_size, "sha256": _sha(lib_path)},
        ]
    }

    monkeypatch.setattr(upload_runner.gcloud, "run_capture", lambda _cmd: (0, json.dumps(remote_meta)))
    cp_calls: list[list[str]] = []
    monkeypatch.setattr(
        upload_runner.gcloud,
        "run_capture_retry",
        lambda cmd: (cp_calls.append(cmd) or (0, "")),
    )

    upload_runner.run()

    assert cp_calls == []


def test_upload_runner_uploads_only_changed_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner_dir, lib_dir = _set_env(monkeypatch, tmp_path)
    runner_path = runner_dir / "kardome_runner"
    lib_path = lib_dir / "libKardome.so"
    remote_meta = {
        "files": [
            {"name": "kardome_runner", "size": runner_path.stat().st_size, "sha256": "deadbeef"},
            {"name": "libKardome.so", "size": lib_path.stat().st_size, "sha256": _sha(lib_path)},
        ]
    }

    monkeypatch.setattr(upload_runner.gcloud, "run_capture", lambda _cmd: (0, json.dumps(remote_meta)))
    cp_calls: list[list[str]] = []
    monkeypatch.setattr(
        upload_runner.gcloud,
        "run_capture_retry",
        lambda cmd: (cp_calls.append(cmd) or (0, "")),
    )

    upload_runner.run()

    assert len(cp_calls) == 2
    joined = [" ".join(call) for call in cp_calls]
    assert any("kardome_runner" in text and "runner_meta.json" not in text for text in joined)
    assert any("runner_meta.json" in text for text in joined)
    assert not any("libKardome.so" in text for text in joined)
