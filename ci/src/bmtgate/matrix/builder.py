"""Matrix: build matrix from CMake presets, filter supported, parse release runners."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bmtgate.clients.actions import gh_notice, gh_warning, write_github_output
from bmtgate import core


def _load_configure_presets(presets_file: Path) -> list[dict[str, Any]]:
    if not presets_file.is_file():
        raise RuntimeError(f"Missing presets file: {presets_file}")
    try:
        payload = json.loads(presets_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {presets_file}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError("Invalid CMakePresets payload: expected object")
    presets = payload.get("configurePresets")
    if not isinstance(presets, list):
        raise TypeError("Missing configurePresets array")
    return [p for p in presets if isinstance(p, dict)]


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
        if name in seen:
            continue
        seen.add(name)
        rows.append({"configure": name, "build": f"{name}-build", "short": name})
    return rows


def _load_json(raw: str, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON for {label}: {exc}") from exc


def _project_set_from_include(payload: dict[str, Any], label: str) -> list[str]:
    include = payload.get("include", [])
    if not isinstance(include, list):
        raise TypeError(f"{label}.include must be a JSON array")
    projects = []
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


class MatrixManager:
    @classmethod
    def from_env(cls) -> MatrixManager:
        return cls()

    def __init__(self) -> None:
        pass

    def build(self) -> None:
        github_output = core.require_env("GITHUB_OUTPUT")
        output_key = os.environ.get("BMT_OUTPUT_KEY", "matrix")
        presets_file = Path(os.environ.get("BMT_PRESETS_FILE", "CMakePresets.json"))
        presets = _load_configure_presets(presets_file)
        rows = _build_bmt_rows(presets).get("include", [])
        matrix = {
            "include": [{"project": str(r["project"]), "bmt_id": str(r["bmt_id"])} for r in rows]
        }
        if not matrix["include"]:
            gh_warning("No supported release runner rows found in CMake presets.")
        write_github_output(github_output, output_key, json.dumps(matrix, separators=(",", ":")))
        print(f"Built matrix rows: {len(matrix['include'])}")

    def filter_supported(self) -> None:
        github_output = core.require_env("GITHUB_OUTPUT")
        output_key = os.environ.get("BMT_OUTPUT_KEY", "matrix")
        has_legs_key = os.environ.get("BMT_HAS_LEGS_KEY", "has_legs")
        runner_matrix = _load_json(core.require_env("RUNNER_MATRIX"), "RUNNER_MATRIX")
        full_matrix = _load_json(core.require_env("FULL_MATRIX"), "FULL_MATRIX")
        accepted_projects = _load_json(
            os.environ.get("ACCEPTED_PROJECTS", "[]"), "ACCEPTED_PROJECTS"
        )
        if (
            not isinstance(runner_matrix, dict)
            or not isinstance(full_matrix, dict)
            or not isinstance(accepted_projects, list)
        ):
            raise TypeError("RUNNER_MATRIX/FULL_MATRIX/ACCEPTED_PROJECTS type mismatch")
        accepted_set = {str(x).strip() for x in accepted_projects if str(x).strip()}
        requested = _project_set_from_include(runner_matrix, "RUNNER_MATRIX")
        supported = _project_set_from_include(full_matrix, "FULL_MATRIX")
        unsupported = sorted(p for p in requested if p not in set(supported))
        for project in unsupported:
            print(f"::warning::Project '{project}' has no BMT config in this repo.")
        include = full_matrix.get("include", [])
        if not isinstance(include, list):
            raise TypeError("FULL_MATRIX.include must be a JSON array")
        filtered_include = []
        for entry in include:
            if not isinstance(entry, dict):
                continue
            project = str(entry.get("project", "")).strip()
            if project not in accepted_set:
                continue
            row = dict(entry)
            if not str(row.get("bmt_id", "")).strip():
                row["bmt_id"] = (
                    str(row.get("preset", "") or row.get("configure", "") or f"{project}_default")
                    .strip()
                    .lower()
                    or f"{project}_default"
                )
            filtered_include.append(row)
        filtered = {"include": filtered_include}
        supported_legs = len(include)
        legs = len(filtered_include)
        has_legs = "false" if supported_legs == 0 else "true"
        if supported_legs == 0:
            print("::warning::No supported BMT projects in requested runner set; skipping BMT.")
        elif legs == 0:
            raise RuntimeError(
                "Supported BMT projects exist but no supported runner upload succeeded."
            )
        else:
            gh_notice(f"Triggering BMT for {legs} leg(s) (supported runners only).")
        write_github_output(github_output, output_key, json.dumps(filtered, separators=(",", ":")))
        write_github_output(github_output, has_legs_key, has_legs)

    def parse_release_runners(self) -> None:
        output_format = core.require_env("BMT_OUTPUT_FORMAT")
        if output_format not in {"ci", "bmt"}:
            raise RuntimeError(f"BMT_OUTPUT_FORMAT must be 'ci' or 'bmt', got {output_format!r}")
        presets_file = Path(os.environ.get("BMT_PRESETS_FILE", "CMakePresets.json"))
        github_output = os.environ.get("GITHUB_OUTPUT")
        presets = _load_configure_presets(presets_file)
        default_key = "presets"
        if output_format == "ci":
            payload = _build_ci_rows(presets)
        else:
            payload = _build_bmt_rows(presets)
            default_key = "runner_matrix"
        payload_json = json.dumps(payload, separators=(",", ":"))
        if github_output:
            key = (os.environ.get("BMT_OUTPUT_KEY", "") or "").strip() or default_key
            write_github_output(github_output, key, payload_json)
        else:
            print(payload_json)
        if output_format == "ci":
            row_count = len(payload) if isinstance(payload, list) else 0
            print(f"Parsed CI release rows: {row_count}")
        else:
            include = payload.get("include", []) if isinstance(payload, dict) else []
            gh_notice(f"Runner matrix: {payload_json}")
            print(f"Parsed BMT release rows: {len(include)}")
