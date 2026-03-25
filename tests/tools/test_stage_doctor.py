"""Smoke tests for ``tools bmt stage doctor``."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_doctor_sk_project_exits_zero(repo_stage_root: Path) -> None:
    from tools.bmt.stage_doctor import doctor_stage_project

    code, lines = doctor_stage_project(stage_root=repo_stage_root, project="sk")
    assert code == 0, "\n".join(lines)
