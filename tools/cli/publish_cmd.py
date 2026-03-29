"""``tools publish`` — discover project/BMT or take explicit args; enables BMT by default."""

from __future__ import annotations

import os
from typing import Annotated

import typer

from tools.bmt.stage_bmts import iter_staged_bmts
from tools.repo.paths import DEFAULT_STAGE_ROOT, repo_root


def _resolve_publish_targets(
    project: str | None,
    benchmark: str | None,
) -> tuple[str, str]:
    stage_root = repo_root() / DEFAULT_STAGE_ROOT
    pairs = iter_staged_bmts(stage_root=stage_root)

    if project is not None and benchmark is not None:
        return project, benchmark

    if project is not None and benchmark is None:
        under = [p for p in pairs if p[0] == project]
        if len(under) == 1:
            return under[0]
        if not under:
            raise typer.BadParameter(f"No staged BMTs under project {project!r}.", param_hint="project")
        lines = "\n".join(f"  {p[0]}  {p[1]}" for p in under)
        raise typer.BadParameter(
            f"Project {project!r} has multiple BMTs; pass the benchmark folder too:\n{lines}",
            param_hint="benchmark",
        )

    if benchmark is not None:
        raise typer.BadParameter("Pass project name before benchmark folder.", param_hint="project")

    if len(pairs) == 1:
        return pairs[0]

    env_p = (os.environ.get("BMT_PROJECT") or "").strip()
    env_b = (os.environ.get("BMT_BENCHMARK") or "").strip()
    if env_p and env_b:
        return env_p, env_b

    if not pairs:
        raise typer.BadParameter(
            "No projects with bmts/*/bmt.json under benchmarks/projects/. Create one with `just add <project>` first.",
        )

    lines = "\n".join(f"  {p[0]}  {p[1]}" for p in pairs)
    raise typer.BadParameter(
        "Several BMTs are staged; pick one explicitly or set BMT_PROJECT and BMT_BENCHMARK.\n"
        f"Examples: `just publish sk false_rejects` or `just publish` when only one exists.\n"
        f"Staged pairs (project  benchmark folder):\n{lines}",
    )


def register_publish_command(target: typer.Typer) -> None:
    """Register ``publish`` on the root tools CLI."""

    @target.command("publish", rich_help_panel="Contributor")
    def publish_command(
        project: Annotated[
            str | None,
            typer.Argument(
                show_default=False,
                help="Project name. Omit when only one BMT exists, or set BMT_PROJECT + BMT_BENCHMARK.",
            ),
        ] = None,
        benchmark: Annotated[
            str | None,
            typer.Argument(
                show_default=False,
                help="Folder under bmts/ (same as bmt_slug). Omit if that project has only one BMT.",
            ),
        ] = None,
        no_sync: Annotated[
            bool,
            typer.Option("--no-sync", help="Publish locally only; do not sync the project subtree to GCS."),
        ] = False,
        no_enable: Annotated[
            bool,
            typer.Option("--no-enable", help="Do not set enabled: true in bmt.json (default is to enable)."),
        ] = False,
    ) -> None:
        """Build the plugin bundle, set enabled (unless --no-enable), and sync to GCS (unless --no-sync).

        Run ``just test-local`` and follow CONTRIBUTING.md (verify / publish) before publishing; see docs/contributors.md for manifest/SDK detail.
        """
        from tools.bmt.publisher import publish_bmt as publish_bmt_impl

        p, b = _resolve_publish_targets(project, benchmark)
        result = publish_bmt_impl(project=p, bmt_slug=b, sync=not no_sync, enable=not no_enable)
        typer.echo(result.plugin_ref)
        raise typer.Exit(0)
