"""Unit tests for tools.remote.preflight_bucket (JSON snapshots and image listing)."""

from __future__ import annotations

from pathlib import Path

import orjson
import pytest

from tools.remote.preflight_bucket import (
    PreflightSnapshot,
    gcp_image_files,
    load_code_paths_from_snapshot,
    run_preflight,
)

pytestmark = pytest.mark.unit


def test_snapshot_json_roundtrip(tmp_path: Path) -> None:
    snap = PreflightSnapshot(
        schema_version=1,
        bucket="my-bucket",
        generated_at="2025-01-01T00:00:00Z",
        code_rel_paths=frozenset({"a.py", "b/c.py"}),
        stats_code={"file_count": 2, "total_bytes": 10},
        stats_runtime={"file_count": 0, "total_bytes": 0},
        top_level_uris=("gs://my-bucket/code/",),
    )
    path = tmp_path / "p.json"
    path.write_bytes(snap.to_json_bytes())
    loaded = PreflightSnapshot.from_json_bytes(path.read_bytes())
    assert loaded.bucket == snap.bucket
    assert loaded.code_rel_paths == snap.code_rel_paths
    assert load_code_paths_from_snapshot(path) == {"a.py", "b/c.py"}


def test_load_snapshot_arg_json(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_bytes(
        orjson.dumps(
            {
                "schema_version": 1,
                "bucket": "b",
                "generated_at": "t",
                "code_rel_paths": ["z.py"],
                "stats": {"code": {}, "runtime": {}},
                "top_level_uris": [],
            }
        )
    )
    assert load_code_paths_from_snapshot(p) == {"z.py"}


def test_replay_rejects_txt_snapshot(tmp_path: Path) -> None:
    txt = tmp_path / "old.txt"
    txt.write_text("anything", encoding="utf-8")
    assert run_preflight(snapshot=txt, local_only=False) == 1


def test_gcp_image_files_respects_excludes(tmp_path: Path) -> None:
    img = tmp_path / "gcp" / "image"
    img.mkdir(parents=True)
    (img / "keep.py").write_text("x", encoding="utf-8")
    (img / "__pycache__").mkdir(parents=True)
    (img / "__pycache__" / "x.pyc").write_bytes(b"\0")
    paths = gcp_image_files(tmp_path)
    assert "keep.py" in paths
    assert not any("__pycache__" in p for p in paths)
