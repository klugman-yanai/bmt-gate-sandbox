"""CMake buildPresets snapshot matching bmt-gcloud ``build-and-test.yml`` jq (repo_snapshot)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_GCC_RELEASE_MARKER = "_gcc_Release"


def _jq_test_icase(pattern: str, text: str) -> bool:
    return bool(re.search(re.escape(pattern), text, flags=re.IGNORECASE))


def classify_build_preset_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per buildPreset; same semantics as the jq snippet in ``build-and-test.yml``.

    Rows include ``build``, ``configure``, ``short``, ``is_release``, ``soft_fail``.
    """
    rows: list[dict[str, Any]] = []
    for build in doc.get("buildPresets", []) or []:
        if not isinstance(build, dict):
            continue
        raw_name = str(build.get("name", "") if build.get("name") is not None else "")
        configure = str(build.get("configurePreset", "") if build.get("configurePreset") is not None else "")
        short = str(raw_name).removesuffix("-build")
        is_release = (
            (_GCC_RELEASE_MARKER in configure)
            and (not _jq_test_icase("xtensa", configure))
            and (not _jq_test_icase("hexagon", configure))
        )
        soft_fail = _jq_test_icase("xtensa", configure) or _jq_test_icase("hexagon", configure)
        rows.append(
            {
                "build": raw_name,
                "configure": configure,
                "short": short,
                "is_release": is_release,
                "soft_fail": soft_fail,
            }
        )
    return rows


def snapshot_release_splits(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    release = [r for r in rows if r["is_release"]]
    non_release = [r for r in rows if not r["is_release"]]
    return release, non_release


def write_github_bmt_gcloud_repo_snapshot(
    presets_path: Path, github_output: str | Path, *, presets_key_release: str, presets_key_non: str
) -> None:
    from kardome_bmt.matrix_core_main import load_presets_file

    doc = load_presets_file(presets_path)
    rows = classify_build_preset_rows(doc)
    release_rows, non_release_rows = snapshot_release_splits(rows)
    rel_json = json.dumps(release_rows, separators=(",", ":"))
    nrel_json = json.dumps(non_release_rows, separators=(",", ":"))
    outp = Path(github_output)
    with outp.open("a", encoding="utf-8") as fh:
        fh.write(f"{presets_key_release}={rel_json}\n")
        fh.write(f"{presets_key_non}={nrel_json}\n")
