from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.shared.core_main_ci_matrix import classify_build_presets, iter_all_matrix_entries, load_presets


def _minimal_doc() -> dict:
    return {
        "version": 3,
        "configurePresets": [
            {
                "name": "T_base",
                "hidden": True,
                "cacheVariables": {"FOO": "ON"},
            },
            {
                "name": "T_gcc_Release",
                "cacheVariables": {"ARCH": "x86_64", "CMAKE_BUILD_TYPE": "Release"},
            },
            {
                "name": "T_gcc_Debug",
                "cacheVariables": {"ARCH": "x86_64", "CMAKE_BUILD_TYPE": "Debug"},
            },
            {
                "name": "T_android_Release",
                "cacheVariables": {"ARCH": "android_aarch64", "CMAKE_BUILD_TYPE": "Release"},
            },
        ],
        "buildPresets": [
            {"name": "T_gcc_Release-build", "configurePreset": "T_gcc_Release"},
            {"name": "T_gcc_Debug-build", "configurePreset": "T_gcc_Debug"},
            {"name": "T_android_Release-build", "configurePreset": "T_android_Release"},
        ],
    }


def test_classify_minimal_fixture(tmp_path: Path) -> None:
    (tmp_path / "bmt" / "T").mkdir(parents=True)
    (tmp_path / "bmt" / "T" / "run-bmt.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    doc = _minimal_doc()
    rb, rnb, nr = classify_build_presets(doc, tmp_path)

    assert len(rb) == 1 and rb[0]["short"] == "T_gcc_Release"
    assert rb[0]["runnable_on_bmt_runner"] is True
    assert rb[0]["soft_fail"] is False

    assert len(rnb) == 1 and rnb[0]["short"] == "T_android_Release"
    assert rnb[0]["soft_fail"] is True

    assert len(nr) == 1 and nr[0]["short"] == "T_gcc_Debug"

    all_e = iter_all_matrix_entries(rb, rnb, nr)
    assert len(all_e) == len(doc["buildPresets"])


@pytest.mark.skipif(not os.environ.get("CORE_MAIN_ROOT"), reason="CORE_MAIN_ROOT not set")
def test_live_core_main_bucket_counts_match_build_presets() -> None:
    root = Path(os.environ["CORE_MAIN_ROOT"]).resolve()
    doc = load_presets(root)
    rb, rnb, nr = classify_build_presets(doc, root)
    assert len(rb) + len(rnb) + len(nr) == len(doc["buildPresets"])
