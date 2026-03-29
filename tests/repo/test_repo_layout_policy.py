"""Repo layout policy regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.repo.repo_layout_policy import _existing_forbidden_paths

pytestmark = pytest.mark.unit


def test_existing_forbidden_paths_detects_nested_runtime_source_dirs(tmp_path: Path) -> None:
    (tmp_path / "backend" / "backend").mkdir(parents=True)
    (tmp_path / "backend" / "bmtplugin").mkdir(parents=True)

    assert _existing_forbidden_paths(tmp_path) == [
        "backend/backend",
        "backend/bmtplugin",
    ]


def test_existing_forbidden_paths_ignores_canonical_src_layout(tmp_path: Path) -> None:
    (tmp_path / "backend" / "src" / "backend").mkdir(parents=True)
    (tmp_path / "backend" / "src" / "bmtplugin").mkdir(parents=True)

    assert _existing_forbidden_paths(tmp_path) == []
