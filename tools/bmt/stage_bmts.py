"""Enumerate benchmark folders under staged projects (``benchmarks/`` or ``bmts/``)."""

from __future__ import annotations

from pathlib import Path

from backend.runtime.stage_paths import BENCHMARKS_V1, BENCHMARKS_V2


def iter_staged_bmts(*, stage_root: Path) -> list[tuple[str, str]]:
    """Return sorted (project, bmt_folder) pairs for each ``bmt.json`` under staged projects."""
    projects = stage_root / "projects"
    if not projects.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for proj_dir in sorted(projects.iterdir()):
        if not proj_dir.is_dir():
            continue
        for seg in (BENCHMARKS_V2, BENCHMARKS_V1):
            base = proj_dir / seg
            if not base.is_dir():
                continue
            for bmt_dir in sorted(base.iterdir()):
                if (bmt_dir / "bmt.json").is_file():
                    out.append((proj_dir.name, bmt_dir.name))
    return sorted(set(out))
