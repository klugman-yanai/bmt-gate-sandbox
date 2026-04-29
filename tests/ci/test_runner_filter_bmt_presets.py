"""``runner filter-bmt-presets`` / ``filter-bmt-presets.sh`` parity."""

from __future__ import annotations

import json
from pathlib import Path

from kardome_bmt.runner import filter_bmt_presets_upstream_artifacts_matrix


def test_filter_keeps_only_runnable_with_script(tmp_path: Path) -> None:
    art = tmp_path / "upstream"
    meta_dir = art / "runner-a"
    meta_dir.mkdir(parents=True)
    meta_dir.joinpath("metadata.json").write_text(
        json.dumps(
            {
                "runnable_on_bmt_runner": True,
                "build_preset": "T_gcc_Release-build",
                "bmt_key": "T",
                "configure_preset": "T_gcc_Release",
                "runner_path": "runner/kardome_runner",
                "arch": "x86_64",
                "os": "linux",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "bmt" / "T").mkdir(parents=True)
    (tmp_path / "bmt" / "T" / "run-bmt.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    items, count, hp = filter_bmt_presets_upstream_artifacts_matrix(art, tmp_path)
    assert count == 1 and hp
    assert items[0]["artifact_name"] == "runner-T_gcc_Release-build"
