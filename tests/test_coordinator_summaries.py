"""Tests for coordinator summary artifact read/write."""

from gcp.image.coordinator import summary_artifact_path


def test_summary_artifact_path_format() -> None:
    """Summary path follows triggers/summaries/<wf_id>/<project>-<bmt_id>.json convention."""
    result = summary_artifact_path("wf-123", "sk", "4a5b6e82")
    assert result == "triggers/summaries/wf-123/sk-4a5b6e82.json"


def test_summary_artifact_path_strips_whitespace() -> None:
    result = summary_artifact_path(" wf-123 ", " sk ", " abc ")
    assert result == "triggers/summaries/wf-123/sk-abc.json"
