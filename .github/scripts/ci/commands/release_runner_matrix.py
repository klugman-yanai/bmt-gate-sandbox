from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click


def _allow_all(raw: str) -> bool:
    normalized = " ".join((raw or "").strip().lower().split())
    return normalized in {"", "all", "*", "all release runners", "all-release-runners", "all_release_runners"}


def _allowed_projects(raw: str) -> set[str]:
    if _allow_all(raw):
        return set()
    return {item.strip().lower() for item in (raw or "").split(",") if item.strip()}


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
        raise TypeError(f"Invalid CMakePresets payload in {presets_file}: missing configurePresets array")
    out: list[dict[str, Any]] = []
    for row in presets:
        if isinstance(row, dict):
            out.append(row)
    return out


def _build_ci_rows(presets: list[dict[str, Any]], allowed: set[str]) -> list[dict[str, str]]:
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
        if allowed and project not in allowed:
            continue
        if name in seen:
            continue
        seen.add(name)
        rows.append({"configure": name, "build": f"{name}-build", "short": name})
    return rows


def _build_bmt_rows(presets: list[dict[str, Any]], allowed: set[str]) -> dict[str, list[dict[str, str]]]:
    include: list[dict[str, str]] = []
    for preset in presets:
        name = str(preset.get("name", "")).strip()
        if not name.endswith("_gcc_Release"):
            continue
        name_lower = name.lower()
        if "xtensa" in name_lower or "hexagon" in name_lower:
            continue
        project = name[: -len("_gcc_Release")].lower()
        if allowed and project not in allowed:
            continue
        binary_dir = str(preset.get("binaryDir", "")).replace("${sourceDir}/", "", 1)
        include.append(
            {
                "configure": name,
                "preset": name_lower,
                "project": project,
                "binary_dir": binary_dir,
            }
        )
    return {"include": include}


@click.command("parse-release-runners")
@click.option("--presets-file", default="CMakePresets.json", show_default=True, type=click.Path(path_type=Path))
@click.option("--project-filter", default="", envvar="BMT_PROJECTS")
@click.option("--output-format", type=click.Choice(["ci", "bmt"]), required=True)
@click.option("--output-key", default="", help="Output key for GITHUB_OUTPUT (defaults by format)")
@click.option("--github-output", envvar="GITHUB_OUTPUT")
def command(
    presets_file: Path,
    project_filter: str,
    output_format: str,
    output_key: str,
    github_output: str | None,
) -> None:
    """Parse CMake release runners once and emit CI/BMT matrix shapes."""
    presets = _load_configure_presets(presets_file)
    allowed = _allowed_projects(project_filter)

    default_key = "presets"
    payload: dict[str, list[dict[str, str]]] | list[dict[str, str]]
    if output_format == "ci":
        payload = _build_ci_rows(presets, allowed)
    else:
        payload = _build_bmt_rows(presets, allowed)
        default_key = "runner_matrix"

    payload_json = json.dumps(payload, separators=(",", ":"))

    if github_output:
        key = output_key.strip() or default_key
        with Path(github_output).open("a", encoding="utf-8") as fh:
            _ = fh.write(f"{key}={payload_json}\n")
    else:
        print(payload_json)

    allowed_raw = project_filter or "all release runners"
    if output_format == "ci":
        row_count = len(payload) if isinstance(payload, list) else 0
        print(f"::notice::Building one job per project (BMT_PROJECTS={allowed_raw}): {payload_json}")
        print(f"Parsed CI release rows: {row_count}")
    else:
        include = payload.get("include", []) if isinstance(payload, dict) else []
        print(f"::notice::Runner matrix (BMT_PROJECTS={allowed_raw}): {payload_json}")
        print(f"Parsed BMT release rows: {len(include)}")
