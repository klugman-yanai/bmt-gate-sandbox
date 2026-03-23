"""Tests for runtime summary artifact paths."""

import pytest

from gcp.image.runtime.artifacts import summary_path
from tests.support.sentinels import FAKE_WORKFLOW_ID

pytestmark = pytest.mark.unit

_PROJECT = "sk"
_BMT_ID = "4a5b6e82"


def test_summary_artifact_path_format() -> None:
    """Summary path follows triggers/summaries/<wf_id>/<project>-<bmt_id>.json convention."""
    result = summary_path(FAKE_WORKFLOW_ID, _PROJECT, _BMT_ID)
    assert result == f"triggers/summaries/{FAKE_WORKFLOW_ID}/{_PROJECT}-{_BMT_ID}.json"
