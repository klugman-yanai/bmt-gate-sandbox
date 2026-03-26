from __future__ import annotations

import json
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

import backend.main as image_main
import backend.runtime.entrypoint as runtime_entrypoint
from backend.runtime.artifacts import load_summary
from backend.runtime.entrypoint import run_coordinator_mode, run_plan_mode, run_task_mode
from tests.support.fixtures.paths import StagePaths
from tests.support.sentinels import FAKE_REPO, FAKE_SHA_ALT, FAKE_WORKFLOW_ID, SYNTH_BMT_SLUG, SYNTH_PROJECT
from tools.bmt.publisher import publish_bmt
from tools.bmt.scaffold import add_bmt, add_project

pytestmark = pytest.mark.integration


def test_runtime_modes_write_plan_summary_and_pointer(tmp_path: Path, monkeypatch) -> None:
    sp = StagePaths(tmp_path / "gcp" / "stage")
    workspace_root = tmp_path / "workspace"
    add_project(SYNTH_PROJECT, stage_root=sp.root, dry_run=False)
    add_bmt(SYNTH_PROJECT, SYNTH_BMT_SLUG, stage_root=sp.root, plugin="default")

    manifest_path = sp.bmt_manifest(SYNTH_PROJECT, SYNTH_BMT_SLUG)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["enabled"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    dataset_root = sp.inputs(SYNTH_PROJECT, SYNTH_BMT_SLUG)
    dataset_root.mkdir(parents=True, exist_ok=True)
    (dataset_root / "sample.wav").write_bytes(b"fake")
    # Avoid live GCS sync (GCS_BUCKET in env); this test exercises local runtime modes only.
    publish_bmt(stage_root=sp.root, project=SYNTH_PROJECT, bmt_slug=SYNTH_BMT_SLUG, sync=False)

    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("BMT_HEAD_SHA", FAKE_SHA_ALT)
    monkeypatch.setenv("BMT_HEAD_BRANCH", "main")
    monkeypatch.setenv("BMT_ACCEPTED_PROJECTS_JSON", json.dumps([SYNTH_PROJECT]))

    assert run_plan_mode(workflow_run_id=FAKE_WORKFLOW_ID, stage_root=sp.root) == 0
    assert (
        run_task_mode(
            workflow_run_id=FAKE_WORKFLOW_ID,
            task_profile="standard",
            task_index=0,
            stage_root=sp.root,
            workspace_root=workspace_root,
        )
        == 0
    )
    assert run_coordinator_mode(workflow_run_id=FAKE_WORKFLOW_ID, stage_root=sp.root) == 0

    assert not sp.trigger_plan(FAKE_WORKFLOW_ID).exists()
    assert not sp.trigger_summary(FAKE_WORKFLOW_ID, SYNTH_PROJECT, SYNTH_BMT_SLUG).exists()
    pointer_path = sp.current_json(SYNTH_PROJECT, SYNTH_BMT_SLUG)
    assert pointer_path.is_file()

    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    expected_run = f"{FAKE_WORKFLOW_ID}-{SYNTH_BMT_SLUG}"
    assert pointer["latest"] == expected_run
    assert pointer["last_passing"] == expected_run


def test_run_task_mode_writes_failure_summary_when_execute_leg_raises(tmp_path: Path, monkeypatch) -> None:
    sp = StagePaths(tmp_path / "gcp" / "stage")
    workspace_root = tmp_path / "workspace"
    add_project(SYNTH_PROJECT, stage_root=sp.root, dry_run=False)
    add_bmt(SYNTH_PROJECT, SYNTH_BMT_SLUG, stage_root=sp.root, plugin="default")

    manifest_path = sp.bmt_manifest(SYNTH_PROJECT, SYNTH_BMT_SLUG)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["enabled"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    dataset_root = sp.inputs(SYNTH_PROJECT, SYNTH_BMT_SLUG)
    dataset_root.mkdir(parents=True, exist_ok=True)
    (dataset_root / "sample.wav").write_bytes(b"fake")
    publish_bmt(stage_root=sp.root, project=SYNTH_PROJECT, bmt_slug=SYNTH_BMT_SLUG, sync=False)

    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("BMT_HEAD_SHA", FAKE_SHA_ALT)
    monkeypatch.setenv("BMT_HEAD_BRANCH", "main")
    monkeypatch.setenv("BMT_ACCEPTED_PROJECTS_JSON", json.dumps([SYNTH_PROJECT]))

    def boom(**_kwargs: object) -> None:
        raise RuntimeError("injected execute_leg failure")

    monkeypatch.setattr(runtime_entrypoint, "execute_leg", boom)

    wf_err = "wf-err"
    assert run_plan_mode(workflow_run_id=wf_err, stage_root=sp.root) == 0
    assert (
        run_task_mode(
            workflow_run_id=wf_err,
            task_profile="standard",
            task_index=0,
            stage_root=sp.root,
            workspace_root=workspace_root,
        )
        == 0
    )
    summary = load_summary(
        stage_root=sp.root,
        workflow_run_id=wf_err,
        project=SYNTH_PROJECT,
        bmt_slug=SYNTH_BMT_SLUG,
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
