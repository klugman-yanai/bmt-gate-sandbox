"""Tests for safe log path resolution in runtime GitHub reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.config.bmt_domain_status import BmtLegStatus
from runtime.config.value_types import as_results_path
from runtime.github_reporting import (
    _resolved_logs_dir_under_stage,
    _write_log_dump_and_sign,
)
from runtime.models import ExecutionPlan, LegSummary, PlanLeg, ScorePayload, StageRuntimePaths

pytestmark = pytest.mark.unit


def test_resolved_logs_dir_rejects_path_outside_stage(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert _resolved_logs_dir_under_stage(stage, f"../{outside.name}") is None


def test_resolved_logs_dir_accepts_subdirectory(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    logs = stage / "runtime" / "logs"
    logs.mkdir(parents=True)
    resolved = _resolved_logs_dir_under_stage(stage, "runtime/logs")
    assert resolved == logs.resolve()


def _minimal_fail_plan() -> ExecutionPlan:
    return ExecutionPlan(
        workflow_run_id="wf-path-test",
        repository="owner/repo",
        head_sha="0" * 40,
        head_branch="main",
        head_event="pull_request",
        pr_number="1",
        status_context="BMT Gate",
        standard_task_count=1,
        heavy_task_count=0,
        legs=[
            PlanLeg(
                project="sk",
                bmt_slug="b1",
                bmt_id="b1-id",
                run_id="wf-path-test-b1",
                manifest_path="projects/sk/bmts/b1/bmt.json",
                manifest_digest="m",
                plugin_ref="p",
                plugin_digest="p",
                inputs_prefix="i",
                results_path=as_results_path("projects/sk/results/b1"),
                outputs_prefix="o",
            ),
        ],
    )


def _fail_summary(*, logs_uri: str) -> LegSummary:
    return LegSummary(
        project="sk",
        bmt_slug="b1",
        bmt_id="b1-id",
        run_id="r1",
        status=BmtLegStatus.FAIL.value,
        reason_code="runner_failures",
        plugin_ref="p",
        execution_mode_used="legacy",
        score=ScorePayload(aggregate_score=0.0),
        verdict_summary={},
        logs_uri=logs_uri,
    )


def test_write_log_dump_does_not_read_outside_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Legs pointing outside stage_root via .. must not contribute file contents."""
    stage = tmp_path / "stage"
    stage.mkdir()
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    (secret_dir / "leak.txt").write_text("SECRET_SHOULD_NOT_APPEAR", encoding="utf-8")

    runtime = StageRuntimePaths(stage_root=stage, workspace_root=tmp_path / "ws")
    plan = _minimal_fail_plan()
    summaries = [_fail_summary(logs_uri=f"../{secret_dir.name}")]

    monkeypatch.delenv("GCS_BUCKET", raising=False)
    assert _write_log_dump_and_sign(plan=plan, runtime=runtime, summaries=summaries) is None


def test_write_log_dump_includes_logs_under_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    log_dir = stage / "logs" / "b1"
    log_dir.mkdir(parents=True)
    (log_dir / "out.log").write_text("expected log line", encoding="utf-8")

    runtime = StageRuntimePaths(stage_root=stage, workspace_root=tmp_path / "ws")
    plan = _minimal_fail_plan()
    summaries = [_fail_summary(logs_uri="logs/b1")]

    monkeypatch.delenv("GCS_BUCKET", raising=False)
    assert _write_log_dump_and_sign(plan=plan, runtime=runtime, summaries=summaries) is None
    dump = stage / "log-dumps" / f"{plan.workflow_run_id}.txt"
    assert dump.is_file()
    text = dump.read_text(encoding="utf-8")
    assert "expected log line" in text
    assert "SECRET" not in text
