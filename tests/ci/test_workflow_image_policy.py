"""Workflow guardrails for hardened pre-baked image policy."""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    # Tests can move around; resolve repo root by walking upward.
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / ".github").is_dir() and (parent / "gcp").is_dir():
            return parent
    raise RuntimeError(f"Unable to resolve repo root from {here}")


def test_bmt_image_build_enforces_family_policy() -> None:
    workflow = (_repo_root() / ".github" / "workflows" / "bmt-image-build.yml").read_text(
        encoding="utf-8"
    )
    assert "Enforce image family policy" in workflow
    assert "BMT_EXPECTED_IMAGE_FAMILY" in workflow
    assert "BMT_EXPECTED_BASE_IMAGE_FAMILY" in workflow
    assert "PKR_VAR_base_image_family" in workflow
    assert "PKR_VAR_base_image_project" in workflow


def test_bmt_vm_provision_enforces_runtime_family_policy() -> None:
    workflow = (_repo_root() / ".github" / "workflows" / "bmt-vm-provision.yml").read_text(
        encoding="utf-8"
    )
    assert "Enforce runtime image policy" in workflow
    assert "BMT_EXPECTED_IMAGE_FAMILY" in workflow
    assert "gcloud compute images describe" in workflow
