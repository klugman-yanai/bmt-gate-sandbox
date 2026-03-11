#!/usr/bin/env python3
"""Validate pinned uv release metadata, digest alignment, and Ubuntu 22.04 compatibility."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click
from click_exit import run_click_command

from repo_paths import DEFAULT_CONFIG_ROOT
from uv_pin import fetch_pinned_uv_binary, read_pinned_binary_sha, read_release_spec

UV_CHECKSUM_REL = "_tools/uv/linux-x86_64/uv.sha256"
UV_RELEASE_SPEC_REL = "_tools/uv/linux-x86_64/uv.release.json"


@click.command()
@click.option("--src-dir", default=DEFAULT_CONFIG_ROOT, help="Source deploy/code directory")
def main(src_dir: str) -> int:
    src = Path(src_dir)
    if not src.is_dir():
        click.echo(f"::error::Missing source directory: {src}", err=True)
        return 1

    expected_binary_sha = read_pinned_binary_sha(src / UV_CHECKSUM_REL, filename="uv")
    spec = read_release_spec(src / UV_RELEASE_SPEC_REL)
    if spec.binary_sha256 != expected_binary_sha:
        click.echo(
            "::error::uv pin mismatch between uv.sha256 and uv.release.json "
            f"({expected_binary_sha} != {spec.binary_sha256})",
            err=True,
        )
        return 1

    with tempfile.TemporaryDirectory(prefix="validate_uv_pin_") as tmp_dir:
        uv_bin = fetch_pinned_uv_binary(spec, Path(tmp_dir))
        click.echo(f"Validated pinned uv binary: {uv_bin}")
    click.echo(
        "Pinned uv metadata valid and Ubuntu 22.04 compatible: "
        f"version={spec.version} sha={spec.binary_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

