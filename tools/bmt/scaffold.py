"""Scaffold stage-based BMT projects and manifests."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tools.repo.paths import DEFAULT_STAGE_ROOT, repo_root


def _validate_name(name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError(f"Invalid name: {name}")


def _default_stage_root(stage_root: Path | None) -> Path:
    return stage_root if stage_root is not None else repo_root() / DEFAULT_STAGE_ROOT


def _project_root(stage_root: Path, project: str) -> Path:
    return stage_root / "projects" / project


def _plugin_package_name(project: str) -> str:
    return f"{project}_plugin"


def _plugin_class_name(project: str) -> str:
    return "".join(part.capitalize() for part in project.split("_")) + "Plugin"


def _project_manifest(project: str) -> str:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "project": project,
                "default_plugin": "default",
                "description": f"{project} BMT project",
            },
            indent=2,
        )
        + "\n"
    )


def _plugin_manifest(project: str) -> str:
    return (
        json.dumps(
            {
                "api_version": "v1",
                "plugin_name": "default",
                "entrypoint": f"{_plugin_package_name(project)}:{_plugin_class_name(project)}",
                "package_root": "src",
            },
            indent=2,
        )
        + "\n"
    )


def _plugin_init(project: str) -> str:
    class_name = _plugin_class_name(project)
    return f'from .plugin import {class_name}\n\n__all__ = ["{class_name}"]\n'


def _plugin_code(project: str) -> str:
    class_name = _plugin_class_name(project)
    return f"""from __future__ import annotations

from backend.config.bmt_domain_status import BmtLegStatus
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.plugin import BmtPlugin
from backend.runtime.sdk.results import CaseResult, ExecutionResult, PreparedAssets, ScoreResult, VerdictResult


class {class_name}(BmtPlugin):
    plugin_name = "default"
    api_version = "v1"

    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        return self.prepared_assets_from_context(context)

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        case_results: list[CaseResult] = []
        for wav_path in sorted(context.dataset_root.rglob("*.wav")):
            rel = wav_path.relative_to(context.dataset_root).as_posix()
            case_results.append(
                CaseResult(
                    case_id=rel,
                    input_path=wav_path,
                    exit_code=0,
                    status="ok",
                    metrics={{"score": 1.0}},
                )
            )
        return ExecutionResult(
            execution_mode_used="plugin_direct",
            case_results=case_results,
        )

    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult:
        aggregate = 1.0 if execution_result.case_results else 0.0
        return ScoreResult(
            aggregate_score=aggregate,
            metrics={{"case_count": len(execution_result.case_results)}},
            extra={{"baseline_present": baseline is not None}},
        )

    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        threshold = float(context.bmt_manifest.plugin_config.get("pass_threshold", 1.0))
        passed = score_result.aggregate_score >= threshold
        return VerdictResult(
            passed=passed,
            status=BmtLegStatus.PASS.value if passed else BmtLegStatus.FAIL.value,
            reason_code="score_above_threshold" if passed else "score_below_threshold",
            summary={{
                "aggregate_score": score_result.aggregate_score,
                "threshold": threshold,
            }},
        )
"""


def _bmt_manifest(project: str, bmt_slug: str, *, plugin_ref: str) -> str:
    from backend.runtime.sdk.manifest_build import build_default_bmt_manifest

    manifest = build_default_bmt_manifest(project, bmt_slug, plugin_ref=plugin_ref)
    return manifest.model_dump_json(by_alias=True, indent=2) + "\n"


def add_project(project: str, *, stage_root: Path | None = None, dry_run: bool = False) -> int:
    _validate_name(project)
    root = _project_root(_default_stage_root(stage_root), project)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Project scaffold already exists: {root}")

    files = {
        root / "project.json": _project_manifest(project),
        root / "README.md": f"# {project}\n",
        root / "plugin_workspaces" / "default" / "plugin.json": _plugin_manifest(project),
        root / "plugin_workspaces" / "default" / "src" / _plugin_package_name(project) / "__init__.py": _plugin_init(
            project
        ),
        root / "plugin_workspaces" / "default" / "src" / _plugin_package_name(project) / "plugin.py": _plugin_code(
            project
        ),
        root / "bmts" / "example" / "bmt.json": _bmt_manifest(project, "example", plugin_ref="workspace:default"),
        root / "inputs" / ".keep": "",
    }
    if dry_run:
        return 0
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return 0


def add_bmt(
    project: str,
    bmt_slug: str,
    *,
    stage_root: Path | None = None,
    plugin: str = "default",
    dry_run: bool = False,
) -> int:
    _validate_name(project)
    _validate_name(bmt_slug)
    root = _project_root(_default_stage_root(stage_root), project)
    if not root.exists():
        raise FileNotFoundError(f"Project scaffold does not exist: {root}")
    manifest_path = root / "bmts" / bmt_slug / "bmt.json"
    if manifest_path.exists():
        raise FileExistsError(f"BMT scaffold already exists: {manifest_path}")
    if not dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(_bmt_manifest(project, bmt_slug, plugin_ref=f"workspace:{plugin}"), encoding="utf-8")
    return 0
