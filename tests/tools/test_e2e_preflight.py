"""Unit tests for e2e preflight secret selection."""

from __future__ import annotations

import pytest

from tools.repo.e2e_preflight import (
    GITHUB_APP_SECRETS_DEV,
    GITHUB_APP_SECRETS_PRIMARY,
    required_actions_app_secret_names,
)

pytestmark = pytest.mark.unit


def test_required_secrets_kardome_org_uses_primary() -> None:
    names = required_actions_app_secret_names("Kardome-org/core-main")
    assert names == GITHUB_APP_SECRETS_PRIMARY


def test_required_secrets_other_owner_uses_dev() -> None:
    names = required_actions_app_secret_names("klugman-yanai/bmt-gcloud")
    assert names == GITHUB_APP_SECRETS_DEV
