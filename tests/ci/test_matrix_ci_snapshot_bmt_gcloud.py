"""Tests for ``build-and-test.yml`` repo_snapshot jq parity."""

from __future__ import annotations

from pathlib import Path

from kardome_bmt.matrix_ci_snapshot_bmt_gcloud import (
    classify_build_preset_rows,
    snapshot_release_splits,
    write_github_bmt_gcloud_repo_snapshot,
)


def test_snapshot_splits_match_jq_semantics(tmp_path: Path) -> None:
    doc = {
        "buildPresets": [
            {"name": "sk_gcc_Release-build", "configurePreset": "sk_gcc_Release"},
            {"name": "sk_xtensa_Release-build", "configurePreset": "sk_xtensa_GCC_Release"},
            {"name": "sk_gcc_Debug-build", "configurePreset": "sk_gcc_Debug"},
        ]
    }
    rows = classify_build_preset_rows(doc)
    release, non_release = snapshot_release_splits(rows)
    release_shorts = {r["short"] for r in release}
    assert release_shorts == {"sk_gcc_Release"}
    assert {r["short"] for r in non_release} == {"sk_xtensa_Release", "sk_gcc_Debug"}
    xtensa_row = next(r for r in rows if "xtensa" in r["configure"].lower())
    assert xtensa_row["soft_fail"] is True
    assert xtensa_row["is_release"] is False


def test_writes_github_outputs(tmp_path: Path) -> None:
    dst = Path(tmp_path / "preset.json")
    dst.write_text(
        '{"buildPresets":[{"name":"sk_gcc_Release-build","configurePreset":"sk_gcc_Release"}]}',
        encoding="utf-8",
    )
    outp = Path(tmp_path / "out.txt")
    write_github_bmt_gcloud_repo_snapshot(
        dst, outp, presets_key_release="release_presets", presets_key_non="non_release_presets"
    )
    txt = outp.read_text(encoding="utf-8")
    assert "release_presets=" in txt
    assert "non_release_presets=" in txt
    line_rel = next(x for x in txt.splitlines() if x.startswith("release_presets="))
    payload = line_rel.split("=", 1)[1]
    assert '"is_release":true' in payload
