from __future__ import annotations

from pathlib import Path

import pytest
from github import GithubException

from gcp.image.config.constants import STATUS_CONTEXT
from gcp.image.config.value_types import as_results_path
from gcp.image.github.presentation import CheckFinalView, CheckProgressView, FinalCommentView, ProgressBmtRow
from gcp.image.runtime.artifacts import (
    load_optional_reporting_metadata,
    write_progress,
    write_reporting_metadata,
    write_summary,
)
from gcp.image.runtime.github_reporting import (
    _elapsed_seconds,
    _estimate_eta_sec_parallel,
    ensure_reporting_metadata_for_plan,
    publish_final_results,
    publish_github_failure,
    publish_progress,
)
from gcp.image.runtime.models import (
    ExecutionPlan,
    LegSummary,
    PlanLeg,
    ProgressRecord,
    ReportingMetadata,
    ScorePayload,
    StageRuntimePaths,
)
from tests.support.captures import CallRecorder
from tests.support.sentinels import FAKE_BUCKET, FAKE_REPO, FAKE_SHA_ALT, FAKE_WORKFLOW_ID

pytestmark = pytest.mark.integration

_PROJECT = "sk"
_BMT_FR = "false_rejects"
_BMT_FA = "false_alarms"


def _plan(*, head_event: str = "pull_request", pr_number: str = "17") -> ExecutionPlan:
    return ExecutionPlan(
        workflow_run_id=FAKE_WORKFLOW_ID,
        repository=FAKE_REPO,
        head_sha=FAKE_SHA_ALT,
        head_branch="main",
        head_event=head_event,
        pr_number=pr_number,
        status_context=STATUS_CONTEXT,
        standard_task_count=2,
        heavy_task_count=0,
        legs=[
            PlanLeg(
                project=_PROJECT,
                bmt_slug=_BMT_FR,
                bmt_id="fr-id",
                run_id=f"{FAKE_WORKFLOW_ID}-{_BMT_FR}",
                manifest_path=f"projects/{_PROJECT}/bmts/{_BMT_FR}/bmt.json",
                manifest_digest="manifest-fr",
                plugin_ref=f"projects/{_PROJECT}/plugins/default/sha256-demo",
                plugin_digest="plugin-fr",
                inputs_prefix=f"projects/{_PROJECT}/inputs/{_BMT_FR}",
                results_path=as_results_path(f"projects/{_PROJECT}/results/{_BMT_FR}"),
                outputs_prefix=f"projects/{_PROJECT}/outputs/{_BMT_FR}",
            ),
            PlanLeg(
                project=_PROJECT,
                bmt_slug=_BMT_FA,
                bmt_id="fa-id",
                run_id=f"{FAKE_WORKFLOW_ID}-{_BMT_FA}",
                manifest_path=f"projects/{_PROJECT}/bmts/{_BMT_FA}/bmt.json",
                manifest_digest="manifest-fa",
                plugin_ref=f"projects/{_PROJECT}/plugins/default/sha256-demo",
                plugin_digest="plugin-fa",
                inputs_prefix=f"projects/{_PROJECT}/inputs/{_BMT_FA}",
                results_path=as_results_path(f"projects/{_PROJECT}/results/{_BMT_FA}"),
                outputs_prefix=f"projects/{_PROJECT}/outputs/{_BMT_FA}",
            ),
        ],
    )


def _summary(
    *,
    bmt_slug: str,
    run_id: str,
    status: str,
    reason_code: str,
    aggregate_score: float,
    logs_uri: str = "",
    duration_sec: int | None = None,
) -> LegSummary:
    return LegSummary(
        project=_PROJECT,
        bmt_slug=bmt_slug,
        bmt_id=f"{bmt_slug}-id",
        run_id=run_id,
        status=status,
        reason_code=reason_code,
        plugin_ref=f"projects/{_PROJECT}/plugins/default/sha256-demo",
        execution_mode_used="adaptive_batch_then_legacy",
        score=ScorePayload(aggregate_score=aggregate_score),
        verdict_summary={},
        logs_uri=logs_uri,
        duration_sec=duration_sec,
    )


def test_publish_progress_updates_the_existing_check_run(tmp_path: Path, monkeypatch) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/123",
            check_run_id=42,
            started_at="2026-03-19T10:00:00Z",
        ),
    )
    write_summary(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        summary=_summary(
            bmt_slug="false_rejects",
            run_id=f"{FAKE_WORKFLOW_ID}-{_BMT_FR}",
            status="pass",
            reason_code="score_gte_last",
            aggregate_score=56.8,
            duration_sec=63,
        ),
    )
    write_progress(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        progress=ProgressRecord(
            project="sk",
            bmt_slug="false_alarms",
            status="running",
            started_at="2026-03-19T10:00:00Z",
            updated_at="2026-03-19T10:01:00Z",
        ),
    )

    cap = CallRecorder()

    class FakeReporter:
        def __init__(self, *, repository: str, sha: str, token: str, status_context: str) -> None:
            cap.init = (repository, sha, token, status_context)

        def update_progress_check_run(self, *, check_run_id: int, view: CheckProgressView, details_url: str) -> None:
            cap.check_run_id = check_run_id
            cap.progress_view = view
            cap.details_url = details_url

    def _resolve_token(repository: str) -> str:
        cap.resolved_repository = repository
        return "app-token"

    monkeypatch.setattr("gcp.image.runtime.github_reporting.resolve_github_app_token", _resolve_token)
    monkeypatch.setattr("gcp.image.runtime.github_reporting.GitHubReporter", FakeReporter)

    publish_progress(plan=plan, runtime=runtime)

    assert cap.check_run_id == 42
    assert cap.details_url == "https://example.test/workflows/123"
    assert cap.resolved_repository == FAKE_REPO
    view = cap.progress_view
    assert view is not None
    assert view.completed_count == 1
    assert view.total_count == 2
    rows = {(row.project, row.bmt): row for row in view.bmts}
    assert rows[("sk", "false_rejects")].status == "pass"
    assert rows[("sk", "false_alarms")].status == "running"


def test_publish_final_results_posts_status_and_failure_comment_with_log_dump(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/123",
            check_run_id=91,
            started_at="2026-03-19T10:00:00Z",
        ),
    )

    failed_logs_root = (
        runtime.stage_root
        / "projects"
        / _PROJECT
        / "results"
        / _BMT_FR
        / "snapshots"
        / f"{FAKE_WORKFLOW_ID}-{_BMT_FR}"
        / "logs"
    )
    failed_logs_root.mkdir(parents=True, exist_ok=True)
    (failed_logs_root / "runner.log").write_text("runner failed hard", encoding="utf-8")

    summaries = [
        _summary(
            bmt_slug="false_rejects",
            run_id=f"{FAKE_WORKFLOW_ID}-{_BMT_FR}",
            status="fail",
            reason_code="score_below_last",
            aggregate_score=41.25,
            logs_uri=f"projects/{_PROJECT}/results/{_BMT_FR}/snapshots/{FAKE_WORKFLOW_ID}-{_BMT_FR}/logs",
            duration_sec=65,
        ),
        _summary(
            bmt_slug="false_alarms",
            run_id=f"{FAKE_WORKFLOW_ID}-{_BMT_FA}",
            status="pass",
            reason_code="score_gte_last",
            aggregate_score=56.8,
            duration_sec=59,
        ),
    ]

    cap = CallRecorder()

    class FakeReporter:
        def __init__(self, *, repository: str, sha: str, token: str, status_context: str) -> None:
            cap.init = (repository, sha, token, status_context)

        def finalize_check_run(
            self, *, check_run_id: int | None, view: CheckFinalView, details_url: str
        ) -> tuple[int | None, bool]:
            cap.finalize_check_run_id = check_run_id
            cap.finalize_view = view
            cap.finalize_details_url = details_url
            return check_run_id, True

        def post_final_status(self, *, state: str, description: str, details_url: str | None = None) -> bool:
            cap.status_state = state
            cap.status_description = description
            cap.status_details_url = details_url
            return True

        def upsert_final_pr_comment(self, *, pr_number: int, view: FinalCommentView) -> None:
            cap.comment_pr_number = pr_number
            cap.comment_view = view

    def _fake_signed_url(*, bucket_name: str, blob_name: str) -> str:
        _ = bucket_name
        return f"https://example.test/{blob_name}"

    def _resolve_token(repository: str) -> str:
        cap.resolved_repository = repository
        return "app-token"

    monkeypatch.setattr("gcp.image.runtime.github_reporting.resolve_github_app_token", _resolve_token)
    monkeypatch.setattr("gcp.image.runtime.github_reporting.GitHubReporter", FakeReporter)
    monkeypatch.setattr("gcp.image.runtime.github_reporting._generate_signed_url", _fake_signed_url)
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)

    publish_final_results(plan=plan, summaries=summaries, runtime=runtime)

    log_dump_path = runtime.stage_root / "log-dumps" / f"{FAKE_WORKFLOW_ID}.txt"
    assert log_dump_path.is_file()
    assert "runner failed hard" in log_dump_path.read_text(encoding="utf-8")

    assert cap.status_state == "failure"
    assert cap.status_description == "1/2 BMTs failed."
    assert cap.status_details_url == "https://example.test/workflows/123"
    assert cap.resolved_repository == FAKE_REPO

    assert cap.finalize_check_run_id == 91
    assert cap.finalize_details_url == "https://example.test/workflows/123"
    assert cap.finalize_view is not None
    assert cap.finalize_view.links.log_dump_url == f"https://example.test/log-dumps/{FAKE_WORKFLOW_ID}.txt"

    assert cap.comment_pr_number == 17
    assert cap.comment_view is not None
    assert cap.comment_view.failed_bmts == [("false_rejects", "score dropped below baseline")]
    assert cap.comment_view.links.log_dump_url == f"https://example.test/log-dumps/{FAKE_WORKFLOW_ID}.txt"

    meta_after = load_optional_reporting_metadata(stage_root=runtime.stage_root, workflow_run_id=plan.workflow_run_id)
    assert meta_after is not None
    assert meta_after.github_publish_complete is True


def test_publish_final_results_still_posts_status_when_check_and_comment_fail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/123",
            check_run_id=12,
            started_at="2026-03-19T10:00:00Z",
        ),
    )
    summaries = [
        _summary(
            bmt_slug="false_rejects",
            run_id=f"{FAKE_WORKFLOW_ID}-{_BMT_FR}",
            status="fail",
            reason_code="score_below_last",
            aggregate_score=41.25,
        )
    ]

    cap = CallRecorder()

    class FakeReporter:
        def __init__(self, *, repository: str, sha: str, token: str, status_context: str) -> None:
            cap.init = (repository, sha, token, status_context)

        def finalize_check_run(self, *, check_run_id: int | None, view, details_url: str):
            raise GithubException(500, None, None, "check update failed")

        def post_final_status(self, *, state: str, description: str, details_url: str | None = None) -> bool:
            cap.status_state = state
            cap.status_description = description
            cap.status_details_url = details_url
            return True

        def upsert_final_pr_comment(self, *, pr_number: int, view) -> None:
            raise GithubException(500, None, None, "comment update failed")

    def _resolve_token(repository: str) -> str:
        cap.resolved_repository = repository
        return "app-token"

    monkeypatch.setattr("gcp.image.runtime.github_reporting.resolve_github_app_token", _resolve_token)
    monkeypatch.setattr("gcp.image.runtime.github_reporting.GitHubReporter", FakeReporter)
    monkeypatch.setattr("gcp.image.runtime.github_reporting._write_log_dump_and_sign", lambda **_kwargs: None)

    publish_final_results(plan=plan, summaries=summaries, runtime=runtime)

    assert cap.status_state == "failure"
    assert cap.status_description == "1/1 BMTs failed."
    assert cap.status_details_url == "https://example.test/workflows/123"
    assert cap.resolved_repository == FAKE_REPO

    meta_after = load_optional_reporting_metadata(stage_root=runtime.stage_root, workflow_run_id=plan.workflow_run_id)
    assert meta_after is not None
    assert meta_after.github_publish_complete is False


def test_publish_github_failure_skips_when_github_publish_complete(tmp_path: Path, monkeypatch) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/123",
            check_run_id=1,
            started_at="2026-03-19T10:00:00Z",
            github_publish_complete=True,
        ),
    )
    cap = CallRecorder()

    def _fail_if_called(*_a: object, **_k: object) -> None:
        cap.called = True

    monkeypatch.setattr("gcp.image.runtime.github_reporting.publish_final_results", _fail_if_called)
    publish_github_failure(plan=plan, runtime=runtime, reason="should not run")
    assert not getattr(cap, "called", False)


def test_publish_github_failure_skips_without_check_run_id(tmp_path: Path, monkeypatch) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/123",
            check_run_id=None,
            started_at="2026-03-19T10:00:00Z",
        ),
    )
    cap = CallRecorder()

    def _fail_if_called(*_a: object, **_k: object) -> None:
        cap.called = True

    monkeypatch.setattr("gcp.image.runtime.github_reporting.publish_final_results", _fail_if_called)
    publish_github_failure(plan=plan, runtime=runtime, reason="noop")
    assert not getattr(cap, "called", False)


def test_publish_github_failure_syncs_metadata_when_remote_check_completed(tmp_path: Path, monkeypatch) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/123",
            check_run_id=77,
            started_at="2026-03-19T10:00:00Z",
            github_publish_complete=False,
        ),
    )
    monkeypatch.setattr(
        "gcp.image.runtime.github_reporting.github_checks.get_check_run_status",
        lambda *_a, **_k: "completed",
    )
    monkeypatch.setattr("gcp.image.runtime.github_reporting.resolve_github_app_token", lambda _r: "tok")

    publish_github_failure(plan=plan, runtime=runtime, reason="irrelevant")

    meta_after = load_optional_reporting_metadata(stage_root=runtime.stage_root, workflow_run_id=plan.workflow_run_id)
    assert meta_after is not None
    assert meta_after.github_publish_complete is True


def test_ensure_reporting_metadata_for_plan_skips_when_already_complete(tmp_path: Path, monkeypatch) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/123",
            check_run_id=99,
            started_at="2026-03-19T10:00:00Z",
        ),
    )
    cap = CallRecorder()
    cap.constructed = False
    cap.create_called = False

    class FakeReporter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            cap.constructed = True

        def create_started_check_run(self, view, *, details_url: str, external_id: str | None = None) -> int:
            cap.create_called = True
            return 1

    monkeypatch.setenv("BMT_WORKFLOW_EXECUTION_URL", "https://env.example/wf")
    monkeypatch.setattr("gcp.image.runtime.github_reporting.GitHubReporter", FakeReporter)
    monkeypatch.setattr("gcp.image.runtime.github_reporting.resolve_github_app_token", lambda _r: "tok")

    ensure_reporting_metadata_for_plan(plan=plan, runtime=runtime)

    assert not cap.create_called


def test_ensure_reporting_metadata_backfills_started_at_when_complete_but_missing(tmp_path: Path, monkeypatch) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/123",
            check_run_id=99,
            started_at="",
        ),
    )
    cap = CallRecorder()
    cap.create_called = False

    class FakeReporter:
        def create_started_check_run(self, *args: object, **kwargs: object) -> int:
            cap.create_called = True
            return 1

    monkeypatch.setattr("gcp.image.runtime.github_reporting.GitHubReporter", FakeReporter)
    monkeypatch.setattr("gcp.image.runtime.github_reporting.resolve_github_app_token", lambda _r: "tok")

    ensure_reporting_metadata_for_plan(plan=plan, runtime=runtime)

    assert not cap.create_called
    path = runtime.stage_root / "triggers" / "reporting" / f"{FAKE_WORKFLOW_ID}.json"
    meta = ReportingMetadata.model_validate_json(path.read_text(encoding="utf-8"))
    assert meta.started_at


def test_parallel_eta_maxes_only_in_flight_remaining_not_completed_duration(tmp_path: Path, monkeypatch) -> None:
    """Completed leg durations must not appear inside ``max(...)`` with in-flight estimates."""
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True)
    plan = _plan()

    def _hist(*, stage_root: Path, leg: PlanLeg) -> int | None:
        if leg.bmt_slug == "false_alarms":
            return 100
        return None

    monkeypatch.setattr(
        "gcp.image.runtime.github_reporting.load_observed_duration_sec_from_latest_snapshot",
        _hist,
    )
    rows = [
        ProgressBmtRow(
            project="sk",
            bmt="false_rejects",
            status="pass",
            duration_sec=300,
            has_completed_summary=True,
        ),
        ProgressBmtRow(
            project="sk",
            bmt="false_alarms",
            status="running",
            duration_sec=None,
            has_completed_summary=False,
        ),
    ]
    # In-flight est=100 from snapshot; elapsed 150 -> remaining 0 (old code gave max(300,100)-150=150).
    assert _estimate_eta_sec_parallel(plan=plan, runtime=runtime, rows=rows, elapsed_sec=150) == 0


def test_elapsed_seconds_uses_progress_when_reporting_started_at_missing(tmp_path: Path, monkeypatch) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True)
    wid = FAKE_WORKFLOW_ID
    prog = tmp_path / "stage" / "triggers" / "progress" / wid
    prog.mkdir(parents=True)
    (prog / "sk-false_rejects.json").write_text(
        ProgressRecord(
            project="sk",
            bmt_slug="false_rejects",
            status="running",
            started_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ).model_dump_json(),
        encoding="utf-8",
    )
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=wid,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/wf",
            check_run_id=1,
            started_at="",
        ),
    )
    import whenever

    fixed_now = whenever.Instant.parse_iso("2020-01-01T01:00:00Z")
    monkeypatch.setattr("gcp.image.runtime.github_reporting._instant_now", lambda: fixed_now)
    assert _elapsed_seconds(runtime=runtime, workflow_run_id=wid) == 3600


def test_ensure_reporting_metadata_for_plan_creates_check_and_writes_file(tmp_path: Path, monkeypatch) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    monkeypatch.setenv("BMT_WORKFLOW_EXECUTION_URL", "https://console.example.com/workflows/exec")

    cap = CallRecorder()

    class FakeReporter:
        def __init__(self, *, repository: str, sha: str, token: str, status_context: str) -> None:
            cap.init = (repository, sha, token, status_context)

        def create_started_check_run(
            self, view, *, details_url: str, external_id: str | None = None, pending_legs=None
        ) -> int:
            cap.create_details_url = details_url
            cap.create_external_id = external_id
            cap.pending_legs = pending_legs
            return 55

        def upsert_started_pr_comment(self, *, pr_number: int, view: object) -> None:
            cap.started_pr_number = pr_number

    monkeypatch.setattr("gcp.image.runtime.github_reporting.resolve_github_app_token", lambda _r: "app-token")
    monkeypatch.setattr("gcp.image.runtime.github_reporting.GitHubReporter", FakeReporter)

    ensure_reporting_metadata_for_plan(plan=plan, runtime=runtime)

    assert cap.create_details_url == "https://console.example.com/workflows/exec"
    assert cap.create_external_id == FAKE_WORKFLOW_ID
    assert cap.pending_legs == [("sk", "false_rejects"), ("sk", "false_alarms")]
    assert cap.started_pr_number == 17
    path = runtime.stage_root / "triggers" / "reporting" / f"{FAKE_WORKFLOW_ID}.json"
    assert path.is_file()
    meta = ReportingMetadata.model_validate_json(path.read_text(encoding="utf-8"))
    assert meta.check_run_id == 55
    assert meta.workflow_execution_url == "https://console.example.com/workflows/exec"
    assert meta.started_at


def test_ensure_reporting_metadata_merges_url_when_check_id_exists_without_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="",
            check_run_id=77,
            started_at="2026-03-19T10:00:00Z",
        ),
    )
    cap = CallRecorder()
    cap.create_called = False

    class FakeReporter:
        def create_started_check_run(self, *args: object, **kwargs: object) -> int:
            cap.create_called = True
            return 1

    monkeypatch.setenv("BMT_WORKFLOW_EXECUTION_URL", "https://env.example/wf")
    monkeypatch.setattr("gcp.image.runtime.github_reporting.GitHubReporter", FakeReporter)
    monkeypatch.setattr("gcp.image.runtime.github_reporting.resolve_github_app_token", lambda _r: "tok")

    ensure_reporting_metadata_for_plan(plan=plan, runtime=runtime)

    assert not cap.create_called
    path = runtime.stage_root / "triggers" / "reporting" / f"{FAKE_WORKFLOW_ID}.json"
    meta = ReportingMetadata.model_validate_json(path.read_text(encoding="utf-8"))
    assert meta.check_run_id == 77
    assert meta.workflow_execution_url == "https://env.example/wf"


def test_publish_final_results_pr_comment_includes_case_crash_count(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """When reason_code is runner_case_failures, the PR comment detail includes case crash count."""
    runtime = StageRuntimePaths(stage_root=tmp_path / "stage", workspace_root=tmp_path / "workspace")
    runtime.stage_root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/123",
            check_run_id=91,
            started_at="2026-03-19T10:00:00Z",
        ),
    )

    summaries = [
        LegSummary(
            project="sk",
            bmt_slug="false_rejects",
            bmt_id="fr-id",
            run_id=f"{FAKE_WORKFLOW_ID}-{_BMT_FR}",
            status="fail",
            reason_code="runner_case_failures",
            plugin_ref="projects/sk/plugins/default/sha256-demo",
            execution_mode_used="kardome_legacy_stdout",
            score=ScorePayload(
                aggregate_score=87.5,
                metrics={"case_count": 24, "cases_ok": 22, "cases_failed": 2},
            ),
            verdict_summary={},
            duration_sec=65,
        ),
    ]

    cap = CallRecorder()

    class FakeReporter:
        def __init__(self, *, repository: str, sha: str, token: str, status_context: str) -> None:
            pass

        def finalize_check_run(self, *, check_run_id, view, details_url):
            return check_run_id, True

        def post_final_status(self, *, state, description, details_url=None):
            return True

        def upsert_final_pr_comment(self, *, pr_number: int, view: FinalCommentView) -> None:
            cap.comment_view = view

    monkeypatch.setattr("gcp.image.runtime.github_reporting.resolve_github_app_token", lambda _r: "app-token")
    monkeypatch.setattr("gcp.image.runtime.github_reporting.GitHubReporter", FakeReporter)
    monkeypatch.setattr("gcp.image.runtime.github_reporting._write_log_dump_and_sign", lambda **_kwargs: None)

    publish_final_results(plan=plan, summaries=summaries, runtime=runtime)

    assert cap.comment_view is not None
    assert len(cap.comment_view.failed_bmts) == 1
    bmt_name, detail = cap.comment_view.failed_bmts[0]
    assert bmt_name == "false_rejects"
    assert "runner crashed on one or more test files" in detail
    assert "(2 of 24 cases crashed)" in detail
