"""JSON Schema generation for Kardome batch results (operator tooling)."""

from __future__ import annotations

import pytest

from runtime.kardome_batch_results import KardomeBatchFile

pytestmark = pytest.mark.unit


def test_kardome_batch_file_model_json_schema() -> None:
    schema = KardomeBatchFile.model_json_schema()
    assert "properties" in schema
    assert "results" in schema["properties"]
