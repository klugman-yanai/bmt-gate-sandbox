#!/usr/bin/env python3
"""Symlink shared BMT native dependencies into each project's runner lib directory.

libKardome.so (and the runner) expect shared .so files (e.g. libonnxruntime.so) to be
in the same directory at runtime. Instead of copying dependencies into each project
lib dir, we create symlinks so one copy is shared.

Paths come from tools.repo.paths (DEFAULT_BMT_ROOT, BMT_DEPS_SUBDIR, BMT_PROJECT_LIB_SUBDIR).
Override with BMT_ROOT env or --bmt-root (relative to repo root or absolute).
Run from repo root. Safe to run repeatedly (idempotent).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from tools.repo.paths import (
    BMT_DEPS_SUBDIR,
    BMT_PROJECT_LIB_SUBDIR,
    DEFAULT_BMT_ROOT,
)


def _resolve_bmt_root(root: Path, bmt_root_raw: str | Path | None) -> Path:
    """Resolve BMT root dir: optional override (env/CLI) or default relative to repo root."""
    if bmt_root_raw is None or (isinstance(bmt_root_raw, str) and not bmt_root_raw.strip()):
        return root / DEFAULT_BMT_ROOT
    p = Path(bmt_root_raw) if isinstance(bmt_root_raw, str) else bmt_root_raw
    return p if p.is_absolute() else root / p


def _find_deps_dir(bmt_root: Path) -> Path:
    return bmt_root / BMT_DEPS_SUBDIR


def _find_project_lib_dirs(bmt_root: Path) -> list[Path]:
    """Find <bmt_root>/<project>/lib directories (per-project lib for libKardome.so + deps)."""
    lib_dirs: list[Path] = []
    if not bmt_root.is_dir():
        return lib_dirs
    for project_dir in bmt_root.iterdir():
        if not project_dir.is_dir() or project_dir.name.startswith(".") or project_dir.name == BMT_DEPS_SUBDIR.name:
            continue
        lib_dir = project_dir / BMT_PROJECT_LIB_SUBDIR
        if lib_dir.is_dir():
            lib_dirs.append(lib_dir)
    return sorted(lib_dirs)


def _repo_root() -> Path:
    root = Path(__file__).resolve().parent.parent.parent
    if not (root / "gcp").is_dir():
        raise SystemExit("Run from repo root (gcp/ not found).")
    return root


def run(
    *,
    root: Path | None = None,
    bmt_root: Path | str | None = None,
    deps_dir: Path | None = None,
    dry_run: bool = False,
) -> int:
    repo_root = root or _repo_root()
    bmt_base = _resolve_bmt_root(repo_root, bmt_root or os.environ.get("BMT_ROOT"))
    deps = deps_dir or _find_deps_dir(bmt_base)
    if not deps.is_dir():
        print(f"{deps} not found; nothing to symlink.", file=sys.stderr)
        return 0

    dep_files = sorted(p for p in deps.iterdir() if p.is_file())
    if not dep_files:
        print(f"No files in {deps}; nothing to symlink.", file=sys.stderr)
        return 0

    lib_dirs = _find_project_lib_dirs(bmt_base)
    if not lib_dirs:
        print(f"No {BMT_PROJECT_LIB_SUBDIR}/ dirs found under {bmt_base}.", file=sys.stderr)
        return 0

    updated = 0
    for lib_dir in lib_dirs:
        for dep in dep_files:
            link_path = lib_dir / dep.name
            try:
                target = dep.resolve()
            except OSError:
                continue
            if link_path.exists():
                if link_path.is_symlink():
                    try:
                        if link_path.resolve() == target:
                            if dry_run:
                                try:
                                    rel = link_path.relative_to(repo_root)
                                except ValueError:
                                    rel = link_path
                                print(f"Already linked: {rel} -> {dep.name}")
                            continue
                    except OSError:
                        pass
                    if not dry_run:
                        link_path.unlink()
                else:
                    # Real file; do not overwrite (e.g. libKardome.so)
                    continue
            if dry_run:
                print(f"Would link {link_path} -> {target}")
            else:
                link_path.symlink_to(os.path.relpath(target, link_path.parent))
                try:
                    rel = link_path.relative_to(repo_root)
                except ValueError:
                    rel = link_path
                print(f"Linked {rel} -> {dep.name}")
            updated += 1

    if updated and not dry_run:
        print(f"Created {updated} symlink(s).")
    elif dry_run and updated:
        print(f"Would create {updated} symlink(s). Run without --dry-run to apply.")
    elif dry_run and not updated and lib_dirs and dep_files:
        print("No changes needed; all symlinks already present and correct.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument(
        "--bmt-root",
        type=Path,
        default=None,
        metavar="DIR",
        help=f"BMT root (default: {DEFAULT_BMT_ROOT} or BMT_ROOT env); relative to repo root or absolute",
    )
    ap.add_argument(
        "--deps-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help=f"Override shared deps directory (default: <bmt-root>/{BMT_DEPS_SUBDIR})",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print what would be done")
    args = ap.parse_args()
    return run(bmt_root=args.bmt_root, deps_dir=args.deps_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
