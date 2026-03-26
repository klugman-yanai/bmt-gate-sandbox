"""Tests for deduplicated runner uploads."""

from __future__ import annotations

from pathlib import Path

import pytest
from bmtgate.clients import gcs as gcs_module
from bmtgate.matrix.runner import RunnerManager, _pair_sha256_from_file_rows, _sha256_file

pytestmark = pytest.mark.contract


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _set_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    runner_dir = tmp_path / "artifact" / "Runners"
    lib_dir = tmp_path / "artifact" / "Kardome"
    _write(runner_dir / "kardome_runner", b"runner-binary-v1")
    _write(lib_dir / "libKardome.so", b"lib-binary-v1")

    monkeypatch.setenv("GCS_BUCKET", "bucket-a")
    monkeypatch.setenv("GCP_WIF_PROVIDER", "projects/1/locations/global/workloadIdentityPools/p/providers/p")
    monkeypatch.setenv("GCP_SA_EMAIL", "bmt@example.iam.gserviceaccount.com")
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("PROJECT", "sk")
    monkeypatch.setenv("PRESET", "sk_gcc_release")
    monkeypatch.setenv("SOURCE_REF", "abc123")
    monkeypatch.setenv("RUNNER_DIR", str(runner_dir))
    monkeypatch.setenv("LIB_DIR", str(lib_dir))
    return runner_dir, lib_dir


def _sha(path: Path) -> str:
    return _sha256_file(path)


def test_upload_runner_uploads_all_when_remote_meta_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_env(monkeypatch, tmp_path)

    monkeypatch.setattr(gcs_module, "download_json", lambda _uri: (None, "missing"))
    write_calls: list[str] = []
    monkeypatch.setattr(gcs_module, "write_object", lambda uri, _data: write_calls.append(uri))
    monkeypatch.setattr(gcs_module, "upload_json", lambda uri, _payload: write_calls.append(uri))

    RunnerManager.from_env().upload()

    assert len(write_calls) >= 2
    assert any("kardome_runner" in u or "runner_meta.json" in u for u in write_calls)


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

    monkeypatch.setattr(gcs_module, "download_json", lambda _uri: (remote_meta, None))
    write_calls: list[str] = []
    monkeypatch.setattr(gcs_module, "write_object", lambda uri, _data: write_calls.append(uri))
    monkeypatch.setattr(gcs_module, "upload_json", lambda uri, _payload: write_calls.append(uri))

    RunnerManager.from_env().upload()

    assert len(write_calls) >= 1
    assert any("runner.slsa.json" in u for u in write_calls)


def test_upload_runner_reuploads_both_when_pair_digest_changes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pair checksum: any local/remote mismatch for the runner+lib set re-uploads both objects."""
    runner_dir, lib_dir = _set_env(monkeypatch, tmp_path)
    runner_path = runner_dir / "kardome_runner"
    lib_path = lib_dir / "libKardome.so"
    remote_meta = {
        "files": [
            {"name": "kardome_runner", "size": runner_path.stat().st_size, "sha256": "deadbeef"},
            {"name": "libKardome.so", "size": lib_path.stat().st_size, "sha256": _sha(lib_path)},
        ]
    }

    monkeypatch.setattr(gcs_module, "download_json", lambda _uri: (remote_meta, None))
    write_calls: list[str] = []
    monkeypatch.setattr(gcs_module, "write_object", lambda uri, _data: write_calls.append(uri))
    monkeypatch.setattr(gcs_module, "upload_json", lambda uri, _payload: write_calls.append(uri))

    RunnerManager.from_env().upload()

    joined = write_calls
    assert any("kardome_runner" in u for u in joined)
    assert any("libKardome.so" in u for u in joined)
    assert any("runner_meta.json" in u for u in joined)


def test_pair_sha256_stable_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner_dir, lib_dir = _set_env(monkeypatch, tmp_path)
    runner_path = runner_dir / "kardome_runner"
    lib_path = lib_dir / "libKardome.so"
    rows = [
        {"name": "kardome_runner", "sha256": _sha(runner_path)},
        {"name": "libKardome.so", "sha256": _sha(lib_path)},
    ]
    assert _pair_sha256_from_file_rows(list(reversed(rows))) == _pair_sha256_from_file_rows(rows)


def test_upload_runner_skips_when_stored_pair_sha256_matches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner_dir, lib_dir = _set_env(monkeypatch, tmp_path)
    runner_path = runner_dir / "kardome_runner"
    lib_path = lib_dir / "libKardome.so"
    rows = [
        {"name": "kardome_runner", "sha256": _sha(runner_path)},
        {"name": "libKardome.so", "sha256": _sha(lib_path)},
    ]
    pair = _pair_sha256_from_file_rows(rows)
    remote_meta = {
        "pair_sha256": pair,
        "files": [
            {"name": "kardome_runner", "size": 0, "sha256": "stale"},
            {"name": "libKardome.so", "size": 0, "sha256": "stale"},
        ],
    }

    monkeypatch.setattr(gcs_module, "download_json", lambda _uri: (remote_meta, None))
    write_calls: list[str] = []
    monkeypatch.setattr(gcs_module, "write_object", lambda uri, _data: write_calls.append(uri))
    monkeypatch.setattr(gcs_module, "upload_json", lambda uri, _payload: write_calls.append(uri))

    RunnerManager.from_env().upload()

    assert any("runner.slsa.json" in u for u in write_calls)
    assert not any("kardome_runner" in u for u in write_calls)
    assert not any("libKardome.so" in u for u in write_calls)
    assert not any("runner_meta.json" in u for u in write_calls)
