"""Ordered contributor steps and lightweight repo signals (unit-testable)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkflowStep:
    """One row in the contributor workflow checklist."""

    key: str
    title: str
    summary: str
    primary_command: str


@dataclass(frozen=True)
class RepoWorkflowHints:
    """Cheap filesystem signals for `tools workflow status` / `just status`."""

    has_venv: bool
    stage_project_names: list[str]


def workflow_steps_ordered() -> list[WorkflowStep]:
    """Match docs/adding-a-project.md: scaffold → edit → quick checks → publish → bucket → full verify."""
    return [
        WorkflowStep(
            key="onboard",
            title="Dev environment",
            summary="uv sync + hooks. Extra args go to the bootstrap script (e.g. --dry-run).",
            primary_command="just onboard",
        ),
        WorkflowStep(
            key="contributor_add",
            title="Project, BMT, and/or dataset",
            summary="`just add`: new project; optional --bmt, --data (zip / dir / tar).",
            primary_command="just add <project> [--bmt=<folder>] [--data=<path>]",
        ),
        WorkflowStep(
            key="edit_scaffold",
            title="Edit plugin and manifests",
            summary="Under plugin_workspaces/default/ and bmts/<folder>/bmt.json.",
            primary_command="",
        ),
        WorkflowStep(
            key="test_local",
            title="Quick checks before publish",
            summary="`just test-local` then `just tools bmt verify`. See docs/local-bmt-testing.md.",
            primary_command="just test-local",
        ),
        WorkflowStep(
            key="publish_plugin",
            title="Publish plugin (enables BMT)",
            summary="Build bundle, set enabled in bmt.json, sync project to GCS (unless --no-sync).",
            primary_command="just publish   # or: just publish <project> [<bmt_folder>]",
        ),
        WorkflowStep(
            key="workspace_deploy",
            title="Upload full gcp/ mirror to bucket",
            summary="Whole gcp/ tree → bucket for CI. Same as `just workspace deploy`.",
            primary_command="just sync-to-bucket",
        ),
        WorkflowStep(
            key="test",
            title="Full verify before push",
            summary="pytest, ruff, ty, actionlint, shellcheck, layout (pre-push gate).",
            primary_command="just test",
        ),
    ]


def repo_workflow_hints(*, repo_root: Path) -> RepoWorkflowHints:
    has_venv = (repo_root / ".venv").is_dir()
    projects = repo_root / "gcp" / "stage" / "projects"
    names: list[str] = []
    if projects.is_dir():
        for p in sorted(projects.iterdir()):
            if p.is_dir() and not p.name.startswith("."):
                names.append(p.name)
    return RepoWorkflowHints(has_venv=has_venv, stage_project_names=names)
