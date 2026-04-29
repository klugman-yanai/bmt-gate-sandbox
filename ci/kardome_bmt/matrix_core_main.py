"""Classify core-main CMake buildPresets for BMT runner artifact publishing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_NONRELEASE_SOFT_FAIL_NEEDLES = ("xtensa", "hexagon", "mingw", "webos")


def load_presets_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Missing presets file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError("CMakePresets.json must be a JSON object")
    return data


def classify_build_presets(
    doc: dict[str, Any], repo_root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify host Release presets as runner-artifact candidates.

    BMT support is owned by bmt-gcloud's plugin/runtime registry.  The consumer
    repo only decides whether a preset can build a host runner artifact.
    """
    configure_by_name = {
        preset["name"]: preset for preset in doc.get("configurePresets", []) if isinstance(preset.get("name"), str)
    }
    base_names = sorted(
        [
            str(preset["name"])[: -len("_base")]
            for preset in doc.get("configurePresets", [])
            if isinstance(preset, dict) and preset.get("hidden") and str(preset.get("name", "")).endswith("_base")
        ],
        key=len,
        reverse=True,
    )

    release_bmt: list[dict[str, Any]] = []
    release_no_bmt: list[dict[str, Any]] = []
    nonrelease: list[dict[str, Any]] = []

    for build in doc.get("buildPresets", []) or []:
        if not isinstance(build, dict):
            continue
        configure_name = str(build.get("configurePreset", "")).strip()
        if configure_name not in configure_by_name:
            raise KeyError(f"configurePreset references missing configure preset: {configure_name!r}")
        configure = configure_by_name[configure_name]
        cache = configure.get("cacheVariables", {})
        if not isinstance(cache, dict):
            cache = {}
        arch = str(cache.get("ARCH", "") if cache.get("ARCH", "") is not None else "")
        build_type = str(cache.get("CMAKE_BUILD_TYPE", "") if cache.get("CMAKE_BUILD_TYPE", "") is not None else "")
        is_linux_host = arch == "x86_64"
        bmt_key = next(
            (base for base in base_names if configure_name.startswith(f"{base}_")),
            configure_name,
        )
        is_host_release = is_linux_host and build_type == "Release"

        entry: dict[str, Any] = {
            "build": build["name"],
            "configure": configure_name,
            "short": str(build["name"]).removesuffix("-build"),
            "bmt_key": bmt_key,
            "arch": arch,
            "os": "linux" if is_linux_host else "other",
            "build_type": build_type,
            "runnable_on_bmt_runner": is_host_release,
        }
        if is_host_release:
            release_bmt.append(entry)
        else:
            hay = f"{configure_name} {build['name']}".lower()
            entry["soft_fail"] = any(m in hay for m in _NONRELEASE_SOFT_FAIL_NEEDLES)
            nonrelease.append(entry)

    return release_bmt, release_no_bmt, nonrelease


def write_github_presets_outputs(
    release_bmt: list[dict[str, Any]],
    release_no_bmt: list[dict[str, Any]],
    nonrelease: list[dict[str, Any]],
    github_output: str | Path,
    *,
    key_release: str = "presets_release",
    key_nonrelease: str = "presets_nonrelease",
) -> None:
    """Emit ``GITHUB_OUTPUT`` lines matching core-main Actions outputs."""
    release_all = [*release_bmt, *release_no_bmt]
    line_release = json.dumps(release_all, separators=(",", ":"))
    line_nonrelease = json.dumps(nonrelease, separators=(",", ":"))
    outp = Path(github_output)
    with outp.open("a", encoding="utf-8") as fh:
        fh.write(f"{key_release}={line_release}\n")
        fh.write(f"{key_nonrelease}={line_nonrelease}\n")


def extract_presets_github_output_from_repo(
    repo_root: Path,
    presets_file: Path,
    github_output: str | Path,
) -> None:
    """Resolve ``presets_file`` against ``repo_root`` when relative; classify and emit outputs."""
    path = presets_file if presets_file.is_absolute() else (repo_root / presets_file).resolve()
    doc = load_presets_file(path)
    rb, rnb, nr = classify_build_presets(doc, repo_root.resolve())
    write_github_presets_outputs(rb, rnb, nr, github_output)


def iter_all_matrix_entries(
    release_bmt: list[dict[str, Any]],
    release_no_bmt: list[dict[str, Any]],
    nonrelease: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [*release_bmt, *release_no_bmt, *nonrelease]
