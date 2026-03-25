"""Project-level checks for ``gcp/stage`` layout (manifests, paths, plugin digests)."""

from __future__ import annotations

from pathlib import Path

from gcp.image.runtime.models import BmtManifest, PluginManifest, ProjectManifest
from gcp.image.runtime.plugin_loader import PluginLoadError, load_plugin
from gcp.image.runtime.plugin_publisher import plugin_digest
from gcp.image.runtime.stage_paths import (
    BENCHMARKS_V1,
    BENCHMARKS_V2,
    iter_bmt_manifest_paths_for_project,
    resolve_plugin_workspace_dir,
    resolve_published_plugin_dir,
)


def _prefix_path(stage_root: Path, posix_prefix: str) -> Path:
    """Turn a stage-root-relative posix prefix (e.g. ``projects/sk/inputs/x``) into a path."""
    return stage_root.joinpath(*posix_prefix.split("/"))


def doctor_stage_project(*, stage_root: Path, project: str) -> tuple[int, list[str]]:
    """Return (exit_code, lines). ``0`` when no errors (warnings still listed)."""
    lines: list[str] = []
    errors = 0
    pr = stage_root / "projects" / project
    pj = pr / "project.json"
    if not pj.is_file():
        lines.append(f"ERROR: missing {pj}")
        return 1, lines
    try:
        ProjectManifest.model_validate_json(pj.read_text(encoding="utf-8"))
    except Exception as exc:
        lines.append(f"ERROR: invalid project.json: {exc}")
        errors += 1

    manifests = iter_bmt_manifest_paths_for_project(stage_root=stage_root, project=project)
    if not manifests:
        lines.append(f"ERROR: no bmt.json under {pr}/{{{BENCHMARKS_V2},{BENCHMARKS_V1}}}/*/")
        errors += 1
        return 1 if errors else 0, lines

    for manifest_path in manifests:
        slug = manifest_path.parent.name
        try:
            manifest = BmtManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            lines.append(f"ERROR: {manifest_path}: invalid manifest: {exc}")
            errors += 1
            continue

        if manifest.project != project:
            lines.append(f"ERROR: {manifest_path}: manifest.project {manifest.project!r} != folder project {project!r}")
            errors += 1
        if manifest.bmt_slug != slug:
            lines.append(f"ERROR: {manifest_path}: manifest.bmt_slug {manifest.bmt_slug!r} != folder {slug!r}")
            errors += 1

        inputs_dir = _prefix_path(stage_root, manifest.inputs_prefix)
        if not inputs_dir.is_dir():
            lines.append(f"ERROR: {manifest_path}: inputs_prefix not a directory: {inputs_dir}")
            errors += 1

        runner_path = _prefix_path(stage_root, manifest.runner.uri)
        if not runner_path.exists():
            lines.append(f"ERROR: {manifest_path}: runner.uri missing: {runner_path}")
            errors += 1

        if manifest.plugin_ref.startswith("published:"):
            parts = manifest.plugin_ref.split(":", 2)
            if len(parts) != 3:
                lines.append(f"ERROR: {manifest_path}: malformed published plugin_ref")
                errors += 1
                continue
            _, pname, digest_segment = parts
            published_root = resolve_published_plugin_dir(stage_root, project, pname, digest_segment)
            pjson = published_root / "plugin.json"
            if not pjson.is_file():
                lines.append(f"ERROR: {manifest_path}: missing published bundle: {pjson}")
                errors += 1
                continue
            try:
                PluginManifest.model_validate_json(pjson.read_text(encoding="utf-8"))
            except Exception as exc:
                lines.append(f"ERROR: {manifest_path}: invalid plugin.json: {exc}")
                errors += 1
                continue
            expected = digest_segment.removeprefix("sha256-")
            actual = plugin_digest(published_root)
            if actual != expected:
                lines.append(
                    f"ERROR: {manifest_path}: plugin digest mismatch under {published_root} "
                    f"(expected sha256-{expected}, tree hashes to sha256-{actual}) — run "
                    f"`uv run python -m tools bmt stage publish-plugin {project} {pname}`"
                )
                errors += 1

        elif manifest.plugin_ref.startswith("workspace:"):
            name = manifest.plugin_ref.split(":", 1)[1]
            ws = resolve_plugin_workspace_dir(stage_root, project, name)
            if not ws.is_dir():
                lines.append(f"ERROR: {manifest_path}: workspace missing: {ws}")
                errors += 1
            else:
                try:
                    load_plugin(stage_root, project, manifest.plugin_ref, allow_workspace=True)
                except (PluginLoadError, OSError, ValueError) as exc:
                    lines.append(f"ERROR: {manifest_path}: workspace plugin load failed: {exc}")
                    errors += 1
        else:
            lines.append(f"ERROR: {manifest_path}: unsupported plugin_ref {manifest.plugin_ref!r}")
            errors += 1

        if manifest.enabled and manifest.plugin_ref.startswith("workspace:"):
            lines.append(f"WARN: {manifest_path}: enabled BMT uses workspace: ref (CI/prod expects published:)")

    return (1 if errors else 0), lines
