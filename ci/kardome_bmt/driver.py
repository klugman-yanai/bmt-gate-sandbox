#!/usr/bin/env python3
"""BMT CI entrypoint (Typer)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from kardome_bmt import capability as capability_mod
from kardome_bmt import config, matrix
from kardome_bmt.actions import gh_error
from kardome_bmt.handoff import HandoffManager
from kardome_bmt.matrix import MatrixManager
from kardome_bmt.preset import PresetManager
from kardome_bmt.runner import RunnerManager
from kardome_bmt.workflow_dispatch import WorkflowDispatchManager

DEFAULT_PLUGINS_ROOT = Path("plugins/projects")
DEFAULT_PRESETS_FILE = Path("CMakePresets.json")

app = typer.Typer(
    no_args_is_help=True,
    help="BMT CI driver: matrix, runners, handoff, Workflows dispatch.",
)

meta_app = typer.Typer(help="Bootstrap helpers.")
app.add_typer(meta_app, name="meta")

matrix_app = typer.Typer(help="CMake preset matrix for CI and BMT.")
app.add_typer(matrix_app, name="matrix")

runner_app = typer.Typer(help="Runner artifacts and upload matrix.")
app.add_typer(runner_app, name="runner")

handoff_app = typer.Typer(help="Context file, status, and summaries.")
app.add_typer(handoff_app, name="handoff")

dispatch_app = typer.Typer(help="Google Workflows dispatch.")
app.add_typer(dispatch_app, name="dispatch")

preset_app = typer.Typer(help="Release preset staging.")
app.add_typer(preset_app, name="preset")


@meta_app.command("load-env")
def meta_load_env() -> None:
    """Write BmtConfig fields to GITHUB_ENV."""
    config.load_env()


@matrix_app.command("build")
def matrix_build() -> None:
    """Emit BMT matrix JSON to the ``matrix`` key in ``GITHUB_OUTPUT``."""
    MatrixManager.from_env().build()


@matrix_app.command("filter-supported")
def matrix_filter_supported() -> None:
    """Filter matrix to supported runner projects."""
    MatrixManager.from_env().filter_supported()


@matrix_app.command("parse-release-runners")
def matrix_parse_release_runners() -> None:
    """Parse CMakePresets for CI or BMT runner rows."""
    MatrixManager.from_env().parse_release_runners()


@matrix_app.command("capability")
def matrix_capability(
    plugins_root: Annotated[
        Path,
        typer.Option(
            "--plugins-root",
            help="Platform plugin directory (source of truth for supported projects).",
        ),
    ] = DEFAULT_PLUGINS_ROOT,
    platform_release: Annotated[
        str,
        typer.Option(
            "--platform-release",
            help="Platform release tag (e.g. bmt-v0.3.2). Falls back to $BMT_PLATFORM_RELEASE or 'dev'.",
        ),
    ] = "",
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write JSON to this path (otherwise stdout)."),
    ] = None,
    github_output_key: Annotated[
        str | None,
        typer.Option(
            "--github-output-key",
            help="If set and $GITHUB_OUTPUT is present, append key=<json>.",
        ),
    ] = None,
) -> None:
    """Emit the platform capability manifest (bmt.capability/v1).

    Single source of truth for "which projects can the BMT platform test?".
    Consumers call ``bmt matrix plan`` to project their CMakePresets onto it.
    """
    release = platform_release.strip() or os.environ.get("BMT_PLATFORM_RELEASE", "").strip() or "dev"
    matrix.emit_capability(
        plugins_root=plugins_root,
        platform_release=release,
        out=out,
        github_output_key=github_output_key,
    )


@matrix_app.command("plan")
def matrix_plan(
    presets: Annotated[
        Path,
        typer.Option(
            "--presets",
            help="Caller's CMakePresets.json to project onto the capability manifest.",
        ),
    ] = DEFAULT_PRESETS_FILE,
    capability: Annotated[
        Path | None,
        typer.Option(
            "--capability",
            help="Path to a capability manifest JSON. If omitted, --plugins-root is scanned live.",
        ),
    ] = None,
    plugins_root: Annotated[
        Path,
        typer.Option(
            "--plugins-root",
            help="Plugin directory (used only when --capability is not supplied).",
        ),
    ] = DEFAULT_PLUGINS_ROOT,
    platform_release: Annotated[
        str,
        typer.Option(
            "--platform-release",
            help="Platform release tag recorded in plan output (when scanning live).",
        ),
    ] = "",
    commit: Annotated[
        str,
        typer.Option("--commit", help="Caller commit SHA to embed in the plan."),
    ] = "",
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write JSON to this path (otherwise stdout)."),
    ] = None,
    github_output_key: Annotated[
        str | None,
        typer.Option(
            "--github-output-key",
            help="If set and $GITHUB_OUTPUT is present, append key=<json>.",
        ),
    ] = None,
) -> None:
    """Project caller presets onto capability → 3-bucket build plan (bmt.plan/v1).

    Buckets:
      * ``publish``      — host-release presets whose project has a BMT plugin.
      * ``acknowledged`` — host-release presets with no platform plugin.
      * ``nonrelease``   — debug, cross-compile, and other non-release presets.
    """
    release = platform_release.strip() or os.environ.get("BMT_PLATFORM_RELEASE", "").strip() or "dev"
    capability_source: capability_mod.CapabilityManifest | Path = (
        capability if capability is not None else capability_mod.build_capability_manifest(plugins_root, release)
    )
    matrix.emit_plan(
        presets_file=presets,
        capability_source=capability_source,
        commit=commit.strip() or None,
        out=out,
        github_output_key=github_output_key,
    )


@runner_app.command("upload")
def runner_upload() -> None:
    """Upload runner binaries to GCS."""
    RunnerManager.from_env().upload()


@runner_app.command("filter-upload-matrix")
def runner_filter_upload_matrix() -> None:
    """Compute matrix_need_upload from context and GCS."""
    RunnerManager.from_env().filter_upload_matrix()


@runner_app.command("upload-to-gcs")
def runner_upload_to_gcs() -> None:
    """chmod + upload runner from artifact/Runners."""
    RunnerManager.from_env().upload_runner_to_gcs()


@runner_app.command("validate-in-repo")
def runner_validate_in_repo() -> None:
    """Validate runner exists in bucket or stage mirror."""
    RunnerManager.from_env().validate_in_repo()


@runner_app.command("resolve-uploaded-projects")
def runner_resolve_uploaded_projects() -> None:
    """Resolve accepted_projects from upload markers."""
    RunnerManager.from_env().resolve_uploaded_projects()


@runner_app.command("summarize-handshake")
def runner_summarize_handshake() -> None:
    """Log matrix handshake line."""
    RunnerManager.from_env().summarize_matrix_handshake()


@handoff_app.command("write-context")
def handoff_write_context() -> None:
    """Serialize BmtContext to .bmt/context.json."""
    HandoffManager.from_env().write_context()


@handoff_app.command("resolve-failure-context")
def handoff_resolve_failure_context() -> None:
    """Emit mode/head_sha/pr_number for failure fallback."""
    HandoffManager.from_env().resolve_failure_context()


@handoff_app.command("post-pending-status")
def handoff_post_pending_status() -> None:
    """Post pending commit status for BMT."""
    HandoffManager.from_env().post_pending_status()


@handoff_app.command("post-timeout-status")
def handoff_post_timeout_status() -> None:
    """Post error commit status on handoff timeout."""
    HandoffManager.from_env().post_handoff_timeout_status()


@handoff_app.command("validate-dataset-inputs")
def handoff_validate_dataset_inputs() -> None:
    """Validate .wav inputs in GCS for accepted BMTs."""
    HandoffManager.from_env().validate_dataset_inputs()


@handoff_app.command("write-summary")
def handoff_write_summary() -> None:
    """Append Markdown to GITHUB_STEP_SUMMARY."""
    HandoffManager.from_env().write_summary()


@dispatch_app.command("invoke-workflow")
def dispatch_invoke_workflow() -> None:
    """Start Google Workflow execution for BMT handoff."""
    WorkflowDispatchManager.from_env().invoke()


@preset_app.command("stage-release-runner")
def preset_stage_release_runner() -> None:
    """Stage release runner paths for upload job."""
    PresetManager.from_env().stage_release_runner()


@preset_app.command("compute-info")
def preset_compute_info() -> None:
    """Compute preset binary dir for GITHUB_OUTPUT."""
    PresetManager.from_env().compute_preset_info()


def main() -> None:
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:
        gh_error(str(exc))
        sys.exit(1)


def main_matrix() -> None:
    MatrixManager.from_env().build()


def main_write_context() -> None:
    HandoffManager.from_env().write_context()


def main_write_handoff_summary() -> None:
    HandoffManager.from_env().write_summary()


if __name__ == "__main__":
    main()
