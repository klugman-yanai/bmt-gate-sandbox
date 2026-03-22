"""Tests for runtime summary artifact paths."""

import pytest

from gcp.image.runtime.artifacts import summary_path

pytestmark = pytest.mark.unit


def test_summary_artifact_path_format() -> None:
    """Summary path follows triggers/summaries/<wf_id>/<project>-<bmt_id>.json convention."""
    result = summary_path("wf-123", "sk", "4a5b6e82")
    assert result == "triggers/summaries/wf-123/sk-4a5b6e82.json"
