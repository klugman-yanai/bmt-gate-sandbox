"""Tests for FUSE mount detection in BmtManagerBase."""

from pathlib import Path
from unittest.mock import patch

from gcp.image.projects.shared.bmt_manager_base import BmtManagerBase


def test_fuse_not_mounted_when_dir_missing() -> None:
    """fuse_mounted is False when /mnt/runtime does not exist."""
    with patch.object(Path, "is_dir", return_value=False):
        assert BmtManagerBase.is_fuse_available() is False


def test_fuse_mounted_when_dir_exists() -> None:
    """fuse_mounted is True when /mnt/runtime exists."""
    with patch.object(Path, "is_dir", return_value=True):
        assert BmtManagerBase.is_fuse_available() is True


def test_fuse_inputs_root_resolves_to_mount(tmp_path: Path) -> None:
    """When FUSE is available, inputs resolve relative to mount root."""
    from gcp.image.projects.shared.bmt_manager_base import _fuse_inputs_root

    result = _fuse_inputs_root("projects/sk/inputs/false_rejects")
    assert result == Path("/mnt/runtime/projects/sk/inputs/false_rejects")
