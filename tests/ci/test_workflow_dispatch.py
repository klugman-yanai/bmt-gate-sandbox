from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import pytest

from ci.kardome_bmt.workflow_dispatch import (
    WorkflowDispatchInvokePayload,
    WorkflowDispatchManager,
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
    monkeypatch.setenv("GCP_PROJECT", "demo-project")
    monkeypatch.setenv("CLOUD_RUN_REGION", "europe-west4")
    monkeypatch.setenv("GCS_BUCKET", "demo-bucket")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("HEAD_SHA", "0123456789abcdef0123456789abcdef01234567")
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
            "name": "projects/demo/locations/europe-west4/workflows/bmt-workflow/executions/abc",
            "state": "ACTIVE",
        }

    monkeypatch.setattr("ci.kardome_bmt.workflow_dispatch.start_execution", _fake_start_execution)

    WorkflowDispatchManager.from_env().invoke()

    outputs = _read_outputs(github_output)
    assert outputs["dispatch_confirmed"] == "true"
    assert outputs["workflow_execution_state"] == "ACTIVE"
    assert (
        outputs["workflow_execution_url"] == "https://console.cloud.google.com/workflows/workflow/"
        "europe-west4/bmt-workflow/execution/abc?project=demo-project"
    )
    assert json.loads(outputs["accepted_projects"]) == ["sk"]
    assert spy.project == "demo-project"
    assert spy.region == "europe-west4"
    assert spy.workflow_name == "bmt-workflow"
    assert spy.argument is not None
    assert spy.argument["bucket"] == "demo-bucket"
    assert spy.argument["workflow_run_id"] == "12345"
    assert spy.argument["accepted_projects_json"] == '["sk"]'
