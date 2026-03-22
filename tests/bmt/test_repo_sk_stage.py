from __future__ import annotations

import pytest

from gcp.image.runtime.models import StageRuntimePaths, WorkflowRequest
from gcp.image.runtime.planning import PlanOptions, build_plan

pytestmark = pytest.mark.integration


def test_repo_stage_sk_project_is_discoverable(repo_root) -> None:
    stage_root = repo_root / "gcp" / "stage"
    workspace_root = repo_root / ".local" / "test-bmt-framework"
    plan = build_plan(
        runtime=StageRuntimePaths(stage_root=stage_root, workspace_root=workspace_root),
        options=PlanOptions(
            request=WorkflowRequest(workflow_run_id="repo-stage", accepted_projects=["sk"]),
            allow_workspace_plugins=False,
        ),
    )

    sk_slugs = {(leg.project, leg.bmt_slug) for leg in plan.legs if leg.project == "sk"}
    assert ("sk", "false_alarms") in sk_slugs
    assert ("sk", "false_rejects") in sk_slugs
    assert all(not leg.plugin_ref.startswith("workspace:") for leg in plan.legs if leg.project == "sk")
