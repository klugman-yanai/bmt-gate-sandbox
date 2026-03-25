"""Tests for :func:`gcp.image.runtime.sdk.manifest_build.build_default_bmt_manifest`."""

from __future__ import annotations

import pytest

from gcp.image.runtime.models import BmtManifest
from gcp.image.runtime.sdk.manifest_build import build_default_bmt_manifest

pytestmark = pytest.mark.unit


def test_build_default_round_trips_json() -> None:
    m = build_default_bmt_manifest("myproject", "mybench", plugin_ref="workspace:default")
    raw = m.model_dump_json(by_alias=True)
    again = BmtManifest.model_validate_json(raw)
    assert again.project == "myproject"
    assert again.bmt_slug == "mybench"
    assert again.inputs_prefix == "projects/myproject/inputs/mybench"
