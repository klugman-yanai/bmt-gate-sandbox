from __future__ import annotations

import json
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

import runtime.entrypoint as runtime_entrypoint
import runtime.main as image_main
from runtime.artifacts import load_summary
from runtime.entrypoint import run_coordinator_mode, run_plan_mode, run_task_mode

pytestmark = pytest.mark.integration


def _setup_flat_project(stage_root: Path, project: str, bmt_slug: str) -> None:
    """Set up a flat-layout project with plugin.py at project root and a flat BMT manifest."""
    import uuid

    project_dir = stage_root / "projects" / project
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(
        json.dumps({"schema_version": 1, "project": project}, indent=2) + "\n",
        encoding="utf-8",
    )
    bmt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://bmt/{project}/{bmt_slug}"))
    (project_dir / f"{bmt_slug}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project": project,
                "bmt_slug": bmt_slug,
                "bmt_id": bmt_id,
                "enabled": True,
                "plugin_ref": "direct",
                "inputs_prefix": f"projects/{project}/inputs/{bmt_slug}",
                "results_prefix": f"projects/{project}/results/{bmt_slug}",
                "outputs_prefix": f"projects/{project}/outputs/{bmt_slug}",
                "runner": {"uri": "", "deps_prefix": "", "template_path": "runtime/assets/kardome_input_template.json"},
                "execution": {"policy": "adaptive_batch_then_legacy"},
                "plugin_config": {"pass_threshold": 1.0},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    # Flat layout: plugin.py at project root
    (project_dir / "plugin.py").write_text(
        f"""from __future__ import annotations
from bmt_sdk import BmtPlugin, ExecutionContext
from bmt_sdk.results import CaseResult, ExecutionResult, PreparedAssets, ScoreResult, VerdictResult
from runtime.config.bmt_domain_status import BmtLegStatus


class {project.capitalize()}Plugin(BmtPlugin):
    plugin_name = "default"
    api_version = "v1"

    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        return PreparedAssets(
            dataset_root=context.dataset_root,
            workspace_root=context.workspace_root,
            runner_path=context.runner_path,
        )

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        case_results: list[CaseResult] = []
        for wav_path in sorted(context.dataset_root.rglob("*.wav")):
            rel = wav_path.relative_to(context.dataset_root).as_posix()
            case_results.append(
                CaseResult(case_id=rel, input_path=wav_path, exit_code=0, status="ok", metrics={{"score": 1.0}})
            )
        return ExecutionResult(execution_mode_used="plugin_direct", case_results=case_results)

    def score(self, execution_result: ExecutionResult, baseline: ScoreResult | None, context: ExecutionContext) -> ScoreResult:
        aggregate = 1.0 if execution_result.case_results else 0.0
        return ScoreResult(aggregate_score=aggregate, metrics={{"case_count": len(execution_result.case_results)}}, extra={{"baseline_present": baseline is not None}})

    def evaluate(self, score_result: ScoreResult, baseline: ScoreResult | None, context: ExecutionContext) -> VerdictResult:
        passed = score_result.aggregate_score >= 1.0
        return VerdictResult(
            passed=passed,
            status=BmtLegStatus.PASS.value if passed else BmtLegStatus.FAIL.value,
            reason_code="score_above_threshold" if passed else "score_below_threshold",
            summary={{"aggregate_score": score_result.aggregate_score}},
        )
""",
        encoding="utf-8",
    )


def test_runtime_modes_write_plan_summary_and_pointer(tmp_path: Path, monkeypatch) -> None:
    stage_root = tmp_path / "gcp" / "stage"
    workspace_root = tmp_path / "workspace"
    _setup_flat_project(stage_root, "acme", "wake_word_quality")

    dataset_root = stage_root / "projects" / "acme" / "inputs" / "wake_word_quality"
    dataset_root.mkdir(parents=True, exist_ok=True)
    (dataset_root / "sample.wav").write_bytes(b"fake")

    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("BMT_HEAD_SHA", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("BMT_HEAD_BRANCH", "main")
    monkeypatch.setenv("BMT_ACCEPTED_PROJECTS_JSON", '["acme"]')

    assert run_plan_mode(workflow_run_id="wf-123", stage_root=stage_root) == 0
    assert (
        run_task_mode(
            workflow_run_id="wf-123",
            task_profile="standard",
            task_index=0,
            stage_root=stage_root,
            workspace_root=workspace_root,
        )
        == 0
    )
    assert run_coordinator_mode(workflow_run_id="wf-123", stage_root=stage_root) == 0

    plan_path = stage_root / "triggers" / "plans" / "wf-123.json"
    summary_path = stage_root / "triggers" / "summaries" / "wf-123" / "acme-wake_word_quality.json"
    pointer_path = stage_root / "projects" / "acme" / "results" / "wake_word_quality" / "current.json"
    assert not plan_path.exists()
    assert not summary_path.exists()
    assert pointer_path.is_file()

    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer["latest"] == "wf-123-wake_word_quality"
    assert pointer["last_passing"] == "wf-123-wake_word_quality"


def test_run_task_mode_writes_failure_summary_when_execute_leg_raises(tmp_path: Path, monkeypatch) -> None:
    stage_root = tmp_path / "gcp" / "stage"
    workspace_root = tmp_path / "workspace"
    _setup_flat_project(stage_root, "acme", "wake_word_quality")

    dataset_root = stage_root / "projects" / "acme" / "inputs" / "wake_word_quality"
    dataset_root.mkdir(parents=True, exist_ok=True)
    (dataset_root / "sample.wav").write_bytes(b"fake")

    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("BMT_HEAD_SHA", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("BMT_HEAD_BRANCH", "main")
    monkeypatch.setenv("BMT_ACCEPTED_PROJECTS_JSON", '["acme"]')

    def boom(**_kwargs: object) -> None:
        raise RuntimeError("injected execute_leg failure")

    monkeypatch.setattr(runtime_entrypoint, "execute_leg", boom)

    assert run_plan_mode(workflow_run_id="wf-err", stage_root=stage_root) == 0
    assert (
        run_task_mode(
            workflow_run_id="wf-err",
            task_profile="standard",
            task_index=0,
            stage_root=stage_root,
            workspace_root=workspace_root,
        )
        == 0
    )
    summary = load_summary(
        stage_root=stage_root,
        workflow_run_id="wf-err",
        project="acme",
        bmt_slug="wake_word_quality",
    )
    assert summary.status == "fail"
    assert summary.reason_code == "runner_failures"
    assert summary.score.extra.get("unavailable") is True


def test_image_main_dispatches_task_mode(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    called: dict[str, object] = {}

    def fake_run_task_mode(
        *,
        workflow_run_id: str,
        task_profile: str,
        task_index: int,
        stage_root: Path | None = None,
        workspace_root: Path | None = None,
    ) -> int:
        called.update(
            {
                "workflow_run_id": workflow_run_id,
                "task_profile": task_profile,
                "task_index": task_index,
                "stage_root": stage_root,
                "workspace_root": workspace_root,
            }
        )
        return 0

    monkeypatch.setattr(runtime_entrypoint, "run_task_mode", fake_run_task_mode)
    monkeypatch.setenv("BMT_MODE", "task")
    monkeypatch.setenv("BMT_WORKFLOW_RUN_ID", "wf-456")
    monkeypatch.setenv("BMT_TASK_PROFILE", "heavy")
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "2")
    monkeypatch.setenv("BMT_RUNTIME_ROOT", str(tmp_path / "stage"))
    monkeypatch.setenv("BMT_FRAMEWORK_WORKSPACE", str(tmp_path / "workspace"))

    assert image_main.main() == 0
    assert called == {
        "workflow_run_id": "wf-456",
        "task_profile": "heavy",
        "task_index": 2,
        "stage_root": (tmp_path / "stage").resolve(),
        "workspace_root": (tmp_path / "workspace").resolve(),
    }
