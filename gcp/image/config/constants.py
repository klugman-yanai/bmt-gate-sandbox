"""Shared constants for BMT GCP code.

This module is the single source of truth for PUBSUB_TOPIC_NAME, STATUS_CONTEXT, DEFAULT_REPO_ROOT,
and image build defaults (DEFAULT_IMAGE_FAMILY, DEFAULT_BASE_IMAGE_FAMILY, DEFAULT_BASE_IMAGE_PROJECT).
- Code and CI read these directly. Terraform cannot import Python, so it keeps matching literals in
  main.tf / variables.tf; tests/infra/test_terraform_bmt_config_parity.py fails if they diverge.
"""

from __future__ import annotations

HTTP_TIMEOUT = 30
GITHUB_API_VERSION = "2022-11-28"
EXECUTABLE_MODE = 0o111

# Pub/Sub and GitHub status (single source of truth; Terraform topic name must match PUBSUB_TOPIC_NAME).
PUBSUB_TOPIC_NAME = "bmt-triggers"
STATUS_CONTEXT = "BMT Gate"

# VM path (Terraform bmt_repo_root default must match).
DEFAULT_REPO_ROOT = "/opt/bmt"

# Image build / policy defaults (single source; Terraform image_family default must match DEFAULT_IMAGE_FAMILY).
DEFAULT_IMAGE_FAMILY = "bmt-runtime"
DEFAULT_BASE_IMAGE_FAMILY = "ubuntu-2204-lts"
DEFAULT_BASE_IMAGE_PROJECT = "ubuntu-os-cloud"
