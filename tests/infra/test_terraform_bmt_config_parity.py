"""Pulumi config defaults must match shared runtime constants where applicable."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from backend.config.constants import DEFAULT_IMAGE_FAMILY

# Load InfraConfig from the Pulumi project (not a regular package)
_pulumi_dir = Path(__file__).resolve().parents[2] / "infra" / "pulumi"
_spec = importlib.util.spec_from_file_location("pulumi_infra_config", _pulumi_dir / "pulumi_stack_config.py")
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["pulumi_infra_config"] = _mod
_spec.loader.exec_module(_mod)
InfraConfig = _mod.InfraConfig

pytestmark = pytest.mark.unit


def test_pulumi_image_family_default_matches_constants() -> None:
    """Pulumi image_family default must match constants.DEFAULT_IMAGE_FAMILY."""
    assert InfraConfig.image_family == DEFAULT_IMAGE_FAMILY, (
        f"Pulumi image_family default {InfraConfig.image_family!r} != constants.DEFAULT_IMAGE_FAMILY {DEFAULT_IMAGE_FAMILY!r}"
    )
