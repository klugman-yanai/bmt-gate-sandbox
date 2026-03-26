"""Unified ``tools add`` for project + optional BMT + optional dataset upload."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from tools.bmt.contributor_add import run_contributor_add


def register_add_command(target: typer.Typer) -> None:
    """Register ``add`` on the root tools CLI."""

    @target.command("add", rich_help_panel="Contributor")
    def add_command(
        project: Annotated[
            str,
            typer.Argument(
                help="Project name (folder under benchmarks/projects/). "
                "With no flags, creates the scaffold only if it does not exist yet."
            ),
        ],
        bmt: Annotated[
            str | None,
            typer.Option(
                "--bmt",
                help="Benchmark folder under bmts/<name>/ (same as bmt_slug in bmt.json).",
            ),
        ] = None,
        data: Annotated[
            Path | None,
            typer.Option(
                "--data",
                help="WAV dataset: directory of *.wav, .zip, or .tar/.tar.gz/.tgz (7z: extract first).",
            ),
        ] = None,
        dataset: Annotated[
            str | None,
            typer.Option(
                "--dataset",
                help="GCS inputs/<dataset>/ name; default: --bmt if set, else inferred from --data path.",
            ),
        ] = None,
        upload_local: Annotated[
            bool,
            typer.Option(
                "--local",
                help="Also mirror uploaded WAVs into benchmarks/ (off by default; datasets can be huge).",
            ),
        ] = False,
        force: Annotated[
            bool,
            typer.Option("--force", help="Re-upload even if GCS already matches."),
        ] = False,
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", help="Print what would happen (no writes, no upload)."),
        ] = False,
    ) -> None:
        """Create a project, optionally add a BMT manifest, optionally upload a dataset.

        Examples:

            just add sk

            just add sk --bmt=false_alarms

            just add sk --data ./audio.zip

            just add sk --bmt=false_alarms --data ./corpus.tar.gz --dataset=false_alarms
        """
        rc = run_contributor_add(
            project=project,
            bmt=bmt,
            data=data,
            dataset=dataset,
            upload_local_mirror=upload_local,
            upload_force=force,
            dry_run=dry_run,
        )
        raise typer.Exit(rc)
