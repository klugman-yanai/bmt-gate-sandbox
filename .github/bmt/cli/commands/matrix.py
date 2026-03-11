"""Matrix building, filtering, and CMake release runner parsing."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cli import shared
from cli.gh_output import gh_notice, gh_warning
from cli.shared import require_env

# ---------------------------------------------------------------------------
# matrix (build matrix JSON from remote config)
# ---------------------------------------------------------------------------


def run_build() -> None:
    """Build matrix JSON from CMake release presets. Reads BMT_PRESETS_FILE, BMT_OUTPUT_KEY, GITHUB_OUTPUT."""
    github_output = require_env("GITHUB_OUTPUT")
    output_key = os.environ.get("BMT_OUTPUT_KEY", "matrix")
    presets_file = Path(os.environ.get("BMT_PRESETS_FILE", "CMakePresets.json"))
    presets = _load_configure_presets(presets_file)
    rows = _build_bmt_rows(presets).get("include", [])
    matrix = {
        "include": [{"project": str(row["project"]), "bmt_id": str(row["bmt_id"])} for row in rows]
    }
    if not matrix["include"]:
        gh_warning("No supported release runner rows found in CMake presets.")
    with Path(github_output).open("a", encoding="utf-8") as fh:
        _ = fh.write(f"{output_key}={json.dumps(matrix, separators=(',', ':'))}\n")
    print(f"Built matrix rows: {len(matrix['include'])}")


# ---------------------------------------------------------------------------
# filter-supported-matrix
# ---------------------------------------------------------------------------


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


def run_filter() -> None:
    """Filter supported BMT matrix rows by uploaded runner projects.
    Reads RUNNER_MATRIX, FULL_MATRIX, ACCEPTED_PROJECTS, BMT_OUTPUT_KEY, BMT_HAS_LEGS_KEY, GITHUB_OUTPUT."""
    github_output = require_env("GITHUB_OUTPUT")
    output_key = os.environ.get("BMT_OUTPUT_KEY", "matrix")
    has_legs_key = os.environ.get("BMT_HAS_LEGS_KEY", "has_legs")

    runner_matrix = _load_json(require_env("RUNNER_MATRIX"), "RUNNER_MATRIX")
    full_matrix = _load_json(require_env("FULL_MATRIX"), "FULL_MATRIX")
    accepted_projects = _load_json(os.environ.get("ACCEPTED_PROJECTS", "[]"), "ACCEPTED_PROJECTS")

    if not isinstance(runner_matrix, dict):
        raise TypeError("RUNNER_MATRIX must be a JSON object")
    if not isinstance(full_matrix, dict):
        raise TypeError("FULL_MATRIX must be a JSON object")
    if not isinstance(accepted_projects, list):
        raise TypeError("ACCEPTED_PROJECTS must be a JSON array")

    accepted_set = {str(item).strip() for item in accepted_projects if str(item).strip()}

    requested = _project_set_from_include(runner_matrix, "RUNNER_MATRIX")
    supported = _project_set_from_include(full_matrix, "FULL_MATRIX")

    supported_set = set(supported)
    unsupported = sorted(project for project in requested if project not in supported_set)
    for project in unsupported:
        print(
            f"::warning::Project '{project}' has no BMT config in this repo; no BMT leg will run for it."
        )

    include = full_matrix.get("include", [])
    if not isinstance(include, list):
        raise TypeError("FULL_MATRIX.include must be a JSON array")

    filtered_include: list[dict[str, Any]] = []
    for entry in include:
        if not isinstance(entry, dict):
            continue
        project = str(entry.get("project", "")).strip()
        if project not in accepted_set:
            continue
        row: dict[str, Any] = dict(entry)
        if not str(row.get("bmt_id", "")).strip():
            preset = str(row.get("preset", "")).strip()
            configure = str(row.get("configure", "")).strip()
            if preset:
                row["bmt_id"] = preset
            elif configure:
                row["bmt_id"] = configure.lower()
            else:
                row["bmt_id"] = f"{project}_default"
        filtered_include.append(row)
    filtered = {"include": filtered_include}

    supported_legs = len(include)
    legs = len(filtered_include)

    has_legs = "true"
    if supported_legs == 0:
        has_legs = "false"
        print(
            "::warning::No supported BMT projects in requested runner set; skipping BMT trigger/VM run."
        )
    elif legs == 0:
        raise RuntimeError(
            "Supported BMT projects exist, but no supported runner upload succeeded; refusing to skip VM handoff silently."
        )
    else:
        gh_notice(f"Triggering BMT for {legs} leg(s) (supported runners only).")

    filtered_json = json.dumps(filtered, separators=(",", ":"))
    with Path(github_output).open("a", encoding="utf-8") as fh:
        _ = fh.write(f"{output_key}={filtered_json}\n")
        _ = fh.write(f"{has_legs_key}={has_legs}\n")


# ---------------------------------------------------------------------------
# parse-release-runners (CMake presets)
# ---------------------------------------------------------------------------


def _load_configure_presets(presets_file: Path) -> list[dict[str, Any]]:
    if not presets_file.is_file():
        raise RuntimeError(f"Missing presets file: {presets_file}")
    try:
        payload = json.loads(presets_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {presets_file}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"Invalid CMakePresets payload in {presets_file}: expected object")
    presets = payload.get("configurePresets")
    if not isinstance(presets, list):
        raise TypeError(
            f"Invalid CMakePresets payload in {presets_file}: missing configurePresets array"
        )
    out: list[dict[str, Any]] = []
    for row in presets:
        if isinstance(row, dict):
            out.append(row)
    return out


def _build_ci_rows(presets: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for preset in presets:
        name = str(preset.get("name", "")).strip()
        if not name.endswith("_gcc_Release"):
            continue
        name_lower = name.lower()
        if "xtensa" in name_lower or "hexagon" in name_lower:
            continue
        project = name[: -len("_gcc_Release")].lower()
        if name in seen:
            continue
        seen.add(name)
        rows.append({"configure": name, "build": f"{name}-build", "short": name})
    return rows


def _build_bmt_rows(presets: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    include: list[dict[str, str]] = []
    for preset in presets:
        name = str(preset.get("name", "")).strip()
        if not name.endswith("_gcc_Release"):
            continue
        name_lower = name.lower()
        if "xtensa" in name_lower or "hexagon" in name_lower:
            continue
        project = name[: -len("_gcc_Release")].lower()
        binary_dir = str(preset.get("binaryDir", "")).replace("${sourceDir}/", "", 1)
        include.append(
            {
                "configure": name,
                "preset": name_lower,
                "project": project,
                "bmt_id": name_lower,
                "binary_dir": binary_dir,
            }
        )
    include.sort(key=lambda row: (row["project"], row["bmt_id"]))
    return {"include": include}


def run_release_runners() -> None:
    """Parse CMake release runners. Reads BMT_OUTPUT_FORMAT (ci|bmt), BMT_OUTPUT_KEY, BMT_PRESETS_FILE."""
    output_format = require_env("BMT_OUTPUT_FORMAT")
    if output_format not in {"ci", "bmt"}:
        raise RuntimeError(f"BMT_OUTPUT_FORMAT must be 'ci' or 'bmt', got {output_format!r}")

    presets_file = Path(os.environ.get("BMT_PRESETS_FILE", "CMakePresets.json"))
    github_output = os.environ.get("GITHUB_OUTPUT")

    presets = _load_configure_presets(presets_file)

    default_key = "presets"
    payload: dict[str, list[dict[str, str]]] | list[dict[str, str]]
    if output_format == "ci":
        payload = _build_ci_rows(presets)
    else:
        payload = _build_bmt_rows(presets)
        default_key = "runner_matrix"

    payload_json = json.dumps(payload, separators=(",", ":"))

    if github_output:
        key = (os.environ.get("BMT_OUTPUT_KEY", "") or "").strip() or default_key
        with Path(github_output).open("a", encoding="utf-8") as fh:
            _ = fh.write(f"{key}={payload_json}\n")
    else:
        print(payload_json)

    if output_format == "ci":
        row_count = len(payload) if isinstance(payload, list) else 0
        print(f"::notice::Building one job per release project: {payload_json}")
        print(f"Parsed CI release rows: {row_count}")
    else:
        include = payload.get("include", []) if isinstance(payload, dict) else []
        gh_notice(f"Runner matrix (all release projects): {payload_json}")
        print(f"Parsed BMT release rows: {len(include)}")
