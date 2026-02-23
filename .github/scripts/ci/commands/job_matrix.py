from __future__ import annotations

import json
from pathlib import Path

import click

from ci import config


@click.command("matrix")
@click.option("--config-root", default="remote", show_default=True)
@click.option("--project-filter", default="", envvar="BMT_PROJECTS")
@click.option("--output-key", default="matrix", show_default=True)
@click.option("--github-output", envvar="GITHUB_OUTPUT")
def command(
    config_root: str,
    project_filter: str,
    output_key: str,
    github_output: str | None,
) -> None:
    """Build matrix JSON from remote config."""
    matrix = config.build_matrix(Path(config_root), project_filter)
    if not matrix["include"]:
        raise RuntimeError("No enabled project+BMT rows found for CI matrix")
    if not github_output:
        raise RuntimeError("GITHUB_OUTPUT is required")
    with Path(github_output).open("a", encoding="utf-8") as fh:
        _ = fh.write(f"{output_key}={json.dumps(matrix, separators=(',', ':'))}\n")
    print(f"Built matrix rows: {len(matrix['include'])}")
