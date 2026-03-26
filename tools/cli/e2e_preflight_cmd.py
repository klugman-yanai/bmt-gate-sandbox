"""E2E readiness gate: `tools e2e-preflight` or `just workspace e2e` / `tools workspace e2e`."""

from __future__ import annotations

from typing import Annotated

import typer

from tools.repo.e2e_preflight import run_e2e_preflight


def register_e2e_preflight(root: typer.Typer) -> None:
    @root.command(
        name="e2e-preflight",
        rich_help_panel="Pre-push",
    )
    def e2e_preflight_command(
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", help="Show planned stages only; do not run checks."),
        ] = False,
        skip_bucket: Annotated[
            bool,
            typer.Option(
                "--skip-bucket",
                help="Skip `just workspace preflight` (GCS + drift); use when offline.",
            ),
        ] = False,
        with_tests: Annotated[
            bool,
            typer.Option(
                "--with-tests",
                help="After earlier stages, run full `just test` (pytest, ruff, ty, actionlint, …).",
            ),
        ] = False,
    ) -> None:
        """Staged checks for Actions/handoff readiness; on failure suggests a fix (e.g. `just tools ship`)."""
        rc = run_e2e_preflight(
            skip_bucket=skip_bucket,
            with_tests=with_tests,
            dry_run=dry_run,
        )
        raise typer.Exit(rc)
