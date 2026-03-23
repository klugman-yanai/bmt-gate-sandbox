"""Unit tests for task-mode resilience when plugin execution raises."""

from __future__ import annotations

import pytest

from gcp.image.config.value_types import as_results_path
from gcp.image.runtime.entrypoint import _leg_summary_from_execute_failure
from gcp.image.runtime.models import PlanLeg
from tests.support.sentinels import SYNTH_PROJECT

pytestmark = pytest.mark.unit

_BMT = "sk"


def test_leg_summary_from_execute_failure_maps_exception() -> None:
    leg = PlanLeg(
        project=SYNTH_PROJECT,
        bmt_slug=_BMT,
        bmt_id="b1",
        run_id="r1",
        manifest_path=f"projects/{SYNTH_PROJECT}/bmts/{_BMT}/bmt.json",
        manifest_digest="d",
        plugin_ref="plugins/default",
        plugin_digest="pd",
        inputs_prefix=f"projects/{SYNTH_PROJECT}/inputs/{_BMT}",
        results_path=as_results_path(f"projects/{SYNTH_PROJECT}/results/{_BMT}"),
        outputs_prefix=f"projects/{SYNTH_PROJECT}/outputs/{_BMT}",
    )
    summary = _leg_summary_from_execute_failure(leg=leg, exc=RuntimeError("boom"))
    assert summary.status == "fail"
    assert summary.reason_code == "runner_failures"
    assert summary.execution_mode_used == "unknown"
    assert summary.score.extra.get("unavailable") is True
    assert summary.score.metrics.get("execute_exception_type") == "RuntimeError"
    assert "boom" in (summary.score.metrics.get("execute_exception_message") or "")
