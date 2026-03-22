"""Tests for gcs_sync helpers (single local walk in sync_tree)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.shared import gcs_sync
from tools.shared.gcs_sync import sync_tree

pytestmark = pytest.mark.unit


def test_sync_tree_calls_iter_files_once(tmp_path: Path) -> None:
    """sync_tree must not walk the source tree twice."""
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.txt").write_text("a")
    sub = root / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b")

    client = MagicMock()
    bucket = MagicMock()
    client.bucket.return_value = bucket
    client.list_blobs.return_value = []

    call_count = {"n": 0}
    real_iter = gcs_sync.iter_files

    def counting_iter_files(r: Path) -> list[Path]:
        call_count["n"] += 1
        return real_iter(r)

    with patch.object(gcs_sync, "iter_files", side_effect=counting_iter_files):
        sync_tree(
            client=client,
            bucket_name="b",
            source_root=root,
            destination_prefix="pfx",
        )

    assert call_count["n"] == 1
