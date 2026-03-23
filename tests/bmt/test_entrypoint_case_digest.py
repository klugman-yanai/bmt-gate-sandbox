"""Tests for case digest payload written with snapshot artifacts."""

from __future__ import annotations

import pytest

from gcp.image.runtime.entrypoint import _case_digest_payload
from gcp.image.runtime.models import LegSummary, ScorePayload

pytestmark = pytest.mark.unit


def test_case_digest_payload_includes_outcomes() -> None:
    summary = LegSummary(
        project="sk",
        bmt_slug="false_alarms",
        bmt_id="id",
        run_id="run1",
        status="fail",
        reason_code="runner_case_failures",
        plugin_ref="published:default:x",
        execution_mode_used="kardome_legacy_stdout",
        score=ScorePayload(
            aggregate_score=2.0,
            metrics={
                "case_count": 2,
                "case_outcomes": [
                    {"case_id": "a.wav", "status": "ok", "namuh_count": 1.0, "error": "", "log_name": "a.wav.log"},
                    {
                        "case_id": "b.wav",
                        "status": "failed",
                        "namuh_count": 0.0,
                        "error": "runner_exit_1",
                        "log_name": "",
                    },
                ],
            },
            extra={},
        ),
        verdict_summary={},
    )
    payload = _case_digest_payload(summary)
    assert payload["schema_version"] == 1
    assert payload["project"] == "sk"
    assert payload["bmt_slug"] == "false_alarms"
    assert payload["run_id"] == "run1"
    cases = payload["cases"]
    assert isinstance(cases, list)
    assert len(cases) == 2
