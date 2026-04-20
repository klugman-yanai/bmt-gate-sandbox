"""Matrix: build matrix from CMake presets, filter supported, parse release runners.

Also hosts capability + plan emission (see :mod:`kardome_bmt.capability`) as the
platform-owned alternative to caller-side ``bmt/<KEY>/run-bmt.sh`` heuristics.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from kardome_bmt import capability as _cap
from kardome_bmt import core
from kardome_bmt.actions import gh_notice, gh_warning


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
    """Build a release-runner matrix row per CMake preset.

    Schema per row (minimal, non-redundant):

    - ``project``     — slug matching ``plugins/projects/<project>/`` (lower-case).
    - ``preset``      — CMake preset name, lower-case; canonical identity in the
      handoff pipeline (used in artifact names, env vars, matrix keys).
    - ``configure``   — CMake preset name, original case; required by
      ``cmake --preset`` invocations in build workflows.
    - ``runner_path`` — in-tree path to the built ``kardome_runner`` binary
      (e.g. ``build/SK/gcc_Release/Runners/kardome_runner``).
    - ``lib_path``    — in-tree path to the built ``libKardome.so`` shared
      library (e.g. ``build/SK/gcc_Release/Kardome/libKardome.so``).

    Notes:
        The earlier schema carried ``bmt_id`` (exact duplicate of ``preset``)
        and ``binary_dir`` (now split into ``runner_path`` / ``lib_path``);
        both have been dropped. Runtime ``bmt_id`` (UUID per BMT leg in plugin
        manifests) is an unrelated concept and lives on the plugin side, not
        on the matrix row.
    """
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
                "project": project,
                "preset": name_lower,
                "configure": name,
                "runner_path": f"{binary_dir}/Runners/kardome_runner" if binary_dir else "",
                "lib_path": f"{binary_dir}/Kardome/libKardome.so" if binary_dir else "",
            }
        )
    include.sort(key=lambda row: (row["project"], row["preset"]))
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
        matrix = {"include": [{"project": str(r["project"]), "preset": str(r["preset"])} for r in rows]}
        if not matrix["include"]:
            gh_warning("No supported release runner rows found in CMake presets.")
        with Path(github_output).open("a", encoding="utf-8") as fh:
            fh.write(f"{output_key}={json.dumps(matrix, separators=(',', ':'))}\n")
        print(f"Built matrix rows: {len(matrix['include'])}")

    def filter_supported(self) -> None:
        github_output = core.require_env("GITHUB_OUTPUT")
        output_key = os.environ.get("BMT_OUTPUT_KEY", "matrix")
        has_legs_key = os.environ.get("BMT_HAS_LEGS_KEY", "has_legs")
        runner_matrix = _load_json(core.require_env("RUNNER_MATRIX"), "RUNNER_MATRIX")
        full_matrix = _load_json(core.require_env("FULL_MATRIX"), "FULL_MATRIX")
        accepted_projects = _load_json(os.environ.get("ACCEPTED_PROJECTS", "[]"), "ACCEPTED_PROJECTS")
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
            if not str(row.get("preset", "")).strip():
                row["preset"] = (
                    str(row.get("configure", "") or f"{project}_default").strip().lower() or f"{project}_default"
                )
            filtered_include.append(row)
        filtered = {"include": filtered_include}
        supported_legs = len(include)
        legs = len(filtered_include)
        has_legs = "false" if supported_legs == 0 else "true"
        if supported_legs == 0:
            print("::warning::No supported BMT projects in requested runner set; skipping BMT.")
        elif legs == 0:
            raise RuntimeError("Supported BMT projects exist but no supported runner upload succeeded.")
        else:
            gh_notice(f"Triggering BMT for {legs} leg(s) (supported runners only).")
        with Path(github_output).open("a", encoding="utf-8") as fh:
            fh.write(f"{output_key}={json.dumps(filtered, separators=(',', ':'))}\n")
            fh.write(f"{has_legs_key}={has_legs}\n")

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
            with Path(github_output).open("a", encoding="utf-8") as fh:
                fh.write(f"{key}={payload_json}\n")
        else:
            print(payload_json)
        if output_format == "ci":
            row_count = len(payload) if isinstance(payload, list) else 0
            print(f"Parsed CI release rows: {row_count}")
        else:
            include = payload.get("include", []) if isinstance(payload, dict) else []
            gh_notice(f"Runner matrix: {payload_json}")
            print(f"Parsed BMT release rows: {len(include)}")


def _write_json(payload: str, out: Path | None, github_output_key: str | None) -> None:
    """Emit ``payload`` to file, to GITHUB_OUTPUT, and/or stdout.

    The three sinks are independent so callers can combine them (e.g. write
    a file *and* populate a step output in the same invocation).
    """
    wrote_somewhere = False
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
        wrote_somewhere = True
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output and github_output_key:
        with Path(github_output).open("a", encoding="utf-8") as fh:
            fh.write(f"{github_output_key}={payload}\n")
        wrote_somewhere = True
    if not wrote_somewhere:
        print(payload)


def emit_capability(
    *,
    plugins_root: Path,
    platform_release: str,
    out: Path | None = None,
    github_output_key: str | None = None,
) -> _cap.CapabilityManifest:
    """Build a capability manifest and emit its JSON."""
    manifest = _cap.build_capability_manifest(plugins_root, platform_release)
    payload = manifest.model_dump_json()
    _write_json(payload, out, github_output_key)
    return manifest


def emit_plan(
    *,
    presets_file: Path,
    capability_source: _cap.CapabilityManifest | Path,
    commit: str | None = None,
    out: Path | None = None,
    github_output_key: str | None = None,
) -> _cap.Plan:
    """Project ``presets_file`` onto capability manifest → plan JSON."""
    capability = (
        capability_source
        if isinstance(capability_source, _cap.CapabilityManifest)
        else _cap.load_capability_manifest(capability_source)
    )
    plan = _cap.build_plan(presets_file, capability, commit=commit)
    payload = plan.model_dump_json()
    _write_json(payload, out, github_output_key)
    return plan
