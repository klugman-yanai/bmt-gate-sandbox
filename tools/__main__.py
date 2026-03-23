"""Unified CLI for bmt-gcloud dev tools. Run: uv run python -m tools --help"""

from __future__ import annotations

from dataclasses import dataclass

import typer


@dataclass
class _SubcommandRegistration:
    """Process-wide flag: ``register_subcommands`` attached to the CLI (mutate ``.done``, no ``global``)."""

    done: bool = False


_registration = _SubcommandRegistration()

app = typer.Typer(
    name="tools",
    help="bmt-gcloud dev tools. Run any subcommand with [bold]--help[/bold] for details.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def register_subcommands(target: typer.Typer) -> None:
    """Attach all subcommand groups to ``target`` (idempotent: second call in-process is a no-op)."""
    if _registration.done:
        return
    from tools.cli.bmt_cmd import app as bmt_app
    from tools.cli.bucket_cmd import app as bucket_app
    from tools.cli.build_cmd import app as build_app
    from tools.cli.e2e_preflight_cmd import register_e2e_preflight
    from tools.cli.onboard_cmd import register_onboard
    from tools.cli.pulumi_cmd import app as pulumi_app
    from tools.cli.repo_cmd import app as repo_app
    from tools.cli.ship_cmd import register_ship
    from tools.cli.workspace_cmd import register_workspace

    register_onboard(target)
    register_ship(target)
    register_e2e_preflight(target)
    register_workspace(target)
    target.add_typer(bucket_app, name="bucket", help="GCS bucket operations", rich_help_panel="Storage & deploy")
    target.add_typer(
        pulumi_app, name="pulumi", help="Infrastructure management (Pulumi)", rich_help_panel="Infrastructure"
    )
    target.add_typer(repo_app, name="repo", help="Repository validation and env", rich_help_panel="Repo & config")
    target.add_typer(build_app, name="build", help="Container image build", rich_help_panel="Infrastructure")
    target.add_typer(
        bmt_app,
        name="bmt",
        help="Staged BMT projects: [bold]bmt stage[/bold] (project · bmt · publish), symlink-deps",
        rich_help_panel="BMT",
    )

    _registration.done = True


def main() -> None:
    register_subcommands(app)
    app()


if __name__ == "__main__":
    main()
