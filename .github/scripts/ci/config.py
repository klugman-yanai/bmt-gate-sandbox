from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    """Raised when CI config files are missing or invalid."""


@dataclass(frozen=True, slots=True)
class MatrixRow:
    project: str
    bmt_id: str


def read_json_object(path: Path) -> dict[str, Any]:
    """Load and validate a JSON file as a single object; raises ConfigError if missing/invalid."""
    if not path.is_file():
        raise ConfigError(f"Missing JSON file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Expected JSON object at {path}")
    return data


def _parse_filter(raw: str) -> set[str]:
    normalized = " ".join(raw.strip().lower().split())
    if not normalized or normalized in {"all", "*", "all release runners", "all-release-runners", "all_release_runners"}:
        return set()
    return {item.strip() for item in raw.replace(",", " ").split() if item.strip()}


def _projects_cfg(config_root: Path) -> dict[str, Any]:
    payload = read_json_object(config_root / "bmt_projects.json")
    projects = payload.get("projects", {})
    if not isinstance(projects, dict):
        raise ConfigError(f"Invalid projects object in {config_root / 'bmt_projects.json'}")
    return projects


def _project_cfg(config_root: Path, project: str) -> dict[str, Any]:
    cfg = _projects_cfg(config_root).get(project)
    if not isinstance(cfg, dict):
        raise ConfigError(f"Unknown project: {project}")
    return cfg


def _jobs_cfg(config_root: Path, project_cfg: dict[str, Any]) -> dict[str, Any]:
    jobs_rel = str(project_cfg.get("jobs_config", "")).strip()
    if not jobs_rel:
        raise ConfigError("Project missing jobs_config")
    jobs_path = config_root / jobs_rel
    payload = read_json_object(jobs_path)
    bmts = payload.get("bmts", {})
    if not isinstance(bmts, dict):
        raise ConfigError(f"Invalid bmts object in {jobs_path}")
    return bmts


def build_matrix(config_root: Path, project_filter_raw: str) -> dict[str, list[dict[str, str]]]:
    """Build CI job matrix (project, bmt_id) from bmt_projects.json and jobs configs."""
    project_filter = _parse_filter(project_filter_raw)
    include: list[dict[str, str]] = []

    for project, project_cfg in _projects_cfg(config_root).items():
        if not isinstance(project_cfg, dict):
            continue
        if not bool(project_cfg.get("enabled", True)):
            continue
        if project_filter and project not in project_filter:
            continue

        bmts = _jobs_cfg(config_root, project_cfg)
        for bmt_id, bmt_cfg in bmts.items():
            if isinstance(bmt_cfg, dict) and bool(bmt_cfg.get("enabled", True)):
                include.append({"project": project, "bmt_id": bmt_id})

    include.sort(key=lambda row: (row["project"], row["bmt_id"]))
    return {"include": include}


def resolve_bmt_cfg(config_root: Path, project: str, bmt_id: str) -> dict[str, Any]:
    project_cfg = _project_cfg(config_root, project)
    bmt_cfg = _jobs_cfg(config_root, project_cfg).get(bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise ConfigError(f"Unknown bmt_id: {project}.{bmt_id}")
    return bmt_cfg


def resolve_results_prefix(config_root: Path, project: str, bmt_id: str) -> str:
    """Return paths.results_prefix for the given project and bmt_id."""
    bmt_cfg = resolve_bmt_cfg(config_root, project, bmt_id)
    paths_cfg = bmt_cfg.get("paths", {})
    if not isinstance(paths_cfg, dict):
        raise ConfigError(f"BMT {project}.{bmt_id} paths must be an object")

    results_prefix = str(paths_cfg.get("results_prefix", "")).strip().rstrip("/")
    if not results_prefix:
        raise ConfigError(f"BMT {project}.{bmt_id} missing paths.results_prefix")
    return results_prefix
