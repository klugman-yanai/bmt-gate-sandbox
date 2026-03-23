"""Unit tests for task-mode resilience when plugin execution raises."""
from __future__ import annotations

import pytest

from gcp.image.runtime.entrypoint import _leg_summary_from_execute_failure
from gcp.image.runtime.models import PlanLeg

pytestmark = pytest.mark.unit


def test_leg_summary_from_execute_failure_maps_exception() -> None:
    leg = PlanLeg(
        project="acme",
        bmt_slug="sk",
        bmt_id="b1",
        run_id="r1",
        manifest_path="projects/acme/bmts/sk/bmt.json",
        manifest_digest="d",
        plugin_ref="plugins/default",
        plugin_digest="pd",
        inputs_prefix="projects/acme/inputs/sk",
        results_prefix="projects/acme/results/sk",
        outputs_prefix="projects/acme/outputs/sk",
    )
    summary = _leg_summary_from_execute_failure(leg=leg, exc=RuntimeError("boom"))
    assert summary.status == "fail"
    assert summary.reason_code == "runner_failures"
    assert summary.execution_mode_used == "unknown"
    assert summary.score.extra.get("unavailable") is True
    assert summary.score.metrics.get("execute_exception_type") == "RuntimeError"
    assert "boom" in (summary.score.metrics.get("execute_exception_message") or "")
