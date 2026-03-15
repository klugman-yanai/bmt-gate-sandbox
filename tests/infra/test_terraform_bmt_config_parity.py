"""Ensure Terraform variable defaults and resource names stay in sync with gcp/image/config.

Source of truth for string constants used by both code and Terraform:
- gcp/image/config/constants.py: PUBSUB_TOPIC_NAME, STATUS_CONTEXT, DEFAULT_REPO_ROOT, image defaults
- gcp/image/config/bmt_config.py: BmtConfig defaults (handshake timeouts, etc.)

Terraform variables.tf and main.tf must match these where they duplicate values (e.g. topic name,
bmt_repo_root, bmt_status_context). These tests enforce that.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gcp.image.config.bmt_config import DEFAULT_REPO_ROOT, BmtConfig
from gcp.image.config.constants import (
    DEFAULT_IMAGE_FAMILY,
    PUBSUB_TOPIC_NAME,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _read_terraform_variables() -> str:
    path = _repo_root() / "infra" / "terraform" / "variables.tf"
    return path.read_text()


def _read_terraform_main() -> str:
    path = _repo_root() / "infra" / "terraform" / "main.tf"
    return path.read_text()


def test_terraform_bmt_repo_root_default_matches_bmt_config() -> None:
    """Terraform bmt_repo_root default must match bmt_config.DEFAULT_REPO_ROOT."""
    content = _read_terraform_variables()
    match = re.search(r'variable\s+"bmt_repo_root"\s*\{[^}]*default\s*=\s*"([^"]*)"', content, re.DOTALL)
    assert match, "bmt_repo_root variable with default not found in variables.tf"
    assert match.group(1) == DEFAULT_REPO_ROOT, (
        f"Terraform bmt_repo_root default {match.group(1)!r} != bmt_config.DEFAULT_REPO_ROOT {DEFAULT_REPO_ROOT!r}"
    )


def test_terraform_bmt_status_context_default_matches_bmt_config() -> None:
    """Terraform bmt_status_context default must match BmtConfig.bmt_status_context."""
    content = _read_terraform_variables()
    match = re.search(r'variable\s+"bmt_status_context"\s*\{[^}]*default\s*=\s*"([^"]*)"', content, re.DOTALL)
    assert match, "bmt_status_context variable with default not found in variables.tf"
    expected = BmtConfig().bmt_status_context
    assert match.group(1) == expected, (
        f"Terraform bmt_status_context default {match.group(1)!r} != BmtConfig.bmt_status_context {expected!r}"
    )


def test_terraform_bmt_handshake_timeout_sec_default_matches_bmt_config() -> None:
    """Terraform bmt_handshake_timeout_sec default must match BmtConfig.bmt_handshake_timeout_sec."""
    content = _read_terraform_variables()
    match = re.search(
        r'variable\s+"bmt_handshake_timeout_sec"\s*\{[^}]*default\s*=\s*(\d+)',
        content,
        re.DOTALL,
    )
    assert match, "bmt_handshake_timeout_sec variable with default not found in variables.tf"
    expected = BmtConfig().bmt_handshake_timeout_sec
    actual = int(match.group(1))
    assert actual == expected, (
        f"Terraform bmt_handshake_timeout_sec default {actual} != BmtConfig.bmt_handshake_timeout_sec {expected}"
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
