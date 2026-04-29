"""Tests for core-main extract-presets parity (``kardome_bmt.matrix_core_main``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from kardome_bmt.matrix_core_main import (
    classify_build_presets,
    iter_all_matrix_entries,
)


def _fixture_doc_with_u_release_without_bmt() -> dict:
    """T = BMT runnable; U = linux Release verify-only; Debug + Android = non-release."""
    return {
        "version": 3,
        "configurePresets": [
            {"name": "T_base", "hidden": True},
            {"name": "U_base", "hidden": True},
            {
                "name": "T_gcc_Release",
                "cacheVariables": {"ARCH": "x86_64", "CMAKE_BUILD_TYPE": "Release"},
            },
            {
                "name": "U_gcc_Release",
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
            {"name": "U_gcc_Release-build", "configurePreset": "U_gcc_Release"},
            {"name": "T_gcc_Debug-build", "configurePreset": "T_gcc_Debug"},
            {"name": "T_android_Release-build", "configurePreset": "T_android_Release"},
        ],
    }


def test_classify_host_release_buckets(tmp_path: Path) -> None:
    """``T`` uploads; ``U`` verifies only; Debug / Android → non-release with ``soft_fail`` rules."""
    (tmp_path / "bmt" / "T").mkdir(parents=True)
    (tmp_path / "bmt" / "T" / "run-bmt.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    doc = _fixture_doc_with_u_release_without_bmt()
    rb, rnb, nr = classify_build_presets(doc, tmp_path)

    assert [x["short"] for x in rb] == ["T_gcc_Release"]
    assert rb[0]["runnable_on_bmt_runner"] is True

    assert [x["short"] for x in rnb] == ["U_gcc_Release"]
    assert rnb[0]["runnable_on_bmt_runner"] is False

    shorts_nr = sorted(x["short"] for x in nr)
    assert shorts_nr == ["T_android_Release", "T_gcc_Debug"]
    assert all("soft_fail" in x for x in nr)

    merged = iter_all_matrix_entries(rb, rnb, nr)
    assert len(merged) == len(doc["buildPresets"])
