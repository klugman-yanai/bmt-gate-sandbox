"""Flat-manifest discovery must not treat non-BMT JSON as BmtManifest."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.models import StageRuntimePaths, WorkflowRequest
from runtime.planning import PlanOptions, build_plan


@pytest.mark.unit
def test_build_plan_skips_runner_integration_contract_json(plugins_root: Path) -> None:
    """runner_integration_contract.json lives next to flat manifests but is not a BMT manifest."""
    contract = plugins_root / "projects" / "sk" / "runner_integration_contract.json"
    assert contract.is_file(), "expected committed SK runner contract artifact"
    runtime = StageRuntimePaths(stage_root=plugins_root, workspace_root=plugins_root)
    request = WorkflowRequest(
        workflow_run_id="999",
        repository="test/test",
        accepted_projects=["sk"],
    )
    plan = build_plan(runtime=runtime, options=PlanOptions(request=request))
    assert plan.standard_task_count >= 1
    assert all(leg.project == "sk" for leg in plan.legs)
