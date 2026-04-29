"""Layout policy: ``tools.shared.core_main_ci_matrix`` matches ``kardome_bmt.matrix_core_main``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from kardome_bmt.matrix_core_main import classify_build_presets as classify_k

from tools.shared.core_main_ci_matrix import classify_build_presets, load_presets


def test_reexport_alias_matches_canonical(tmp_path: Path) -> None:
    doc = {
        "configurePresets": [
            {"name": "T_base", "hidden": True},
            {
                "name": "T_gcc_Release",
                "cacheVariables": {"ARCH": "x86_64", "CMAKE_BUILD_TYPE": "Release"},
            },
        ],
        "buildPresets": [{"name": "T_gcc_Release-build", "configurePreset": "T_gcc_Release"}],
    }
    assert classify_build_presets(doc, tmp_path) == classify_k(doc, tmp_path)


@pytest.mark.skipif(not os.environ.get("CORE_MAIN_ROOT"), reason="CORE_MAIN_ROOT not set")
def test_live_core_main_bucket_counts_match_build_presets() -> None:
    root = Path(os.environ["CORE_MAIN_ROOT"]).resolve()
    doc = load_presets(root)
    rb, rnb, nr = classify_build_presets(doc, root)
    assert len(rb) + len(rnb) + len(nr) == len(doc["buildPresets"])
