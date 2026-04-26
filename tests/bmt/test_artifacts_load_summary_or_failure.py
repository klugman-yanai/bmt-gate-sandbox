"""Regression tests for coordinator summary loading (missing file → synthetic failure)."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.artifacts import load_summary_or_failure
from runtime.config.bmt_domain_status import BmtLegStatus
from runtime.config.value_types import as_results_path
from runtime.models import PlanLeg

pytestmark = pytest.mark.unit


def _leg() -> PlanLeg:
    return PlanLeg(
        project="sk",
        bmt_slug="false_rejects",
        bmt_id="fr-id",
        run_id="wf-x-fr",
        manifest_path="projects/sk/bmts/false_rejects/bmt.json",
        manifest_digest="m",
        plugin_ref="projects/sk/plugins/default/sha256-demo",
        plugin_digest="p",
        inputs_prefix="projects/sk/inputs/false_rejects",
        results_path=as_results_path("projects/sk/results/false_rejects"),
        outputs_prefix="projects/sk/outputs/false_rejects",
    )


def test_load_summary_or_failure_returns_synthetic_failure_when_summary_missing(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    leg = _leg()
    summary = load_summary_or_failure(
        stage_root=stage,
        workflow_run_id="wf-x",
        leg=leg,
    )
    assert summary.status == BmtLegStatus.FAIL.value
    assert summary.reason_code == "summary_missing"
    assert summary.score.extra.get("unavailable") is True
    assert summary.project == leg.project
    assert summary.bmt_slug == leg.bmt_slug
