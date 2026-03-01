from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click


def _load_json(raw: str, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON for {label}: {exc}") from exc


def _project_set_from_include(payload: dict[str, Any], label: str) -> list[str]:
    include = payload.get("include", [])
    if not isinstance(include, list):
        raise TypeError(f"{label}.include must be a JSON array")

    projects: list[str] = []
    seen: set[str] = set()
    for entry in include:
        if not isinstance(entry, dict):
            continue
        project = str(entry.get("project", "")).strip()
        if not project or project in seen:
            continue
        seen.add(project)
        projects.append(project)
    projects.sort()
    return projects


@click.command("filter-supported-matrix")
@click.option("--runner-matrix-json", required=True)
@click.option("--full-matrix-json", required=True)
@click.option("--accepted-projects-json", default="[]")
@click.option("--output-key", default="matrix", show_default=True)
@click.option("--has-legs-key", default="has_legs", show_default=True)
@click.option("--github-output", envvar="GITHUB_OUTPUT")
def command(
    runner_matrix_json: str,
    full_matrix_json: str,
    accepted_projects_json: str,
    output_key: str,
    has_legs_key: str,
    github_output: str | None,
) -> None:
    """Filter supported BMT matrix rows by successfully uploaded runner projects."""
    runner_matrix = _load_json(runner_matrix_json, "runner-matrix")
    full_matrix = _load_json(full_matrix_json, "full-matrix")
    accepted_projects = _load_json(accepted_projects_json, "accepted-projects")

    if not isinstance(runner_matrix, dict):
        raise TypeError("runner-matrix must be a JSON object")
    if not isinstance(full_matrix, dict):
        raise TypeError("full-matrix must be a JSON object")
    if not isinstance(accepted_projects, list):
        raise TypeError("accepted-projects must be a JSON array")

    accepted_set = {str(item).strip() for item in accepted_projects if str(item).strip()}

    requested = _project_set_from_include(runner_matrix, "runner-matrix")
    supported = _project_set_from_include(full_matrix, "full-matrix")

    supported_set = set(supported)
    unsupported = sorted(project for project in requested if project not in supported_set)
    for project in unsupported:
        print(f"::warning::Project '{project}' has no BMT config in this repo; no BMT leg will run for it.")

    include = full_matrix.get("include", [])
    if not isinstance(include, list):
        raise TypeError("full-matrix.include must be a JSON array")

    filtered_include = [
        entry for entry in include if isinstance(entry, dict) and str(entry.get("project", "")).strip() in accepted_set
    ]
    filtered = {"include": filtered_include}

    supported_legs = len(include)
    legs = len(filtered_include)

    if not github_output:
        raise RuntimeError("GITHUB_OUTPUT is required")

    has_legs = "true"
    if supported_legs == 0:
        has_legs = "false"
        print("::warning::No supported BMT projects in requested runner set; skipping BMT trigger/VM run.")
    elif legs == 0:
        raise RuntimeError(
            "Supported BMT projects exist, but no supported runner upload succeeded; cannot trigger BMT."
        )
    else:
        print(f"::notice::Triggering BMT for {legs} leg(s) (supported runners only).")

    filtered_json = json.dumps(filtered, separators=(",", ":"))
    with Path(github_output).open("a", encoding="utf-8") as fh:
        _ = fh.write(f"{output_key}={filtered_json}\n")
        _ = fh.write(f"{has_legs_key}={has_legs}\n")
