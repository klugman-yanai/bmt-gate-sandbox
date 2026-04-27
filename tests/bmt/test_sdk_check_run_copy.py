from __future__ import annotations

import pytest
from bmt_sdk import CheckRunCopy, merge_check_run_copy

pytestmark = pytest.mark.unit


def test_check_run_copy_serializes_to_score_extra_fragment() -> None:
    copy = CheckRunCopy(
        success_in_words="Custom success blurb",
        reason_text="Custom reason",
        metric_label="custom metric",
    )
    assert copy.as_extra_fragment() == {
        "check_run_copy": {
            "success_in_words": "Custom success blurb",
            "reason_text": "Custom reason",
            "metric_label": "custom metric",
        }
    }


def test_merge_check_run_copy_keeps_existing_extra_fields() -> None:
    out = merge_check_run_copy({"scoring_policy": {"primary_metric": "hits"}}, CheckRunCopy(reason_text="x"))
    assert out["scoring_policy"]["primary_metric"] == "hits"
    assert out["check_run_copy"]["reason_text"] == "x"
