"""Tests for tools.remote.bucket_upload_wavs (archive handling, rsync, error surfacing)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.remote.bucket_upload_wavs import BucketUploadWavs


def test_archive_zip_routes_to_extraction_and_rsync(tmp_path: Path) -> None:
    """Passing a .zip file routes to extraction; rsync is invoked with extracted dir (no 'Missing source directory')."""
    zip_path = tmp_path / "dataset.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.wav", b"fake-wav")
    assert zip_path.is_file()

    with patch("tools.remote.bucket_upload_wavs.subprocess.run") as m_run:
        m_run.return_value.returncode = 0
        m_run.return_value.stderr = ""
        m_run.return_value.stdout = ""

        result = BucketUploadWavs().run(
            bucket="test-bucket",
            source_dir=str(zip_path),
            dest_prefix="sk/inputs/false_rejects",
            force=True,
        )

    assert result == 0
    # Should not have errored with "Missing source directory"; rsync was invoked
    rsync_calls = [c for c in m_run.call_args_list if c[0] and "rsync" in (c[0][0] if c[0] else [])]
    assert len(rsync_calls) >= 1
    cmd_args = rsync_calls[0][0][0]  # first call's first positional arg (the list)
    # Source was a local path (temp dir; may be removed after run, so check it looked like a path)
    source_args = [a for a in cmd_args if isinstance(a, str) and not a.startswith("gs://") and "/" in a]
    assert len(source_args) >= 1
    # First such arg is the source path (gcloud storage rsync <source> <dest>)
    source_arg = source_args[0]
    assert "bmt_upload_wavs_" in source_arg or "tmp" in source_arg


def test_archive_with_single_top_level_dir_uses_inner_as_rsync_root(tmp_path: Path) -> None:
    """Archive containing one top-level dir (e.g. foo/a.wav) uses that inner dir as rsync source."""
    zip_path = tmp_path / "dataset.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("foo/a.wav", b"fake-wav")
    with patch("tools.remote.bucket_upload_wavs.subprocess.run") as m_run:
        m_run.return_value.returncode = 0
        m_run.return_value.stderr = ""
        m_run.return_value.stdout = ""
        BucketUploadWavs().run(
            bucket="b",
            source_dir=str(zip_path),
            dest_prefix="sk/inputs/false_rejects",
            force=True,
        )
    rsync_calls = [c for c in m_run.call_args_list if c[0] and "rsync" in (c[0][0] if c[0] else [])]
    assert len(rsync_calls) == 1
    cmd_args = rsync_calls[0][0][0]
    source_args = [a for a in cmd_args if isinstance(a, str) and "/" in a and not a.startswith("gs://")]
    assert len(source_args) >= 1
    assert "bmt_upload_wavs_" in source_args[0]


def test_rsync_stderr_surfaced_on_failure(tmp_path: Path) -> None:
    """When gcloud storage rsync fails, stderr is printed and non-zero return code is returned."""
    from io import StringIO

    err = StringIO()
    with patch("tools.remote.bucket_upload_wavs.subprocess.run") as m_run:
        m_run.return_value.returncode = 1
        m_run.return_value.stderr = "NetworkError: connection refused"
        m_run.return_value.stdout = ""
        with patch("sys.stderr", err):
            result = BucketUploadWavs().run(
                bucket="b",
                source_dir=str(tmp_path),
                dest_prefix="sk/inputs/false_rejects",
                force=True,
            )
    assert result == 1
    assert "connection refused" in err.getvalue()
