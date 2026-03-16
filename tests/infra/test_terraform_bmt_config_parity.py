"""Pulumi config defaults must match gcp/image/config where shared."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from gcp.image.config.bmt_config import DEFAULT_REPO_ROOT
from gcp.image.config.constants import DEFAULT_IMAGE_FAMILY, PUBSUB_TOPIC_NAME

# Load InfraConfig from the Pulumi project (not a regular package)
_pulumi_dir = Path(__file__).resolve().parents[2] / "infra" / "pulumi"
_spec = importlib.util.spec_from_file_location("pulumi_infra_config", _pulumi_dir / "config.py")
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["pulumi_infra_config"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
InfraConfig = _mod.InfraConfig


def test_pulumi_bmt_repo_root_default_matches_bmt_config() -> None:
    """Pulumi bmt_repo_root default must match bmt_config.DEFAULT_REPO_ROOT."""
    assert InfraConfig.bmt_repo_root == DEFAULT_REPO_ROOT, (
        f"Pulumi bmt_repo_root default {InfraConfig.bmt_repo_root!r} != bmt_config.DEFAULT_REPO_ROOT {DEFAULT_REPO_ROOT!r}"
    )


def test_pulumi_image_family_default_matches_constants() -> None:
    """Pulumi image_family default must match constants.DEFAULT_IMAGE_FAMILY."""
    assert InfraConfig.image_family == DEFAULT_IMAGE_FAMILY, (
        f"Pulumi image_family default {InfraConfig.image_family!r} != constants.DEFAULT_IMAGE_FAMILY {DEFAULT_IMAGE_FAMILY!r}"
    )


def test_pulumi_pubsub_topic_name_matches_constants() -> None:
    """Pulumi __main__.py triggers topic name must match constants.PUBSUB_TOPIC_NAME."""
    main_py = _pulumi_dir / "__main__.py"
    content = main_py.read_text(encoding="utf-8")
    # The topic resource uses name="bmt-triggers" literal
    assert f'name="{PUBSUB_TOPIC_NAME}"' in content or f"name='{PUBSUB_TOPIC_NAME}'" in content, (
        f"Pulumi __main__.py does not contain topic name={PUBSUB_TOPIC_NAME!r}"
    )
