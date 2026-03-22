"""Tests for local_digest() input-file guards.

Covers:
- 0.2: local_digest() excludes data files under projects/*/inputs/ (WAVs etc.)
- 0.2: local_digest() includes .keep and dataset_manifest.json under projects/*/inputs/
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.shared.bucket_sync import is_inputs_data_path, local_digest
from tools.shared.layout_patterns import FORBIDDEN_RUNTIME_SEED

pytestmark = pytest.mark.unit

# ── is_inputs_data_path ────────────────────────────────────────────────────────


def test_wav_under_inputs_is_data():
    assert is_inputs_data_path("projects/sk/inputs/false_rejects/ambient/cafe_001.wav") is True


def test_wav_in_nested_inputs_is_data():
    assert is_inputs_data_path("projects/any_project/inputs/dataset/subdir/file.wav") is True


def test_keep_under_inputs_is_not_data():
    assert is_inputs_data_path("projects/sk/inputs/false_rejects/.keep") is False


def test_manifest_under_inputs_is_not_data():
    assert is_inputs_data_path("projects/sk/inputs/false_rejects/dataset_manifest.json") is False


def test_non_inputs_path_is_not_data():
    assert is_inputs_data_path("projects/sk/kardome_runner") is False
    assert is_inputs_data_path("projects/sk/lib/libKardome.so") is False
    assert is_inputs_data_path("config/bmt_projects.json") is False


# ── local_digest() inputs exclusion ───────────────────────────────────────────


@pytest.fixture
def staging_tree(tmp_path: Path) -> Path:
    """Create a synthetic gcp/stage tree with runner, inputs (.keep + WAV), and manifest."""
    # Runner binary
    runner = tmp_path / "projects" / "sk" / "kardome_runner"
    runner.parent.mkdir(parents=True)
    runner.write_bytes(b"binary content")

    # .keep placeholder — must appear in digest
    keep = tmp_path / "projects" / "sk" / "inputs" / "false_rejects" / ".keep"
    keep.parent.mkdir(parents=True)
    keep.write_text("")

    # dataset_manifest.json — must appear in digest
    manifest = tmp_path / "projects" / "sk" / "inputs" / "false_rejects" / "dataset_manifest.json"
    manifest.write_text('{"schema_version": 1}')

    # WAV file — must NOT appear in digest
    wav = tmp_path / "projects" / "sk" / "inputs" / "false_rejects" / "ambient" / "test.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"\x52\x49\x46\x46" + b"\x00" * 40)  # RIFF header stub

    return tmp_path


def test_local_digest_excludes_wav_under_inputs(staging_tree: Path) -> None:
    """WAV files under projects/*/inputs/ must not be included in the digest."""
    _digest, count = local_digest(staging_tree, include_artifacts=False, exclude_patterns=FORBIDDEN_RUNTIME_SEED)
    # The tree has: kardome_runner, .keep, dataset_manifest.json, test.wav
    # Expected in digest: kardome_runner, .keep, dataset_manifest.json (NOT test.wav)
    assert count == 3, f"Expected 3 files in digest, got {count}"


def test_local_digest_includes_keep_under_inputs(staging_tree: Path) -> None:
    """.keep placeholder under inputs must be included in the digest."""
    digest_with_keep, count_with_keep = local_digest(
        staging_tree,
        include_artifacts=False,
        exclude_patterns=FORBIDDEN_RUNTIME_SEED,
    )
    # Remove .keep and recompute
    (staging_tree / "projects" / "sk" / "inputs" / "false_rejects" / ".keep").unlink()
    digest_without_keep, count_without_keep = local_digest(
        staging_tree,
        include_artifacts=False,
        exclude_patterns=FORBIDDEN_RUNTIME_SEED,
    )
    assert count_with_keep == count_without_keep + 1, ".keep should contribute to file count"
    assert digest_with_keep != digest_without_keep, ".keep should affect digest"


def test_local_digest_includes_manifest_under_inputs(staging_tree: Path) -> None:
    """dataset_manifest.json under inputs must be included in the digest."""
    digest_with, count_with = local_digest(
        staging_tree,
        include_artifacts=False,
        exclude_patterns=FORBIDDEN_RUNTIME_SEED,
    )
    (staging_tree / "projects" / "sk" / "inputs" / "false_rejects" / "dataset_manifest.json").unlink()
    digest_without, count_without = local_digest(
        staging_tree,
        include_artifacts=False,
        exclude_patterns=FORBIDDEN_RUNTIME_SEED,
    )
    assert count_with == count_without + 1, "dataset_manifest.json should contribute to file count"
    assert digest_with != digest_without, "dataset_manifest.json should affect digest"


def test_local_digest_wav_does_not_affect_digest(staging_tree: Path) -> None:
    """Adding more WAVs under inputs must not change the digest."""
    digest_before, count_before = local_digest(
        staging_tree,
        include_artifacts=False,
        exclude_patterns=FORBIDDEN_RUNTIME_SEED,
    )
    extra_wav = staging_tree / "projects" / "sk" / "inputs" / "false_rejects" / "extra.wav"
    extra_wav.write_bytes(b"\x52\x49\x46\x46" + b"\x00" * 40)
    digest_after, count_after = local_digest(
        staging_tree,
        include_artifacts=False,
        exclude_patterns=FORBIDDEN_RUNTIME_SEED,
    )
    assert digest_before == digest_after, "Extra WAV must not change digest"
    assert count_before == count_after, "Extra WAV must not change file count"
