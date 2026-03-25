"""Round-trip tests for ``tools.bmt.manifest_serde`` (Pydantic v2 JSON)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gcp.image.runtime.models import BmtManifest
from tools.bmt.manifest_serde import read_bmt_manifest, write_bmt_manifest_json

pytestmark = pytest.mark.unit


def test_write_read_round_trip_preserves_results_prefix_alias(tmp_path: Path) -> None:
    path = tmp_path / "bmt.json"
    m = BmtManifest.model_validate_json(
        """
        {
          "schema_version": 1,
          "project": "p",
          "bmt_slug": "s",
          "bmt_id": "00000000-0000-5000-8000-000000000001",
          "enabled": false,
          "plugin_ref": "workspace:default",
          "inputs_prefix": "projects/p/inputs/s",
          "results_prefix": "projects/p/results/s",
          "outputs_prefix": "projects/p/outputs/s"
        }
        """
    )
    write_bmt_manifest_json(path, m)
    text = path.read_text(encoding="utf-8")
    assert "results_prefix" in text
    m2 = read_bmt_manifest(path)
    assert m2.results_path == "projects/p/results/s"
    assert m2.plugin_ref == "workspace:default"
