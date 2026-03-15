"""Unified CLI for bmt-gcloud dev tools. Run: uv run python -m tools --help"""
from __future__ import annotations

import typer

app = typer.Typer(
    name="tools",
    help="bmt-gcloud dev tools. Run any subcommand with --help for details.",
    no_args_is_help=True,
)


def main() -> None:
    from tools.cli.bucket_cmd import app as bucket_app
    from tools.cli.terraform_cmd import app as terraform_app
    from tools.cli.repo_cmd import app as repo_app
    from tools.cli.build_cmd import app as build_app
    from tools.cli.bmt_cmd import app as bmt_app

    app.add_typer(bucket_app, name="bucket", help="GCS bucket operations")
    app.add_typer(terraform_app, name="terraform", help="Infrastructure management")
    app.add_typer(repo_app, name="repo", help="Repository validation and env")
    app.add_typer(build_app, name="build", help="VM image build")
    app.add_typer(bmt_app, name="bmt", help="BMT execution and monitoring")

    app()


if __name__ == "__main__":
    main()
