"""Upload a project runner (kardome_runner + libKardome.so) to GCS."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import click

from ci.adapters import gcloud_cli
from ci.models import runtime_bucket_root_uri


@click.command("upload-runner")
@click.option("--bucket", required=True, envvar="GCS_BUCKET")
@click.option(
    "--runner-dir",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Directory containing kardome_runner (e.g. build/SK/gcc_Release/Runners)",
)
@click.option(
    "--lib-dir",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Directory containing libKardome.so (e.g. build/SK/gcc_Release/Kardome)",
)
@click.option("--project", required=True, help="Lowercased project name (e.g. sk)")
@click.option("--preset", required=True, help="Lowercased preset name (e.g. sk_gcc_release)")
@click.option("--source-ref", default="", help="Git SHA or ref")
def command(
    bucket: str,
    runner_dir: Path,
    lib_dir: Path | None,
    project: str,
    preset: str,
    source_ref: str,
) -> None:
    """Upload runner binary and project lib to GCS."""
    root = runtime_bucket_root_uri(bucket)
    dest_prefix = f"{project}/runners/{preset}"

    runner_binary = runner_dir / "kardome_runner"
    if not runner_binary.is_file():
        raise click.ClickException(f"kardome_runner not found in {runner_dir}")

    uploaded: list[dict[str, str | int]] = []

    # Upload kardome_runner
    runner_dest = f"{root}/{dest_prefix}/kardome_runner"
    rc, err = gcloud_cli.run_capture_retry(["gcloud", "storage", "cp", str(runner_binary), runner_dest, "--quiet"])
    if rc != 0:
        raise click.ClickException(f"Failed to upload kardome_runner: {err}")
    uploaded.append({"name": "kardome_runner", "size": runner_binary.stat().st_size})
    print(f"Uploaded kardome_runner -> {runner_dest}")

    # Upload libKardome.so if available
    lib_file: Path | None = None
    if lib_dir is not None:
        lib_file = lib_dir / "libKardome.so"
    if lib_file is not None and lib_file.is_file():
        lib_dest = f"{root}/{dest_prefix}/libKardome.so"
        rc, err = gcloud_cli.run_capture_retry(["gcloud", "storage", "cp", str(lib_file), lib_dest, "--quiet"])
        if rc != 0:
            raise click.ClickException(f"Failed to upload libKardome.so: {err}")
        uploaded.append({"name": "libKardome.so", "size": lib_file.stat().st_size})
        print(f"Uploaded libKardome.so -> {lib_dest}")

    # Write runner_meta.json
    meta = {
        "uploaded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_ref": source_ref,
        "project": project,
        "preset": preset,
        "files": uploaded,
    }
    with tempfile.TemporaryDirectory(prefix="runner_meta_") as tmp_dir:
        meta_path = Path(tmp_dir) / "runner_meta.json"
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        meta_dest = f"{root}/{dest_prefix}/runner_meta.json"
        rc, err = gcloud_cli.run_capture_retry(["gcloud", "storage", "cp", str(meta_path), meta_dest, "--quiet"])
        if rc != 0:
            raise click.ClickException(f"Failed to upload runner_meta.json: {err}")
    print(f"Uploaded runner_meta.json -> {meta_dest}")
    print(f"Runner upload complete: {len(uploaded)} file(s) for {project}/{preset}")
