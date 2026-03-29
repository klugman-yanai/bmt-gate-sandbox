"""``bmtplugin`` re-exports ``backend.runtime.sdk.contributor`` (often ``import bmtplugin as bmt``)."""

from __future__ import annotations

import bmtplugin as bmt
import pytest
from backend.runtime.sdk import contributor

pytestmark = pytest.mark.unit


def test_bmtplugin_reexports_contributor_surface() -> None:
    assert bmt.BmtPlugin is contributor.BmtPlugin
    assert bmt.__all__ == contributor.__all__
    assert "BmtPlugin" in bmt.__all__
