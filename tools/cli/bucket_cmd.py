"""GCS bucket operations."""

from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Annotated

import typer

from tools.repo.paths import TOOLS_SCRIPTS, repo_root
from tools.shared.bucket_env import bucket_from_env
from tools.shared.rich_minimal import step, step_console, success_panel

app = typer.Typer(no_args_is_help=True)


@app.command("verify-runtime-seed")
def verify_runtime_seed() -> None:
    """Verify runtime seed sync (manifest vs bucket)."""
    from tools.remote.bucket_verify_runtime_seed_sync import BucketVerifyRuntimeSeedSync

    bucket = bucket_from_env()
    rc = BucketVerifyRuntimeSeedSync().run(bucket=bucket)
    raise typer.Exit(rc)


@app.command()
def deploy() -> None:
    """Sync gcp/remote to bucket root and verify runtime seed."""
    from tools.remote.bucket_sync_runtime_seed import BucketSyncRuntimeSeed
    from tools.remote.bucket_verify_runtime_seed_sync import BucketVerifyRuntimeSeedSync

    bucket = bucket_from_env()
    console = step_console()
    if console is not None:
        console.print("[bold]Deploy[/]")
    steps: list[tuple[str, object]] = [
        ("Sync runtime seed", BucketSyncRuntimeSeed()),
        ("Verify runtime seed", BucketVerifyRuntimeSeedSync()),
    ]
    for label, runner in steps:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = runner.run(bucket=bucket)  # type: ignore[union-attr]
        if rc != 0:
            if buf.getvalue():
                sys.stderr.write(buf.getvalue())
            step(console, label, ok=False)
            raise typer.Exit(rc)
        step(console, label, ok=True)
    success_panel(console, "Deploy", "Runtime seed synced and verified.")
    raise typer.Exit(0)


@app.command()
def preflight(
    report: Annotated[
        Path | None,
        typer.Option("--report", help="Path to saved preflight report (.txt); skips shell script"),
    ] = None,
    local_only: Annotated[
        bool,
        typer.Option("--local-only", help="Only list gcp/image, no gcloud"),
    ] = False,
) -> None:
    """Bucket diff report (saved to .local/preflight-bucket-*.txt)."""
    console = step_console()
    if report is not None or local_only:
        script_path = repo_root() / "tools" / "scripts" / "preflight_bucket_vs_remote.py"
        cmd = [sys.executable, str(script_path)]
        if report is not None:
            cmd.extend(["--report", str(report)])
        if local_only:
            cmd.append("--local-only")
        rc = subprocess.run(cmd, check=False, cwd=repo_root()).returncode
        step(console, "Preflight", ok=(rc == 0))
        if rc == 0:
            success_panel(console, "Preflight", "Bucket vs image check passed.")
        raise typer.Exit(rc)
    if console is not None:
        console.print("[bold]Preflight[/]")
    script = repo_root() / TOOLS_SCRIPTS / "run_preflight_bucket.sh"
    rc = subprocess.run(
        ["bash", str(script)],
        check=False,
        cwd=repo_root(),
    ).returncode
    step(console, "Preflight", ok=(rc == 0))
    if rc == 0:
        success_panel(console, "Preflight", "Bucket preflight passed.")
    raise typer.Exit(rc)


@app.command("clean-bloat")
def clean_bloat(
    execute: Annotated[
        bool,
        typer.Option("--execute", help="Actually delete (default is dry-run)"),
    ] = False,
) -> None:
    """Remove Python/uv bloat from GCS bucket."""
    from tools.remote.bucket_clean_bloat import BucketCleanBloat

    bucket = bucket_from_env()
    console = step_console()
    if console is not None:
        console.print("[bold]Clean bloat[/]")
    rc = BucketCleanBloat().run(bucket=bucket, dry_run=not execute)
    step(console, "Clean bloat", ok=(rc == 0))
    if rc == 0:
        success_panel(console, "Clean bloat", "Done (see above for details).", style="blue")
    raise typer.Exit(rc)


@app.command("upload-runner")
def upload_runner(
    runner_path: Annotated[
        Path | None,
        typer.Option("--runner-path", help="Path to runner binary; default from BMT_RUNNER_PATH or sk default"),
    ] = None,
    runner_uri: Annotated[
        str | None,
        typer.Option("--runner-uri", help="GCS object path; default from BMT_RUNNER_URI or sk default"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Upload even if size matches existing"),
    ] = False,
) -> None:
    """Upload runner binary with previous-version rotation and metadata."""
    import os

    from tools.remote.bucket_upload_runner import BucketUploadRunner

    bucket = bucket_from_env()
    path = runner_path or (
        (os.environ.get("BMT_RUNNER_PATH") or "").strip() or "repo/staging/runners/sk_gcc_release/kardome_runner"
    )
    uri = runner_uri or ((os.environ.get("BMT_RUNNER_URI") or "").strip() or "sk/runners/sk_gcc_release/kardome_runner")
    source = (os.environ.get("BMT_SOURCE") or "").strip() or "sandbox_manual"
    source_ref = (os.environ.get("SOURCE_REF") or "").strip()
    rc = BucketUploadRunner().run(
        bucket=bucket,
        runner_path=path,
        runner_uri=uri,
        source=source,
        source_ref=source_ref,
        force=force,
    )
    raise typer.Exit(rc)


@app.command("upload-dataset")
def upload_dataset(
    project: Annotated[
        str,
        typer.Argument(help="Project name (e.g. sk)"),
    ],
    source: Annotated[
        Path,
        typer.Argument(help="Path to a .zip archive or a folder containing WAV files"),
    ],
    dataset_name: Annotated[
        str | None,
        typer.Option("--dataset", help="Dataset name override (auto-detected from source if omitted)"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-upload even if GCS already matches"),
    ] = False,
    no_local: Annotated[
        bool,
        typer.Option("--no-local", help="Skip syncing to gcp/remote/"),
    ] = False,
) -> None:
    """Upload a WAV dataset (zip or folder) to projects/<project>/inputs/<dataset>/.

    Also mirrors the files into gcp/remote/ so the local bucket mirror stays
    current (pass --no-local to skip). Dataset name is auto-detected from the
    source filename when not given: sk_false_rejects.zip → false_rejects.
    """
    from tools.remote.bucket_upload_dataset import BucketUploadDataset
    from tools.repo.paths import repo_root

    bucket = bucket_from_env()
    local_mirror = None if no_local else repo_root() / "gcp" / "remote"
    rc = BucketUploadDataset().run(
        bucket=bucket,
        project=project,
        source=source,
        dataset_name=dataset_name,
        force=force,
        local_mirror=local_mirror,
    )
    raise typer.Exit(rc)


@app.command("upload-wavs")
def upload_wavs(
    source_dir: Annotated[
        Path,
        typer.Option("--source-dir", help="Local directory or archive to upload"),
    ] = ...,
    dest_prefix: Annotated[
        str,
        typer.Option("--dest-prefix", help="GCS prefix under bucket runtime/"),
    ] = "sk/inputs/false_rejects",
    force: Annotated[
        bool,
        typer.Option("--force", help="Upload even if count/size matches"),
    ] = False,
) -> None:
    """Upload WAV dataset tree (or archive) to bucket inputs prefix."""
    from tools.remote.bucket_upload_wavs import BucketUploadWavs

    bucket = bucket_from_env()
    rc = BucketUploadWavs().run(
        bucket=bucket,
        source_dir=source_dir,
        dest_prefix=dest_prefix,
        force=force,
    )
    raise typer.Exit(rc)


@app.command("validate-contract")
def validate_contract(
    require_runner: Annotated[
        bool,
        typer.Option("--require-runner", help="Require runner binary to exist"),
    ] = False,
) -> None:
    """Validate bucket contract (current.json, snapshots, optional runner)."""
    from tools.remote.bucket_validate_contract import BucketValidateContract

    bucket = bucket_from_env()
    rc = BucketValidateContract().run(bucket=bucket, require_runner=require_runner)
    raise typer.Exit(rc)
