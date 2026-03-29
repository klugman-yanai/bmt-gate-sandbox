from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, cast

import pytest
from bmtgate.clients.cloud_run import CloudRunJobsApiError
from bmtgate.clients.workflows import WorkflowsApiError
from bmtgate.handoff.dispatch import (
    WorkflowDispatchInvokePayload,
    WorkflowDispatchManager,
)

from tests.support.sentinels import (
    FAKE_BUCKET,
    FAKE_CONTROL_JOB,
    FAKE_GCP_PROJECT,
    FAKE_REGION,
    FAKE_REPO,
    FAKE_SHA_ALT,
    FAKE_SHA_MISMATCH,
)

pytestmark = pytest.mark.unit


class WorkflowExecutionStubResponse(TypedDict):
    name: str
    state: str


@dataclass
class _WorkflowDispatchSpy:
    """Records arguments passed to the stubbed ``start_execution`` call."""

    project: str | None = None
    region: str | None = None
    workflow_name: str | None = None
    argument: WorkflowDispatchInvokePayload | None = None


def _read_outputs(path: Path) -> dict[str, str]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return dict(line.split("=", 1) for line in lines)


def test_invoke_workflow_starts_execution_and_writes_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCP_PROJECT", FAKE_GCP_PROJECT)
    monkeypatch.setenv("CLOUD_RUN_REGION", FAKE_REGION)
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("HEAD_SHA", FAKE_SHA_ALT)
    monkeypatch.setenv("HEAD_BRANCH", "main")
    monkeypatch.setenv("HEAD_EVENT", "push")
    monkeypatch.setenv("RUN_CONTEXT", "ci")
    monkeypatch.setenv("FILTERED_MATRIX_JSON", json.dumps({"include": [{"project": "sk"}, {"project": "sk"}]}))

    spy = _WorkflowDispatchSpy()

    def _fake_start_execution(
        *, project: str, region: str, workflow_name: str, argument: WorkflowDispatchInvokePayload
    ) -> WorkflowExecutionStubResponse:
        spy.project = project
        spy.region = region
        spy.workflow_name = workflow_name
        spy.argument = argument
        return {
            "name": f"projects/demo/locations/{FAKE_REGION}/workflows/bmt-workflow/executions/abc",
            "state": "ACTIVE",
        }

    monkeypatch.setattr("bmtgate.handoff.dispatch.start_execution", _fake_start_execution)

    WorkflowDispatchManager.from_env().invoke()

    outputs = _read_outputs(github_output)
    assert outputs["dispatch_confirmed"] == "true"
    assert outputs["workflow_execution_state"] == "ACTIVE"
    assert (
        outputs["workflow_execution_url"] == "https://console.cloud.google.com/workflows/workflow/"
        f"{FAKE_REGION}/bmt-workflow/execution/abc?project={FAKE_GCP_PROJECT}"
    )
    assert json.loads(outputs["accepted_projects"]) == ["sk"]
    assert spy.project == FAKE_GCP_PROJECT
    assert spy.region == FAKE_REGION
    assert spy.workflow_name == "bmt-workflow"
    assert spy.argument is not None
    assert spy.argument["bucket"] == FAKE_BUCKET
    assert spy.argument["workflow_run_id"] == "12345"
    assert spy.argument["accepted_projects_json"] == '["sk"]'
    assert spy.argument["github_handoff_run_url"] == f"https://github.com/{FAKE_REPO}/actions/runs/12345"


def test_invoke_workflow_records_pr_active_execution(tmp_path: Path, monkeypatch) -> None:
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCP_PROJECT", FAKE_GCP_PROJECT)
    monkeypatch.setenv("CLOUD_RUN_REGION", FAKE_REGION)
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GITHUB_RUN_ID", "54321")
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("HEAD_SHA", FAKE_SHA_ALT)
    monkeypatch.setenv("HEAD_BRANCH", "ci/check-bmt-gate")
    monkeypatch.setenv("HEAD_EVENT", "pull_request")
    monkeypatch.setenv("PR_NUMBER", "79")
    monkeypatch.setenv("RUN_CONTEXT", "pr")
    monkeypatch.setenv("FILTERED_MATRIX_JSON", json.dumps({"include": [{"project": "sk"}]}))

    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.start_execution",
        lambda **_: {
            "name": "projects/demo/locations/europe-west4/workflows/bmt-workflow/executions/ex-123",
            "state": "ACTIVE",
        },
    )

    seen: dict[str, object] = {}

    def _fake_upload_json(uri: str, payload: dict[str, object]) -> None:
        seen["uri"] = uri
        seen["payload"] = payload

    monkeypatch.setattr("bmtgate.handoff.dispatch.upload_json", _fake_upload_json)

    WorkflowDispatchManager.from_env().invoke()

    assert seen["uri"] == f"gs://{FAKE_BUCKET}/triggers/reporting/pr-active/79.json"
    raw_payload = seen["payload"]
    assert isinstance(raw_payload, dict)
    payload = cast(dict[str, Any], raw_payload)
    assert payload["repository"] == FAKE_REPO
    assert payload["pr_number"] == "79"
    assert str(payload["workflow_execution_name"]).endswith("/executions/ex-123")
    assert payload["workflow_run_id"] == "54321"
    assert "console.cloud.google.com" in str(payload.get("workflow_execution_url", ""))
    assert payload.get("github_handoff_run_url") == f"https://github.com/{FAKE_REPO}/actions/runs/54321"


def test_cancel_pr_execution_requests_cancel_and_clears_index(tmp_path: Path, monkeypatch) -> None:
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GCP_PROJECT", FAKE_GCP_PROJECT)
    monkeypatch.setenv("CLOUD_RUN_REGION", FAKE_REGION)
    monkeypatch.setenv("BMT_CONTROL_JOB", FAKE_CONTROL_JOB)
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("PR_NUMBER", "79")
    monkeypatch.setenv("HEAD_SHA", FAKE_SHA_ALT)

    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.download_json",
        lambda _: (
            {
                "repository": FAKE_REPO,
                "pr_number": "79",
                "head_sha": FAKE_SHA_ALT,
                "workflow_execution_name": "projects/p/locations/r/workflows/w/executions/ex-123",
                "workflow_run_id": "111",
            },
            None,
        ),
    )
    seen: dict[str, str] = {}
    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.cancel_execution",
        lambda *, execution_name: seen.setdefault("execution_name", execution_name),
    )
    monkeypatch.setattr("bmtgate.handoff.dispatch.delete_object", lambda uri: seen.setdefault("deleted_uri", uri))

    run_calls: list[dict] = []

    def _fake_run_job(**kwargs):
        run_calls.append(kwargs)
        return {"done": True}

    monkeypatch.setattr("bmtgate.handoff.dispatch.run_job", _fake_run_job)

    WorkflowDispatchManager.from_env().cancel_pr_execution()

    outputs = _read_outputs(github_output)
    assert outputs["cancel_requested"] == "true"
    assert outputs["cancel_reason"] == "cancel_requested"
    assert outputs["cancelled_execution_name"] == "projects/p/locations/r/workflows/w/executions/ex-123"
    assert seen["deleted_uri"] == f"gs://{FAKE_BUCKET}/triggers/reporting/pr-active/79.json"
    assert outputs["finalize_requested"] == "true"
    assert outputs["finalize_outcome"] == "success"
    assert len(run_calls) == 1
    assert run_calls[0]["env_vars"]["BMT_MODE"] == "finalize-failure"
    assert run_calls[0]["env_vars"]["BMT_WORKFLOW_RUN_ID"] == "111"
    assert "PR closed" in run_calls[0]["env_vars"]["BMT_FAILURE_REASON"]
    assert run_calls[0]["env_vars"]["BMT_FINALIZE_REPOSITORY"] == FAKE_REPO
    assert run_calls[0]["env_vars"]["BMT_FINALIZE_HEAD_SHA"] == FAKE_SHA_ALT
    assert run_calls[0]["env_vars"]["BMT_FINALIZE_PR_NUMBER"] == "79"
    assert run_calls[0]["env_vars"]["BMT_GCS_BUCKET_NAME"] == FAKE_BUCKET


def test_cancel_pr_execution_no_index_is_safe(tmp_path: Path, monkeypatch) -> None:
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("PR_NUMBER", "79")
    monkeypatch.setattr("bmtgate.handoff.dispatch.download_json", lambda _: (None, "not_found"))

    WorkflowDispatchManager.from_env().cancel_pr_execution()
    outputs = _read_outputs(github_output)
    assert outputs["cancel_requested"] == "false"
    assert outputs["cancel_reason"].startswith("no_active_execution:")
    assert outputs["finalize_requested"] == "false"
    assert outputs["finalize_outcome"] == "skipped_no_active_execution"


def test_cancel_pr_execution_skips_finalize_without_control_job(tmp_path: Path, monkeypatch) -> None:
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GCP_PROJECT", FAKE_GCP_PROJECT)
    monkeypatch.setenv("CLOUD_RUN_REGION", FAKE_REGION)
    monkeypatch.delenv("BMT_CONTROL_JOB", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("PR_NUMBER", "79")
    monkeypatch.setenv("HEAD_SHA", FAKE_SHA_ALT)

    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.download_json",
        lambda _: (
            {
                "repository": FAKE_REPO,
                "workflow_execution_name": "projects/p/locations/r/workflows/w/executions/ex-123",
                "workflow_run_id": "111",
                "head_sha": FAKE_SHA_ALT,
            },
            None,
        ),
    )
    monkeypatch.setattr("bmtgate.handoff.dispatch.cancel_execution", lambda **_: None)
    monkeypatch.setattr("bmtgate.handoff.dispatch.delete_object", lambda _: None)
    called: list[str] = []
    monkeypatch.setattr("bmtgate.handoff.dispatch.run_job", lambda **_: called.append("run"))

    WorkflowDispatchManager.from_env().cancel_pr_execution()
    outputs = _read_outputs(github_output)
    assert outputs["cancel_requested"] == "true"
    assert outputs["finalize_requested"] == "false"
    assert outputs["finalize_outcome"] == "skipped_no_bmt_control_job"
    assert called == []


def test_cancel_pr_execution_finalize_failed_when_run_job_raises(tmp_path: Path, monkeypatch) -> None:
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GCP_PROJECT", FAKE_GCP_PROJECT)
    monkeypatch.setenv("CLOUD_RUN_REGION", FAKE_REGION)
    monkeypatch.setenv("BMT_CONTROL_JOB", FAKE_CONTROL_JOB)
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("PR_NUMBER", "79")
    monkeypatch.setenv("HEAD_SHA", FAKE_SHA_ALT)

    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.download_json",
        lambda _: (
            {
                "repository": FAKE_REPO,
                "workflow_execution_name": "projects/p/locations/r/workflows/w/executions/ex-123",
                "workflow_run_id": "111",
                "head_sha": FAKE_SHA_ALT,
            },
            None,
        ),
    )
    monkeypatch.setattr("bmtgate.handoff.dispatch.cancel_execution", lambda **_: None)
    monkeypatch.setattr("bmtgate.handoff.dispatch.delete_object", lambda _: None)

    def _boom(**_kwargs):
        raise CloudRunJobsApiError("boom")

    monkeypatch.setattr("bmtgate.handoff.dispatch.run_job", _boom)

    WorkflowDispatchManager.from_env().cancel_pr_execution()
    outputs = _read_outputs(github_output)
    assert outputs["finalize_requested"] == "true"
    assert outputs["finalize_outcome"].startswith("failed:")


def test_cancel_pr_execution_head_sha_mismatch_still_cancels_and_finalizes(tmp_path: Path, monkeypatch) -> None:
    """Close-PR event SHA can differ from the index (e.g. last push); we still cancel GCP + finalize GitHub."""
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GCP_PROJECT", FAKE_GCP_PROJECT)
    monkeypatch.setenv("CLOUD_RUN_REGION", FAKE_REGION)
    monkeypatch.setenv("BMT_CONTROL_JOB", FAKE_CONTROL_JOB)
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("PR_NUMBER", "79")
    monkeypatch.setenv("HEAD_SHA", FAKE_SHA_ALT)

    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.download_json",
        lambda _: (
            {
                "repository": FAKE_REPO,
                "workflow_execution_name": "projects/p/locations/r/workflows/w/executions/ex-123",
                "workflow_run_id": "111",
                "head_sha": FAKE_SHA_MISMATCH,
            },
            None,
        ),
    )
    called: list[str] = []
    monkeypatch.setattr("bmtgate.handoff.dispatch.cancel_execution", lambda **_: called.append("cancel"))
    monkeypatch.setattr("bmtgate.handoff.dispatch.delete_object", lambda _: None)
    monkeypatch.setattr("bmtgate.handoff.dispatch.run_job", lambda **_: called.append("run_job"))

    WorkflowDispatchManager.from_env().cancel_pr_execution()
    outputs = _read_outputs(github_output)
    assert outputs["cancel_requested"] == "true"
    assert outputs["finalize_requested"] == "true"
    assert outputs["finalize_outcome"] == "success"
    assert called == ["cancel", "run_job"]


def test_cancel_pr_execution_cancel_failure_skips_finalize(tmp_path: Path, monkeypatch) -> None:
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("PR_NUMBER", "79")
    monkeypatch.setenv("HEAD_SHA", FAKE_SHA_ALT)

    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.download_json",
        lambda _: (
            {
                "repository": FAKE_REPO,
                "workflow_execution_name": "projects/p/locations/r/workflows/w/executions/ex-123",
                "workflow_run_id": "111",
                "head_sha": FAKE_SHA_ALT,
            },
            None,
        ),
    )

    def _cancel_boom(**_kwargs):
        raise WorkflowsApiError("cancel boom")

    called: list[str] = []
    monkeypatch.setattr("bmtgate.handoff.dispatch.cancel_execution", _cancel_boom)
    monkeypatch.setattr("bmtgate.handoff.dispatch.run_job", lambda **_: called.append("run_job"))

    WorkflowDispatchManager.from_env().cancel_pr_execution()
    outputs = _read_outputs(github_output)
    assert outputs["cancel_requested"] == "false"
    assert outputs["cancel_reason"].startswith("cancel_failed:")
    assert outputs["finalize_requested"] == "false"
    assert outputs["finalize_outcome"] == "skipped_cancel_failed"
    assert called == []


def test_cancel_pr_execution_cancel_failed_preserves_workflows_permission_error(tmp_path: Path, monkeypatch) -> None:
    """When cancel API fails (e.g. missing workflows.executions.cancel), reason is visible in GITHUB_OUTPUT."""
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("PR_NUMBER", "79")
    monkeypatch.setenv("HEAD_SHA", FAKE_SHA_ALT)

    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.download_json",
        lambda _: (
            {
                "repository": FAKE_REPO,
                "workflow_execution_name": "projects/p/locations/r/workflows/w/executions/ex-123",
                "workflow_run_id": "111",
                "head_sha": FAKE_SHA_ALT,
            },
            None,
        ),
    )

    api_detail = (
        "POST https://workflowexecutions.googleapis.com/v1/.../cancel failed: 403 "
        '{"error":{"code":403,"message":"Permission workflows.executions.cancel denied","status":"PERMISSION_DENIED"}}'
    )

    def _cancel_denied(**_kwargs):
        raise WorkflowsApiError(api_detail)

    monkeypatch.setattr("bmtgate.handoff.dispatch.cancel_execution", _cancel_denied)

    WorkflowDispatchManager.from_env().cancel_pr_execution()
    outputs = _read_outputs(github_output)
    assert outputs["cancel_requested"] == "false"
    assert outputs["cancel_reason"] == f"cancel_failed:{api_detail}"
    assert outputs["finalize_requested"] == "false"
    assert outputs["finalize_outcome"] == "skipped_cancel_failed"
    assert "403" in outputs["cancel_reason"]
    assert "PERMISSION_DENIED" in outputs["cancel_reason"]


def test_cancel_pr_execution_finalize_failed_preserves_cloud_run_permission_error(tmp_path: Path, monkeypatch) -> None:
    """When finalize Cloud Run job run fails (e.g. missing run.jobs.run), outcome carries API detail."""
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GCP_PROJECT", FAKE_GCP_PROJECT)
    monkeypatch.setenv("CLOUD_RUN_REGION", FAKE_REGION)
    monkeypatch.setenv("BMT_CONTROL_JOB", FAKE_CONTROL_JOB)
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("PR_NUMBER", "79")
    monkeypatch.setenv("HEAD_SHA", FAKE_SHA_ALT)

    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.download_json",
        lambda _: (
            {
                "repository": FAKE_REPO,
                "workflow_execution_name": "projects/p/locations/r/workflows/w/executions/ex-123",
                "workflow_run_id": "111",
                "head_sha": FAKE_SHA_ALT,
            },
            None,
        ),
    )
    monkeypatch.setattr("bmtgate.handoff.dispatch.cancel_execution", lambda **_: None)
    monkeypatch.setattr("bmtgate.handoff.dispatch.delete_object", lambda _: None)

    api_detail = (
        "POST https://run.googleapis.com/v2/projects/p/locations/europe-west4/jobs/bmt-control:run failed: 403 "
        '{"error":{"code":403,"message":"Permission run.jobs.run denied","status":"PERMISSION_DENIED"}}'
    )

    def _run_denied(**_kwargs):
        raise CloudRunJobsApiError(api_detail)

    monkeypatch.setattr("bmtgate.handoff.dispatch.run_job", _run_denied)

    WorkflowDispatchManager.from_env().cancel_pr_execution()
    outputs = _read_outputs(github_output)
    assert outputs["cancel_requested"] == "true"
    assert outputs["finalize_requested"] == "true"
    assert outputs["finalize_outcome"] == f"failed:{api_detail}"
    assert "403" in outputs["finalize_outcome"]
    assert "PERMISSION_DENIED" in outputs["finalize_outcome"]


def _invoke_env_base(tmp_path: Path, monkeypatch, *, github_run_id: str) -> Path:
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCP_PROJECT", FAKE_GCP_PROJECT)
    monkeypatch.setenv("CLOUD_RUN_REGION", FAKE_REGION)
    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setenv("GITHUB_RUN_ID", github_run_id)
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("HEAD_SHA", FAKE_SHA_ALT)
    monkeypatch.setenv("HEAD_BRANCH", "main")
    monkeypatch.setenv("HEAD_EVENT", "pull_request")
    monkeypatch.setenv("RUN_CONTEXT", "pr")
    monkeypatch.setenv("PR_NUMBER", "79")
    monkeypatch.setenv("FILTERED_MATRIX_JSON", json.dumps({"include": [{"project": "sk"}, {"project": "sk"}]}))
    monkeypatch.setattr("bmtgate.handoff.dispatch.upload_json", lambda *_a, **_k: None)
    return github_output


def test_invoke_cancels_superseded_pr_workflow_before_start(tmp_path: Path, monkeypatch) -> None:
    _invoke_env_base(tmp_path, monkeypatch, github_run_id="99999")
    cancel_calls: list[str] = []

    def _dl(_uri: str):
        return (
            {
                "repository": FAKE_REPO,
                "workflow_run_id": "111",
                "workflow_execution_name": "projects/p/locations/r/workflows/w/executions/old-ex",
            },
            None,
        )

    monkeypatch.setattr("bmtgate.handoff.dispatch.download_json", _dl)
    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.cancel_execution",
        lambda *, execution_name: cancel_calls.append(execution_name),
    )

    spy = _WorkflowDispatchSpy()

    def _fake_start_execution(
        *, project: str, region: str, workflow_name: str, argument: WorkflowDispatchInvokePayload
    ) -> WorkflowExecutionStubResponse:
        spy.project = project
        spy.region = region
        spy.workflow_name = workflow_name
        spy.argument = argument
        return {
            "name": f"projects/demo/locations/{FAKE_REGION}/workflows/bmt-workflow/executions/new-ex",
            "state": "ACTIVE",
        }

    monkeypatch.setattr("bmtgate.handoff.dispatch.start_execution", _fake_start_execution)
    WorkflowDispatchManager.from_env().invoke()
    assert cancel_calls == ["projects/p/locations/r/workflows/w/executions/old-ex"]
    assert spy.argument is not None
    assert spy.argument["workflow_run_id"] == "99999"


def test_invoke_skips_cancel_when_pr_active_same_workflow_run_id(tmp_path: Path, monkeypatch) -> None:
    _invoke_env_base(tmp_path, monkeypatch, github_run_id="111")
    cancel_calls: list[str] = []

    def _dl(_uri: str):
        return (
            {
                "repository": FAKE_REPO,
                "workflow_run_id": "111",
                "workflow_execution_name": "projects/p/locations/r/workflows/w/executions/same",
            },
            None,
        )

    monkeypatch.setattr("bmtgate.handoff.dispatch.download_json", _dl)
    monkeypatch.setattr(
        "bmtgate.handoff.dispatch.cancel_execution",
        lambda *, execution_name: cancel_calls.append(execution_name),
    )

    def _fake_start_execution(
        **kwargs: object,
    ) -> WorkflowExecutionStubResponse:
        return {
            "name": f"projects/demo/locations/{FAKE_REGION}/workflows/bmt-workflow/executions/x",
            "state": "ACTIVE",
        }

    monkeypatch.setattr("bmtgate.handoff.dispatch.start_execution", _fake_start_execution)
    WorkflowDispatchManager.from_env().invoke()
    assert cancel_calls == []


def test_invoke_starts_after_cancel_failure_on_supersede(tmp_path: Path, monkeypatch) -> None:
    _invoke_env_base(tmp_path, monkeypatch, github_run_id="222")
    start_calls = 0

    def _dl(_uri: str):
        return (
            {
                "repository": FAKE_REPO,
                "workflow_run_id": "111",
                "workflow_execution_name": "projects/p/locations/r/workflows/w/executions/old-ex",
            },
            None,
        )

    monkeypatch.setattr("bmtgate.handoff.dispatch.download_json", _dl)

    def _boom(*, execution_name: str):
        raise WorkflowsApiError(f"cancel failed {execution_name}")

    monkeypatch.setattr("bmtgate.handoff.dispatch.cancel_execution", _boom)

    def _fake_start_execution(
        **kwargs: object,
    ) -> WorkflowExecutionStubResponse:
        nonlocal start_calls
        start_calls += 1
        return {
            "name": f"projects/demo/locations/{FAKE_REGION}/workflows/bmt-workflow/executions/new",
            "state": "ACTIVE",
        }

    monkeypatch.setattr("bmtgate.handoff.dispatch.start_execution", _fake_start_execution)
    WorkflowDispatchManager.from_env().invoke()
    assert start_calls == 1
