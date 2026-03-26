"""`gcp/stage/projects/` layout: v2 paths with v1 fallback (bmts vs benchmarks; flat vs releases/)."""

from __future__ import annotations

from pathlib import Path

# Segment names under projects/<project>/
BENCHMARKS_V1 = "bmts"
BENCHMARKS_V2 = "benchmarks"


def project_dir(stage_root: Path, project: str) -> Path:
    return stage_root / "projects" / project


def resolve_plugin_workspace_dir(stage_root: Path, project: str, plugin_name: str) -> Path:
    """Editable plugin tree: prefer ``plugins/<name>/workspace/``, else ``plugin_workspaces/<name>/``."""
    pr = project_dir(stage_root, project)
    v2 = pr / "plugins" / plugin_name / "workspace"
    v1 = pr / "plugin_workspaces" / plugin_name
    if v2.is_dir():
        return v2
    return v1


def resolve_published_plugin_dir(stage_root: Path, project: str, plugin_name: str, digest_segment: str) -> Path:
    """Immutable bundle: prefer ``plugins/<name>/releases/<digest>`` if present, else flat ``plugins/<name>/<digest>``."""
    pr = project_dir(stage_root, project)
    v2 = pr / "plugins" / plugin_name / "releases" / digest_segment
    v1 = pr / "plugins" / plugin_name / digest_segment
    if v2.is_dir():
        return v2
    return v1


def published_dir_for_new_publish(stage_root: Path, project: str, plugin_name: str, digest_hex: str) -> Path:
    """Target directory when publishing from the workspace (v2 workspace → releases/; else flat)."""
    pr = project_dir(stage_root, project)
    digest_segment = f"sha256-{digest_hex}"
    ws_v2 = pr / "plugins" / plugin_name / "workspace"
    if ws_v2.is_dir():
        return pr / "plugins" / plugin_name / "releases" / digest_segment
    return pr / "plugins" / plugin_name / digest_segment


def iter_bmt_manifest_paths(*, projects_root: Path) -> list[Path]:
    """All ``bmt.json`` paths under ``projects/*/{benchmarks,bmts}/*/``; de-duplicated, sorted."""
    if not projects_root.is_dir():
        return []
    seen: set[Path] = set()
    out: list[Path] = []
    for pattern in (f"*/{BENCHMARKS_V2}/*/bmt.json", f"*/{BENCHMARKS_V1}/*/bmt.json"):
        for path in sorted(projects_root.glob(pattern)):
            key = path.resolve()
            if key not in seen:
                seen.add(key)
                out.append(path)
    out.sort(key=lambda p: p.as_posix())
    return out


def iter_bmt_manifest_paths_for_project(*, stage_root: Path, project: str) -> list[Path]:
    """``bmt.json`` files for one project (benchmarks first, then bmts; unique by slug if duplicated)."""
    root = project_dir(stage_root, project)
    by_slug: dict[str, Path] = {}
    for seg in (BENCHMARKS_V2, BENCHMARKS_V1):
        base = root / seg
        if not base.is_dir():
            continue
        for bdir in sorted(base.iterdir()):
            manifest = bdir / "bmt.json"
            if manifest.is_file():
                by_slug.setdefault(bdir.name, manifest)
    return sorted(by_slug.values(), key=lambda p: p.as_posix())


def resolve_bmt_manifest_path(stage_root: Path, project: str, bmt_slug: str) -> Path | None:
    """Return path to ``bmt.json`` if it exists under ``benchmarks/<slug>`` or ``bmts/<slug>``."""
    pr = project_dir(stage_root, project)
    for seg in (BENCHMARKS_V2, BENCHMARKS_V1):
        candidate = pr / seg / bmt_slug / "bmt.json"
        if candidate.is_file():
            return candidate
    return None


def benchmark_folder_from_manifest_rel(rel: Path) -> str:
    """Return ``benchmarks`` or ``bmts`` from a manifest path relative to stage root."""
    parts = rel.parts
    if len(parts) >= 4 and parts[0] == "projects":
        return parts[2]
    raise ValueError(f"Unexpected manifest-relative path: {rel}")
