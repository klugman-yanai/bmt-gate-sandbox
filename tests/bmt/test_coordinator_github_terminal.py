"""Coordinator GitHub terminal status (finally + finalize-failure hooks)."""

from __future__ import annotations

import signal
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from backend.config.constants import (
    ENV_BMT_FINALIZE_HEAD_SHA,
    ENV_BMT_FINALIZE_REPOSITORY,
)
from backend.runtime.artifacts import write_plan, write_reporting_metadata
from backend.runtime.entrypoint import run_coordinator_mode, run_finalize_failure_mode
from backend.runtime.facade import RuntimeFacade, RuntimeMode
from backend.runtime.models import ExecutionPlan, ReportingMetadata, StageRuntimePaths

pytestmark = pytest.mark.unit


@pytest.fixture
def restore_sigterm_sigint() -> Iterator[None]:
    prev_term = signal.getsignal(signal.SIGTERM)
    prev_int = signal.getsignal(signal.SIGINT)
    yield None
    signal.signal(signal.SIGTERM, prev_term)
    signal.signal(signal.SIGINT, prev_int)


def _empty_plan(*, workflow_run_id: str = "wf-coord-terminal") -> ExecutionPlan:
    return ExecutionPlan(
        workflow_run_id=workflow_run_id,
        repository="owner/repo",
        head_sha="0" * 40,
        head_branch="main",
        head_event="push",
        pr_number="",
        legs=[],
        standard_task_count=0,
        heavy_task_count=0,
    )


def test_coordinator_finally_invokes_github_failure_when_publish_does_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)
    plan = _empty_plan()
    write_plan(stage_root=stage_root, plan=plan)
    write_reporting_metadata(
        stage_root=stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/1",
            check_run_id=9,
            started_at="2026-03-19T10:00:00Z",
            github_publish_complete=False,
        ),
    )
    hook: list[str] = []

    def _track_publish(**_kwargs: object) -> None:
        hook.append("publish")

    def _track_failure(**_kwargs: object) -> None:
        hook.append("failure")

    monkeypatch.setattr("backend.runtime.entrypoint.publish_final_results", _track_publish)
    monkeypatch.setattr("backend.runtime.entrypoint.publish_github_failure", _track_failure)
    monkeypatch.setattr("backend.runtime.entrypoint.cleanup_ephemeral_triggers", lambda **_k: None)

    exit_code = run_coordinator_mode(workflow_run_id=plan.workflow_run_id, stage_root=stage_root)
    assert exit_code == 0
    assert hook == ["publish", "publish", "failure"]


def test_coordinator_publish_crash_still_invokes_failure_publisher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If publish crashes, finally path must still close pending GitHub state via failure publisher."""
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)
    plan = _empty_plan(workflow_run_id="wf-publish-crash")
    write_plan(stage_root=stage_root, plan=plan)
    write_reporting_metadata(
        stage_root=stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/1",
            check_run_id=42,
            started_at="2026-03-19T10:00:00Z",
            github_publish_complete=False,
        ),
    )
    calls: list[str] = []

    def _raise_publish(**_kwargs: object) -> None:
        calls.append("publish")
        raise RuntimeError("injected publish crash")

    def _track_failure(**_kwargs: object) -> None:
        calls.append("failure")

    monkeypatch.setattr("backend.runtime.entrypoint.publish_final_results", _raise_publish)
    monkeypatch.setattr("backend.runtime.entrypoint.publish_github_failure", _track_failure)
    monkeypatch.setattr("backend.runtime.entrypoint.cleanup_ephemeral_triggers", lambda **_k: None)

    with pytest.raises(RuntimeError, match="injected publish crash"):
        run_coordinator_mode(workflow_run_id=plan.workflow_run_id, stage_root=stage_root)
    assert calls == ["publish", "publish", "failure"]


def test_runtime_mode_finalize_failure_string() -> None:
    assert RuntimeMode("finalize-failure") == RuntimeMode.FINALIZE_FAILURE


def test_coordinator_skips_recovery_when_first_publish_marks_github_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: no second publish_github_failure when reporting metadata shows publish complete."""
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)
    plan = _empty_plan(workflow_run_id="wf-complete")
    write_plan(stage_root=stage_root, plan=plan)
    write_reporting_metadata(
        stage_root=stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/1",
            check_run_id=9,
            started_at="2026-03-19T10:00:00Z",
            github_publish_complete=False,
        ),
    )
    publish_calls: list[str] = []
    failure_calls: list[object] = []

    def _publish_then_complete(*, plan: ExecutionPlan, summaries: object, runtime: StageRuntimePaths) -> None:
        publish_calls.append("publish")
        write_reporting_metadata(
            stage_root=runtime.stage_root,
            workflow_run_id=plan.workflow_run_id,
            metadata=ReportingMetadata(
                workflow_execution_url="https://example.test/workflows/1",
                check_run_id=9,
                started_at="2026-03-19T10:00:00Z",
                github_publish_complete=True,
            ),
        )

    monkeypatch.setattr("backend.runtime.entrypoint.publish_final_results", _publish_then_complete)

    def _track_failure(**_kwargs: object) -> None:
        failure_calls.append(True)

    monkeypatch.setattr("backend.runtime.entrypoint.publish_github_failure", _track_failure)
    monkeypatch.setattr("backend.runtime.entrypoint.cleanup_ephemeral_triggers", lambda **_k: None)

    assert run_coordinator_mode(workflow_run_id=plan.workflow_run_id, stage_root=stage_root) == 0
    assert publish_calls == ["publish"]
    assert failure_calls == []


def test_finalize_failure_mode_returns_zero_without_plan_and_without_finalize_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv(ENV_BMT_FINALIZE_REPOSITORY, raising=False)
    monkeypatch.delenv(ENV_BMT_FINALIZE_HEAD_SHA, raising=False)

    def _boom(**_kwargs: object) -> None:
        raise AssertionError("publish_github_failure must not run when plan is missing and env unset")

    monkeypatch.setattr("backend.runtime.entrypoint.publish_github_failure", _boom)
    assert run_finalize_failure_mode(workflow_run_id="missing-plan-id", stage_root=stage_root) == 0


def test_finalize_failure_mode_synthetic_plan_from_env_when_plan_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(ENV_BMT_FINALIZE_REPOSITORY, "acme/widget")
    monkeypatch.setenv(ENV_BMT_FINALIZE_HEAD_SHA, "a" * 40)
    captured: dict[str, object] = {}

    def _capture(*, plan: ExecutionPlan, **_kwargs: object) -> None:
        captured["plan"] = plan

    monkeypatch.setattr("backend.runtime.entrypoint.publish_github_failure", _capture)
    assert run_finalize_failure_mode(workflow_run_id="wf-no-plan", stage_root=stage_root) == 0
    plan = captured["plan"]
    assert isinstance(plan, ExecutionPlan)
    assert plan.workflow_run_id == "wf-no-plan"
    assert plan.repository == "acme/widget"
    assert plan.head_sha == "a" * 40
    assert plan.run_context == "pr"


def test_finalize_failure_mode_passes_reason_from_env_to_publish_github_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)
    plan = _empty_plan(workflow_run_id="wf-ff-env")
    write_plan(stage_root=stage_root, plan=plan)
    write_reporting_metadata(
        stage_root=stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/1",
            check_run_id=3,
            started_at="2026-03-19T10:00:00Z",
            github_publish_complete=False,
        ),
    )
    captured: dict[str, str] = {}

    def _capture_failure(*, reason: str, **_kwargs: object) -> None:
        captured["reason"] = reason

    monkeypatch.setattr("backend.runtime.entrypoint.publish_github_failure", _capture_failure)
    monkeypatch.setenv("BMT_FAILURE_REASON", "workflow_step_read_plan_failed")

    assert run_finalize_failure_mode(workflow_run_id=plan.workflow_run_id, stage_root=stage_root) == 0
    assert captured["reason"] == "workflow_step_read_plan_failed"


def test_finalize_failure_mode_uses_default_reason_when_env_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)
    plan = _empty_plan(workflow_run_id="wf-ff-default")
    write_plan(stage_root=stage_root, plan=plan)
    write_reporting_metadata(
        stage_root=stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/1",
            check_run_id=3,
            started_at="2026-03-19T10:00:00Z",
            github_publish_complete=False,
        ),
    )
    captured: dict[str, str] = {}

    def _capture_failure(*, reason: str, **_kwargs: object) -> None:
        captured["reason"] = reason

    monkeypatch.setattr("backend.runtime.entrypoint.publish_github_failure", _capture_failure)
    monkeypatch.delenv("BMT_FAILURE_REASON", raising=False)

    assert run_finalize_failure_mode(workflow_run_id=plan.workflow_run_id, stage_root=stage_root) == 0
    assert "BMT Google Workflow aborted" in captured["reason"]


@pytest.mark.usefixtures("restore_sigterm_sigint")
def test_runtime_facade_sigterm_handler_raises_system_exit_for_finally_blocks() -> None:
    RuntimeFacade().bootstrap_runtime()
    handler = cast(Callable[..., Any], signal.getsignal(signal.SIGTERM))
    with pytest.raises(SystemExit) as exc_info:
        handler(signal.SIGTERM, None)
    assert exc_info.value.code == 128 + signal.SIGTERM


@pytest.mark.usefixtures("restore_sigterm_sigint")
def test_runtime_facade_sigint_handler_raises_system_exit_for_finally_blocks() -> None:
    RuntimeFacade().bootstrap_runtime()
    handler = cast(Callable[..., Any], signal.getsignal(signal.SIGINT))
    with pytest.raises(SystemExit) as exc_info:
        handler(signal.SIGINT, None)
    assert exc_info.value.code == 128 + signal.SIGINT
