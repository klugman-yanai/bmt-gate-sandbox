"""Tests for bulk ``publish-plugin`` manifest matching."""

from __future__ import annotations

import pytest

from tools.bmt.publisher import plugin_name_references_manifest

pytestmark = pytest.mark.unit


def test_plugin_name_references_workspace() -> None:
    assert plugin_name_references_manifest("main", "workspace:main") is True
    assert plugin_name_references_manifest("other", "workspace:main") is False


def test_plugin_name_references_published() -> None:
    ref = "published:main:sha256-deadbeef"
    assert plugin_name_references_manifest("main", ref) is True
    assert plugin_name_references_manifest("other", ref) is False
