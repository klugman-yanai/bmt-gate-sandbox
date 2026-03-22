"""Workflow guardrails for hardened pre-baked image policy."""

from __future__ import annotations

import pytest

from tools.repo.paths import repo_root

pytestmark = pytest.mark.unit


def test_bmt_image_build_enforces_family_policy() -> None:
    workflow = (repo_root() / ".github" / "workflows" / "ops" / "bmt-image-build.yml").read_text(encoding="utf-8")
    assert "Enforce image family policy" in workflow
    assert "BMT_EXPECTED_IMAGE_FAMILY" in workflow
    assert "BMT_EXPECTED_BASE_IMAGE_FAMILY" in workflow
    assert "PKR_VAR_base_image_family" in workflow
    assert "PKR_VAR_base_image_project" in workflow
