"""CLI commands for the release marker (``bmt release …`` subgroup).

These commands are invoked from ``.github/workflows/release.yml`` (to write
the marker) and from ``.github/workflows/bmt-handoff.yml`` (to assert a commit's
cloud artifacts were produced by a completed ``release.yml`` run).

The commands live in the PEX so they are equally available to this repo's CI
and to consumer repos (e.g. ``Kardome-org/core-main``) that import the BMT
handoff as a reusable workflow.
"""

from __future__ import annotations

import os
from typing import Annotated

import typer
from whenever import Instant

from kardome_bmt import release_marker
from kardome_bmt.release_marker import ReleaseMarker, ReleaseMarkerMismatchError

app = typer.Typer(
    no_args_is_help=True,
    help="Release marker operations (write/verify gs://$BUCKET/_state/release.json).",
)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise typer.BadParameter(f"{name} is not set; required for this command.", param_hint=name)
    return value


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


@app.command("mark")
def mark(
    bucket: Annotated[
        str | None,
        typer.Option("--bucket", "-b", help="GCS bucket (defaults to $GCS_BUCKET)."),
    ] = None,
    git_sha: Annotated[
        str | None,
        typer.Option("--git-sha", help="Git SHA (defaults to $GITHUB_SHA)."),
    ] = None,
    image_digest: Annotated[
        str | None,
        typer.Option(
            "--image-digest",
            help="Cloud Run manifest digest (sha256:…); defaults to $RELEASE_IMAGE_DIGEST, empty if skipped.",
        ),
    ] = None,
    plugins_sha: Annotated[
        str | None,
        typer.Option(
            "--plugins-sha",
            help="Plugins tree hash; defaults to $RELEASE_PLUGINS_SHA, empty if skipped.",
        ),
    ] = None,
    pex_tag: Annotated[
        str | None,
        typer.Option("--pex-tag", help="PEX release tag (bmt-vX.Y.Z); defaults to $RELEASE_PEX_TAG."),
    ] = None,
    pulumi_stack_sha: Annotated[
        str | None,
        typer.Option(
            "--pulumi-stack-sha",
            help="Pulumi stack export hash; defaults to $RELEASE_PULUMI_STACK_SHA, empty if skipped.",
        ),
    ] = None,
) -> None:
    """Write ``gs://$BUCKET/_state/release.json`` for the current release.

    All four surface fields are optional — missing values indicate the
    corresponding ``release.yml`` step was skipped (path-filtered) and no
    previous value was carried forward. The ``git_sha`` is mandatory because
    the marker's whole purpose is to anchor a specific commit.
    """
    bucket_name = bucket or _require_env("GCS_BUCKET")
    sha = git_sha or _require_env("GITHUB_SHA")

    marker = ReleaseMarker(
        git_sha=sha,
        image_digest=image_digest if image_digest is not None else _optional_env("RELEASE_IMAGE_DIGEST"),
        plugins_sha=plugins_sha if plugins_sha is not None else _optional_env("RELEASE_PLUGINS_SHA"),
        pex_tag=pex_tag if pex_tag is not None else _optional_env("RELEASE_PEX_TAG"),
        pulumi_stack_sha=pulumi_stack_sha
        if pulumi_stack_sha is not None
        else _optional_env("RELEASE_PULUMI_STACK_SHA"),
        built_at=Instant.now().format_iso(unit="second"),
    )
    release_marker.write(bucket_name, marker)
    typer.echo(f"wrote {release_marker.marker_uri(bucket_name)} for git_sha={sha[:12]}")


@app.command("verify")
def verify(
    bucket: Annotated[
        str | None,
        typer.Option("--bucket", "-b", help="GCS bucket (defaults to $GCS_BUCKET)."),
    ] = None,
    git_sha: Annotated[
        str | None,
        typer.Option("--sha", "--git-sha", help="Expected git SHA (defaults to $GITHUB_SHA)."),
    ] = None,
) -> None:
    """Assert the bucket's release marker matches ``git_sha``. Exits non-zero on mismatch or missing.

    On mismatch the error message is emitted as a GitHub Actions ``::error::``
    annotation so CI surfaces the fix path at the top of the run summary.
    """
    bucket_name = bucket or _require_env("GCS_BUCKET")
    sha = git_sha or _require_env("GITHUB_SHA")

    try:
        release_marker.assert_matches(bucket_name, sha)
    except ReleaseMarkerMismatchError as exc:
        typer.echo(f"::error::{exc}", err=True)
        raise typer.Exit(2) from exc

    typer.echo(f"release marker OK for git_sha={sha[:12]} at {release_marker.marker_uri(bucket_name)}")
