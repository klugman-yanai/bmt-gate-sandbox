"""Enumerate benchmark folders (bmts/<slug>/bmt.json) under staged projects."""

from __future__ import annotations

from pathlib import Path


def iter_staged_bmts(*, stage_root: Path) -> list[tuple[str, str]]:
    """Return sorted (project, bmt_folder) pairs for each ``bmt.json`` under ``projects/*/bmts/*/``."""
    projects = stage_root / "projects"
    if not projects.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for proj_dir in sorted(projects.iterdir()):
        if not proj_dir.is_dir():
            continue
        bmts = proj_dir / "bmts"
        if not bmts.is_dir():
            continue
        for bmt_dir in sorted(bmts.iterdir()):
            if not bmt_dir.is_dir():
                continue
            if (bmt_dir / "bmt.json").is_file():
                out.append((proj_dir.name, bmt_dir.name))
    return out
