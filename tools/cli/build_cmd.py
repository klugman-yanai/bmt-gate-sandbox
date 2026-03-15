"""VM image build orchestration (extracted from Justfile bash)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Annotated

import typer

from tools.repo.paths import repo_root
from tools.shared.rich_minimal import step_console, success_panel

app = typer.Typer(no_args_is_help=True)

PACKER_TEMPLATE = "infra/packer/bmt-runtime.pkr.hcl"  # relative to repo root
IMAGE_BUILD_WORKFLOW = "ops/trigger-image-build.yml"


def _repo_slug() -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=True,
        cwd=repo_root(),
    )
    url = result.stdout.strip()
    for prefix in ("https://github.com/", "git@github.com:"):
        if url.startswith(prefix):
            return url[len(prefix) :].removesuffix(".git")
    raise typer.BadParameter(f"Cannot parse repo slug from: {url}")


def _current_branch() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        cwd=repo_root(),
    ).stdout.strip()


def _echo_dispatch(branch: str, repo: str) -> None:
    msg = f"Dispatching image build from branch: [bold]{branch}[/bold] (repo: [bold]{repo}[/bold])"
    if sys.stdout.isatty():
        try:
            from rich.console import Console
            from rich.panel import Panel

            Console().print(Panel(msg, title="build image", border_style="blue"))
        except ImportError:
            typer.echo(msg.replace("[bold]", "").replace("[/bold]", ""))
    else:
        typer.echo(f"Dispatching image build from branch: {branch} (repo: {repo})")


def _run_packer_validate() -> int:
    return subprocess.run(
        [
            "packer",
            "validate",
            "-var",
            "gcp_project=dry-run",
            "-var",
            "gcp_zone=europe-west4-a",
            "-var",
            "gcs_bucket=dry-run",
            PACKER_TEMPLATE,
        ],
        check=False,
        cwd=repo_root(),
    ).returncode


def _dispatch_workflow(repo: str, branch: str) -> None:
    # --ref makes GitHub use the trigger workflow file from this branch (no need for it on default).
    # Pass branch input when the workflow accepts it; if target has older workflow (no inputs), retry without -f.
    args = [
        "gh",
        "workflow",
        "run",
        IMAGE_BUILD_WORKFLOW,
        "--repo",
        repo,
        "--ref",
        branch,
        "-f",
        f"branch={branch}",
    ]
    result = subprocess.run(args, check=False, capture_output=True, text=True, cwd=repo_root())
    if result.returncode != 0 and "422" in result.stderr and "Unexpected inputs" in result.stderr:
        # Target repo's workflow doesn't declare branch input; dispatch without -f (workflow uses github.ref_name).
        result = subprocess.run(
            [
                "gh",
                "workflow",
                "run",
                IMAGE_BUILD_WORKFLOW,
                "--repo",
                repo,
                "--ref",
                branch,
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root(),
        )
    if result.returncode != 0:
        if result.stderr:
            typer.echo(result.stderr.strip(), err=True)
        typer.echo(
            "Trigger failed. Ensure .github/workflows/trigger-image-build.yml exists on this branch in the target repo "
            "and accepts a 'branch' input (or omit inputs). Use --skip-image to run Pulumi only.",
            err=True,
        )
        raise typer.Exit(1)


def _dispatch_and_wait(repo: str, branch: str) -> int:
    _dispatch_workflow(repo, branch)
    if sys.stdout.isatty():
        try:
            from rich.console import Console
            from rich.panel import Panel

            Console().print(Panel("Waiting for image build to complete...", border_style="blue"))
        except ImportError:
            typer.echo("Waiting for image build to complete...")
    else:
        typer.echo("Waiting for image build to complete...")
    time.sleep(5)
    run_id_result = subprocess.run(
        [
            "gh",
            "run",
            "list",
            f"--workflow={IMAGE_BUILD_WORKFLOW}",
            "--repo",
            repo,
            "--branch",
            branch,
            "--limit",
            "1",
            "--json",
            "databaseId",
            "-q",
            ".[0].databaseId",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=repo_root(),
    )
    run_id = run_id_result.stdout.strip()
    return subprocess.run(
        ["gh", "run", "watch", run_id, "--repo", repo, "--exit-status"],
        check=False,
        cwd=repo_root(),
    ).returncode


def _run_pulumi() -> int:
    for mod in ("tools.pulumi.pulumi_preflight", "tools.pulumi.pulumi_apply"):
        rc = subprocess.run(
            [sys.executable, "-m", mod],
            check=False,
            cwd=repo_root(),
        ).returncode
        if rc != 0:
            return rc
    return 0


@app.command("packer-validate")
def packer_validate() -> None:
    """Validate Packer template (no GCP credentials needed)."""
    console = step_console()
    rc = _run_packer_validate()
    if rc == 0:
        success_panel(console, "Packer", "Template valid.")
    raise typer.Exit(rc)


@app.command()
def image(
    branch: Annotated[str, typer.Option(help="Git branch to build from")] = "",
    repo: Annotated[
        str,
        typer.Option(
            "--repo",
            help="GitHub repo (owner/name) to dispatch to; default from git origin. Set BMT_BUILD_REPO to override.",
        ),
    ] = "",
    no_wait: Annotated[
        bool,
        typer.Option("--no-wait", help="Dispatch build and return immediately"),
    ] = False,
    skip_image: Annotated[
        bool,
        typer.Option("--skip-image", help="Skip image build, run Pulumi only"),
    ] = False,
    infra: Annotated[
        bool,
        typer.Option("--infra", help="Run Pulumi after image build"),
    ] = False,
) -> None:
    """Build VM image, optionally run Pulumi after."""
    branch = branch or _current_branch()
    repo = (repo or os.environ.get("BMT_BUILD_REPO") or "").strip() or _repo_slug()

    if skip_image:
        rc = _run_pulumi()
        raise typer.Exit(rc)

    if no_wait:
        _echo_dispatch(branch, repo)
        _dispatch_workflow(repo, branch)
        raise typer.Exit(0)

    rc = _run_packer_validate()
    if rc != 0:
        raise typer.Exit(rc)

    _echo_dispatch(branch, repo)
    rc = _dispatch_and_wait(repo, branch)
    if rc != 0:
        raise typer.Exit(rc)
    console = step_console()
    if console is not None:
        success_panel(console, "Build", "Image build completed.")

    if infra:
        rc = _run_pulumi()
        raise typer.Exit(rc)
