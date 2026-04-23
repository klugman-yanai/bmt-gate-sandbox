"""Classify ``buildPresets`` the same way as core-main ``build-and-test.yml`` (extract-presets)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EMBEDDED_ARCHS = frozenset(
    {
        "xtensa",
        "hexagon",
        "webos_arm32",
        "webos_aarch64",
        "android_aarch64",
        "android_arm_v7",
        "mallet",
    }
)


def load_presets(core_main_root: Path) -> dict[str, Any]:
    path = core_main_root / "CMakePresets.json"
    return json.loads(path.read_text(encoding="utf-8"))


def classify_build_presets(doc: dict[str, Any], repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    configure_by_name = {preset["name"]: preset for preset in doc.get("configurePresets", [])}
    base_names = sorted(
        [
            preset["name"][: -len("_base")]
            for preset in doc.get("configurePresets", [])
            if preset.get("hidden") and str(preset["name"]).endswith("_base")
        ],
        key=len,
        reverse=True,
    )

    release_bmt: list[dict[str, Any]] = []
    release_no_bmt: list[dict[str, Any]] = []
    nonrelease: list[dict[str, Any]] = []

    for build in doc.get("buildPresets", []):
        configure_name = build["configurePreset"]
        configure = configure_by_name[configure_name]
        cache = configure.get("cacheVariables", {})
        arch = cache.get("ARCH", "")
        build_type = cache.get("CMAKE_BUILD_TYPE", "")
        is_linux_host = arch == "x86_64"
        bmt_key = next(
            (base for base in base_names if configure_name.startswith(f"{base}_")),
            configure_name,
        )
        has_bmt_script = (repo_root / "bmt" / str(bmt_key) / "run-bmt.sh").is_file()
        runnable = is_linux_host and build_type == "Release" and has_bmt_script

        skip_reasons: list[str] = []
        if build_type == "Release" and not runnable:
            if not is_linux_host:
                skip_reasons.append(f"arch={arch} (BMT runner is linux x86_64)")
            if not has_bmt_script:
                skip_reasons.append(f"no bmt/{bmt_key}/run-bmt.sh")

        entry: dict[str, Any] = {
            "build": build["name"],
            "configure": configure_name,
            "short": str(build["name"]).removesuffix("-build"),
            "bmt_key": bmt_key,
            "arch": arch,
            "os": "linux" if is_linux_host else "other",
            "runnable_on_bmt_runner": runnable,
            "soft_fail": arch in EMBEDDED_ARCHS,
            "skip_reason": "; ".join(skip_reasons),
        }
        if runnable:
            release_bmt.append(entry)
        elif build_type == "Release":
            release_no_bmt.append(entry)
        else:
            nonrelease.append(entry)

    return release_bmt, release_no_bmt, nonrelease


def iter_all_matrix_entries(
    release_bmt: list[dict[str, Any]],
    release_no_bmt: list[dict[str, Any]],
    nonrelease: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [*release_bmt, *release_no_bmt, *nonrelease]
