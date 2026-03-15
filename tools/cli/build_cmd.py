"""VM image build orchestration (extracted from Justfile bash)."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from tools.repo.paths import repo_root

app = typer.Typer(no_args_is_help=True)

PACKER_TEMPLATE = "infra/packer/bmt-runtime.pkr.hcl"  # relative to repo root
IMAGE_BUILD_WORKFLOW = "trigger-image-build.yml"




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
            "and accepts a 'branch' input (or omit inputs). Use --skip-image to run terraform only.",
            err=True,
        )
        raise typer.Exit(1)


def _dispatch_and_wait(repo: str, branch: str) -> int:
    _dispatch_workflow(repo, branch)
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


def _run_terraform() -> int:
    for mod in ("tools.terraform.terraform_preflight", "tools.terraform.terraform_apply"):
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
    rc = _run_packer_validate()
    raise typer.Exit(rc)


@app.command()
def image(
    branch: Annotated[
        str, typer.Option(help="Git branch to build from")
    ] = "",
    no_wait: Annotated[
        bool,
        typer.Option("--no-wait", help="Dispatch build and return immediately"),
    ] = False,
    skip_image: Annotated[
        bool,
        typer.Option("--skip-image", help="Skip image build, run terraform only"),
    ] = False,
    infra: Annotated[
        bool,
        typer.Option("--infra", help="Run terraform after image build"),
    ] = False,
) -> None:
    """Build VM image, optionally run terraform after."""
    branch = branch or _current_branch()
    repo = _repo_slug()

    if skip_image:
        rc = _run_terraform()
        raise typer.Exit(rc)

    if no_wait:
        typer.echo(f"Dispatching image build from branch: {branch} (repo: {repo})")
        _dispatch_workflow(repo, branch)
        raise typer.Exit(0)

    rc = _run_packer_validate()
    if rc != 0:
        raise typer.Exit(rc)

    typer.echo(f"Dispatching image build from branch: {branch} (repo: {repo})")
    rc = _dispatch_and_wait(repo, branch)
    if rc != 0:
        raise typer.Exit(rc)

    if infra:
        rc = _run_terraform()
        raise typer.Exit(rc)
