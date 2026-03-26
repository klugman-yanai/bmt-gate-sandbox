"""Top-level Typer commands for maintainers (release bundle, local act, bucket lifecycle).

Contributors use `just` for day-to-day work; `just tools` is the full CLI including these.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from tools.repo.paths import repo_root

_PANEL = "Maintainer"


def register_maintainer_commands(target: typer.Typer) -> None:
    """Register maintainer-only commands on the root ``tools`` app."""

    @target.command("doctor", rich_help_panel=_PANEL)
    def doctor_cmd() -> None:
        """Vulture + pylint duplicate-code on env-related paths (includes gcp/image/config)."""
        repo = repo_root()
        for args in (
            [
                "uv",
                "run",
                "vulture",
                "gcp/image/config",
                "tools/shared/env.py",
                "tools/shared/bucket_env.py",
                "--min-confidence",
                "80",
            ],
            [
                "uv",
                "run",
                "pylint",
                "--disable=all",
                "--enable=duplicate-code",
                "--min-similarity-lines=6",
                "gcp/image/config/env_parse.py",
                "tools/shared/env.py",
                "tools/shared/bucket_env.py",
                ".github/bmt/ci/workflow_dispatch.py",
            ],
        ):
            rc = subprocess.run(args, cwd=repo, check=False).returncode
            if rc != 0:
                raise typer.Exit(rc)

    @target.command("typecheck", rich_help_panel=_PANEL)
    def typecheck_cmd(
        section: Annotated[
            str,
            typer.Argument(help="all | ci | runtime | gcp | infra | tools | tests | stage"),
        ] = "all",
    ) -> None:
        """Run ``uv run ty check`` on CI, runtime, infra, tools, tests, or gcp/stage slices."""
        repo = repo_root()
        key = section.strip().lower()
        plans: list[tuple[str, str]]
        if key == "all":
            plans = [
                ("CI", ".github/bmt"),
                ("Runtime (gcp/image)", "gcp/image"),
                ("Infra", "infra"),
                ("Tools", "tools"),
                ("Tests", "tests"),
                ("Stage mirror", "gcp/stage"),
            ]
        elif key == "ci":
            plans = [("CI", ".github/bmt")]
        elif key in ("runtime", "gcp"):
            plans = [("Runtime (gcp/image)", "gcp/image")]
        elif key == "infra":
            plans = [("Infra", "infra")]
        elif key == "tools":
            plans = [("Tools", "tools")]
        elif key == "tests":
            plans = [("Tests", "tests")]
        elif key == "stage":
            plans = [("Stage mirror", "gcp/stage")]
        else:
            typer.echo(
                "error: unknown section; use: all | ci | runtime | infra | tools | tests | stage",
                err=True,
            )
            raise typer.Exit(1)

        for label, path in plans:
            typer.echo(f"\n==> ty check: {label} ({path})")
            rc = subprocess.run(["uv", "run", "ty", "check", path], cwd=repo, check=False).returncode
            if rc != 0:
                raise typer.Exit(rc)

    @target.command(
        "release",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
        rich_help_panel=_PANEL,
    )
    def release_cmd(ctx: typer.Context) -> None:
        """Build .github-release/ via scripts/assemble_release.py (extra CLI args are forwarded)."""
        repo = repo_root()
        script = repo / "scripts" / "assemble_release.py"
        rc = subprocess.run([sys.executable, str(script), *ctx.args], cwd=repo, check=False).returncode
        if rc != 0:
            raise typer.Exit(rc)
        typer.echo("Deploy: rsync .github-release/ → ~/kardome/core-main/.github/")

    @target.command("release-check", rich_help_panel=_PANEL)
    def release_check_cmd() -> None:
        """assemble_release --skip-secrets, verify bundle files, actionlint on bundled bmt-handoff.yml."""
        repo = repo_root()
        rc = subprocess.run(
            [sys.executable, str(repo / "scripts" / "assemble_release.py"), "--skip-secrets"],
            cwd=repo,
            check=False,
        ).returncode
        if rc != 0:
            raise typer.Exit(rc)

        bmt_release = repo / ".github-release" / "bmt_release.json"
        if not bmt_release.is_file():
            typer.echo("error: missing .github-release/bmt_release.json", err=True)
            raise typer.Exit(1)
        data = json.loads(bmt_release.read_text(encoding="utf-8"))
        sha = str(data.get("source_sha", ""))
        if len(sha) < 7:
            typer.echo("error: bmt_release.json source_sha too short", err=True)
            raise typer.Exit(1)

        handoff = repo / ".github-release" / "workflows" / "bmt-handoff.yml"
        if not handoff.is_file():
            typer.echo("error: missing .github-release/workflows/bmt-handoff.yml", err=True)
            raise typer.Exit(1)

        actionlint = shutil.which("actionlint")
        if not actionlint:
            typer.echo("error: actionlint not on PATH (https://github.com/rhysd/actionlint)", err=True)
            raise typer.Exit(1)
        rc = subprocess.run(
            [actionlint, "-config-file", ".github-release/actionlint.yaml", str(handoff)],
            cwd=repo,
            check=False,
        ).returncode
        if rc != 0:
            raise typer.Exit(rc)

    @target.command("set-lifecycle", rich_help_panel=_PANEL)
    def set_lifecycle_cmd() -> None:
        """Apply infra/lifecycle.json to the Pulumi stack bucket (gcloud storage buckets update)."""
        repo = repo_root()
        pulumi_dir = repo / "infra" / "pulumi"

        def _pulumi_output(key: str) -> str:
            p = subprocess.run(
                ["pulumi", "stack", "output", key],
                cwd=pulumi_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if p.returncode != 0:
                typer.echo(f"error: pulumi stack output {key}: {p.stderr.strip() or p.stdout}", err=True)
                raise typer.Exit(1)
            return p.stdout.strip()

        bucket = _pulumi_output("gcs_bucket")
        project = _pulumi_output("gcp_project")
        lifecycle = repo / "infra" / "lifecycle.json"
        if not lifecycle.is_file():
            typer.echo(f"error: missing {lifecycle}", err=True)
            raise typer.Exit(1)

        rc = subprocess.run(
            [
                "gcloud",
                "storage",
                "buckets",
                "update",
                f"gs://{bucket}",
                f"--lifecycle-file={lifecycle}",
                f"--project={project}",
            ],
            cwd=repo,
            check=False,
        ).returncode
        if rc != 0:
            raise typer.Exit(rc)

    @target.command("act", rich_help_panel=_PANEL)
    def act_cmd(
        workflow: Annotated[
            Path | None,
            typer.Option(
                "--workflow",
                "-W",
                help="Workflow file; default .github/workflows/build-and-test.yml",
            ),
        ] = None,
        var_file: Annotated[
            Path | None,
            typer.Option(
                "--var-file",
                help="Env file for act; default .env in repo root when the file exists",
            ),
        ] = None,
    ) -> None:
        """Run act workflow_dispatch (uses .env automatically when present)."""
        repo = repo_root()
        wf = workflow or (repo / ".github" / "workflows" / "build-and-test.yml")
        if not wf.is_file():
            typer.echo(f"error: workflow not found: {wf}", err=True)
            raise typer.Exit(1)

        act_bin = shutil.which("act")
        if not act_bin:
            typer.echo("error: act not on PATH (https://github.com/nektos/act)", err=True)
            raise typer.Exit(1)

        cmd: list[str] = [act_bin, "workflow_dispatch", "-W", str(wf)]
        vf = var_file
        if vf is None and (repo / ".env").is_file():
            vf = repo / ".env"
        if vf is not None:
            if not vf.is_file():
                typer.echo(f"error: --var-file not found: {vf}", err=True)
                raise typer.Exit(1)
            cmd.extend(["--var-file", str(vf)])

        rc = subprocess.run(cmd, cwd=repo, check=False).returncode
        raise typer.Exit(rc)
