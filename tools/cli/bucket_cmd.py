"""GCS bucket operations."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from tools.repo.paths import repo_root, TOOLS_SCRIPTS
from tools.shared.bucket_env import bucket_from_env

app = typer.Typer(no_args_is_help=True)




@app.command()
def deploy() -> None:
    """Sync gcp/image to bucket and verify code + runtime seed."""
    from tools.remote.bucket_sync_gcp import BucketSyncGcp
    from tools.remote.bucket_verify_gcp_sync import BucketVerifyGcpSync
    from tools.remote.bucket_verify_runtime_seed_sync import BucketVerifyRuntimeSeedSync

    bucket = bucket_from_env()
    for cls in (BucketSyncGcp, BucketVerifyGcpSync, BucketVerifyRuntimeSeedSync):
        rc = cls().run(bucket=bucket)
        if rc != 0:
            raise typer.Exit(rc)


@app.command()
def preflight() -> None:
    """Bucket diff report (saved to .local/preflight-bucket-*.txt)."""
    import subprocess

    script = repo_root() / TOOLS_SCRIPTS / "run_preflight_bucket.sh"
    rc = subprocess.run(
        ["bash", str(script)],
        check=False,
        cwd=repo_root(),
    ).returncode
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
    rc = BucketCleanBloat().run(bucket=bucket, dry_run=not execute)
    raise typer.Exit(rc)
