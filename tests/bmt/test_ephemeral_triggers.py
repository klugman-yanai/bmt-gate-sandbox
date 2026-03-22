"""Tests for triggers/ cleanup after coordinator."""

from __future__ import annotations

from pathlib import Path

from gcp.image.runtime.artifacts import (
    cleanup_ephemeral_triggers,
    reporting_metadata_path,
    write_reporting_metadata,
    write_summary,
)
from gcp.image.runtime.models import ExecutionPlan, LegSummary, ReportingMetadata, ScorePayload


def test_cleanup_ephemeral_triggers_removes_expected_paths(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    wid = "run-xyz"
    plan = ExecutionPlan(
        workflow_run_id=wid,
        repository="o/r",
        head_sha="a" * 40,
        standard_task_count=0,
        heavy_task_count=0,
        legs=[],
    )
    (stage / "triggers" / "plans").mkdir(parents=True)
    (stage / "triggers" / "plans" / f"{wid}.json").write_text("{}", encoding="utf-8")
    (stage / "triggers" / "reporting").mkdir(parents=True)
    write_reporting_metadata(
        stage_root=stage,
        workflow_run_id=wid,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.com/wf",
            check_run_id=1,
            started_at="2026-01-01T00:00:00Z",
        ),
    )
    prog = stage / "triggers" / "progress" / wid
    prog.mkdir(parents=True)
    (prog / "x.json").write_text("{}", encoding="utf-8")
    summ = stage / "triggers" / "summaries" / wid
    summ.mkdir(parents=True)
    write_summary(
        stage_root=stage,
        workflow_run_id=wid,
        summary=LegSummary(
            project="p",
            bmt_slug="s",
            bmt_id="id",
            run_id="r",
            status="pass",
            reason_code="ok",
            plugin_ref="ref",
            execution_mode_used="m",
            score=ScorePayload(aggregate_score=1.0),
            verdict_summary={},
        ),
    )

    cleanup_ephemeral_triggers(stage_root=stage, plan=plan)

    assert not (stage / "triggers" / "plans" / f"{wid}.json").exists()
    assert not (stage / reporting_metadata_path(wid)).exists()
    assert not (stage / "triggers" / "progress" / wid).exists()
    assert not (stage / "triggers" / "summaries" / wid).exists()
