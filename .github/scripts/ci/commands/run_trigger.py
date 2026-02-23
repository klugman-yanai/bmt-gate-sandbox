from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import click

from ci import models
from ci.adapters import gcloud_cli
from ci.github_output import write_github_output

DEFAULT_STATUS_CONTEXT = "BMT Gate"
DEFAULT_DESCRIPTION_PENDING = "BMT running on VM; status will update when complete."
DEFAULT_DESCRIPTION_SUCCESS = "BMT passed"
DEFAULT_DESCRIPTION_FAILURE = "BMT failed"


def _default_run_id(project: str, bmt_id: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    sha = os.environ.get("GITHUB_SHA", "")[:12]
    raw = f"gh-{run_id}-{attempt}-{project}-{bmt_id}-{sha or now}"
    return models.sanitize_run_id(raw)


@click.command("trigger")
@click.option("--config-root", default="remote", show_default=True)
@click.option("--bucket", required=True)
@click.option("--bucket-prefix", default="")
@click.option("--matrix-json", required=True, help="JSON matrix from prepare-matrix (has 'include' array)")
@click.option("--run-context", required=True, type=click.Choice(["pr", "dev"]))
@click.option(
    "--pr-number", type=int, default=None, help="Pull request number (for PR comment); set when event is pull_request"
)
@click.option("--github-output", envvar="GITHUB_OUTPUT")
def command(
    config_root: str,
    bucket: str,
    bucket_prefix: str,
    matrix_json: str,
    run_context: str,
    pr_number: int | None,
    github_output: str | None,
) -> None:
    """Write one run trigger file to GCS (all legs); VM will run BMT and post commit status."""
    if not github_output:
        raise RuntimeError("GITHUB_OUTPUT is required")

    matrix = json.loads(matrix_json)
    rows = matrix.get("include", [])
    if not rows:
        raise RuntimeError("Empty matrix — nothing to trigger")

    ctx = (os.environ.get("BMT_STATUS_CONTEXT") or "").strip() or DEFAULT_STATUS_CONTEXT
    description_pending = (os.environ.get("BMT_DESCRIPTION_PENDING") or "").strip() or DEFAULT_DESCRIPTION_PENDING
    description_success = (os.environ.get("BMT_DESCRIPTION_SUCCESS") or "").strip() or DEFAULT_DESCRIPTION_SUCCESS
    description_failure = (os.environ.get("BMT_DESCRIPTION_FAILURE") or "").strip() or DEFAULT_DESCRIPTION_FAILURE

    normalized_prefix = models.normalize_prefix(bucket_prefix)
    bucket_root = models.bucket_root_uri(bucket, normalized_prefix)
    triggered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sha = os.environ.get("GITHUB_SHA", "")
    ref = os.environ.get("GITHUB_REF", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    workflow_run_id = os.environ.get("GITHUB_RUN_ID", "local")

    legs: list[dict[str, str]] = []
    for row in rows:
        project = str(row["project"])
        bmt_id = str(row["bmt_id"])
        run_id = _default_run_id(project, bmt_id)
        legs.append(
            {
                "project": project,
                "bmt_id": bmt_id,
                "run_id": run_id,
                "triggered_at": triggered_at,
            }
        )

    run_payload: dict[str, str | int | list[dict[str, str]]] = {
        "workflow_run_id": workflow_run_id,
        "repository": repository,
        "sha": sha,
        "ref": ref,
        "run_context": run_context,
        "triggered_at": triggered_at,
        "bucket": bucket,
        "bucket_prefix": normalized_prefix,
        "legs": legs,
        "status_context": ctx,
        "description_pending": description_pending,
        "description_success": description_success,
        "description_failure": description_failure,
    }
    if pr_number is not None:
        run_payload["pull_request_number"] = pr_number

    run_trigger_uri_str = models.run_trigger_uri(bucket_root, normalized_prefix, workflow_run_id)
    try:
        gcloud_cli.upload_json(run_trigger_uri_str, run_payload)
    except gcloud_cli.GcloudError as exc:
        print(f"::error::Failed to write run trigger: {exc}")
        raise

    manifest = {"legs": legs}
    write_github_output(github_output, "manifest", json.dumps(manifest, separators=(",", ":")))
    write_github_output(github_output, "run_trigger_uri", run_trigger_uri_str)
    write_github_output(github_output, "requested_leg_count", str(len(legs)))
    write_github_output(github_output, "requested_legs", json.dumps(legs, separators=(",", ":")))
    print(f"Triggered run {workflow_run_id} with {len(legs)} leg(s); VM will report status to GitHub")
