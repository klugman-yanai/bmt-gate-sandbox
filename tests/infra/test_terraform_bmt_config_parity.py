"""Terraform defaults and resource names must match gcp/image/config where shared."""

from __future__ import annotations

import re
from pathlib import Path

from gcp.image.config.bmt_config import DEFAULT_REPO_ROOT
from gcp.image.config.constants import DEFAULT_IMAGE_FAMILY, PUBSUB_TOPIC_NAME
from tools.repo.paths import repo_root, INFRA_TERRAFORM


def _read_terraform_variables() -> str:
    path = repo_root() / INFRA_TERRAFORM / "variables.tf"
    return path.read_text()


def _read_terraform_main() -> str:
    path = repo_root() / INFRA_TERRAFORM / "main.tf"
    return path.read_text()


def test_terraform_bmt_repo_root_default_matches_bmt_config() -> None:
    """Terraform bmt_repo_root default must match bmt_config.DEFAULT_REPO_ROOT."""
    content = _read_terraform_variables()
    match = re.search(r'variable\s+"bmt_repo_root"\s*\{[^}]*default\s*=\s*"([^"]*)"', content, re.DOTALL)
    assert match, "bmt_repo_root variable with default not found in variables.tf"
    assert match.group(1) == DEFAULT_REPO_ROOT, (
        f"Terraform bmt_repo_root default {match.group(1)!r} != bmt_config.DEFAULT_REPO_ROOT {DEFAULT_REPO_ROOT!r}"
    )


def test_terraform_image_family_default_matches_constants() -> None:
    """Terraform image_family default must match constants.DEFAULT_IMAGE_FAMILY."""
    content = _read_terraform_variables()
    match = re.search(
        r'variable\s+"image_family"\s*\{[^}]*default\s*=\s*"([^"]*)"',
        content,
        re.DOTALL,
    )
    assert match, "image_family variable with default not found in variables.tf"
    assert match.group(1) == DEFAULT_IMAGE_FAMILY, (
        f"Terraform image_family default {match.group(1)!r} != constants.DEFAULT_IMAGE_FAMILY {DEFAULT_IMAGE_FAMILY!r}"
    )


def test_terraform_pubsub_topic_name_matches_constants() -> None:
    """Terraform main.tf google_pubsub_topic.bmt_triggers name must match constants.PUBSUB_TOPIC_NAME."""
    content = _read_terraform_main()
    match = re.search(
        r'resource\s+"google_pubsub_topic"\s+"bmt_triggers"\s*\{[^}]*name\s*=\s*"([^"]*)"',
        content,
        re.DOTALL,
    )
    assert match, "google_pubsub_topic.bmt_triggers with name = not found in main.tf"
    assert match.group(1) == PUBSUB_TOPIC_NAME, (
        f"Terraform topic name {match.group(1)!r} != constants.PUBSUB_TOPIC_NAME {PUBSUB_TOPIC_NAME!r}"
    )
