"""Unified CLI for bmt-gcloud dev tools. Run: uv run python -m tools --help"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="tools",
    help="bmt-gcloud dev tools. Run any subcommand with [bold]--help[/bold] for details.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def main() -> None:
    from tools.cli.bmt_cmd import app as bmt_app
    from tools.cli.bucket_cmd import app as bucket_app
    from tools.cli.build_cmd import app as build_app
    from tools.cli.pulumi_cmd import app as pulumi_app
    from tools.cli.repo_cmd import app as repo_app

    app.add_typer(bucket_app, name="bucket", help="GCS bucket operations", rich_help_panel="Storage & deploy")
    app.add_typer(
        pulumi_app, name="pulumi", help="Infrastructure management (Pulumi)", rich_help_panel="Infrastructure"
    )
    app.add_typer(repo_app, name="repo", help="Repository validation and env", rich_help_panel="Repo & config")
    app.add_typer(build_app, name="build", help="Container image build", rich_help_panel="Infrastructure")
    app.add_typer(bmt_app, name="bmt", help="BMT execution and scaffolding", rich_help_panel="BMT")

    app()


if __name__ == "__main__":
    main()
