"""Run trigger writing."""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path

# Import runtime context constant (behavioral; not config)
from gcp.code.config.bmt_config import DEFAULT_RUNTIME_CONTEXT
from tools.repo.vars_contract import REPO_VARS_CONTRACT
from whenever import Instant

from cli import shared
from cli.gh_output import gh_error
from cli.shared import DEFAULT_ENV_CONTRACT_PATH, get_config, require_env, write_github_output

DEFAULT_STATUS_CONTEXT = "BMT Gate"
_PUBSUB_PUBLISH_TIMEOUT_SEC = 30
DEFAULT_DESCRIPTION_PENDING = "BMT runtime in progress; status will update when complete."
PROJECT_WIDE_BMT_ID = "__all__"


def _default_context_from_contract(var_name: str, fallback: str) -> str:
    """Read an env-contract default value when present."""
    # Python contract (tools.repo.vars_contract) is always available when bmt-gcloud is installed.
    with contextlib.suppress(Exception):
        # best-effort: REPO_VARS_CONTRACT may not expose default_dict in all environments
        defaults = REPO_VARS_CONTRACT.default_dict()
        ctx = defaults.get(var_name)
        if ctx and str(ctx).strip():
            return str(ctx).strip()
    for base in (Path.cwd(), Path(__file__).resolve().parents[3]):
        contract_path = base / DEFAULT_ENV_CONTRACT_PATH
        if not contract_path.is_file():
            continue
        if contract_path.suffix == ".json":
            with contextlib.suppress(OSError, json.JSONDecodeError, TypeError):
                with contract_path.open() as f:
                    contract = json.load(f)
                defaults = contract.get("defaults") or {}
                ctx = defaults.get(var_name)
                if ctx and str(ctx).strip():
                    return str(ctx).strip()
        break
    return fallback


def _list_pending_trigger_uris(runtime_bucket_root: str) -> list[str]:
    """List existing run trigger URIs under runtime root."""
    from cli import gcs

    prefix = f"{runtime_bucket_root}/triggers/runs/"
    try:
        return [uri for uri in gcs.list_prefix(prefix) if uri.endswith(".json")]
    except gcs.GcsError as exc:
        raise RuntimeError(f"Failed to list pending triggers at {prefix}: {exc}") from exc


def _default_run_id(project: str, bmt_id: str) -> str:
    now = Instant.now().format_iso(unit="second", basic=True)
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    sha = _resolve_source_sha()[:12]
    raw = f"gh-{run_id}-{attempt}-{project}-{bmt_id}-{sha or now}"
    return shared.sanitize_run_id(raw)


_FULL_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")


def _is_full_sha(value: str) -> bool:
    return bool(_FULL_SHA_RE.fullmatch(value.strip()))


def _resolve_source_sha() -> str:
    head_sha = (os.environ.get("HEAD_SHA") or "").strip()
    if _is_full_sha(head_sha):
        return head_sha
    return (os.environ.get("GITHUB_SHA") or "").strip()


def _resolve_source_ref() -> str:
    head_ref = (os.environ.get("HEAD_REF") or "").strip()
    if head_ref.startswith("refs/"):
        return head_ref
    head_branch = (os.environ.get("HEAD_BRANCH") or "").strip()
    if head_branch:
        return f"refs/heads/{head_branch}"
    return (os.environ.get("GITHUB_REF") or "").strip()


def _project_rows(rows: list[object]) -> list[str]:
    """Return unique projects from matrix rows while preserving first-seen order."""
    projects: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        project = str(row.get("project", "")).strip()
        if not project or project in seen:
            continue
        seen.add(project)
        projects.append(project)
    return projects


def run_trigger() -> None:
    """Write one run trigger file to GCS (all legs); VM will run BMT and post commit status.
    Reads FILTERED_MATRIX_JSON, RUN_CONTEXT, PR_NUMBER, GITHUB_OUTPUT from env; GCS_BUCKET and status context from config.

    Test-case (no real PR): set GITHUB_REPOSITORY to an enabled repo in
    gcp/code/config/github_repos.json (e.g. klugman-yanai/bmt-gate-sandbox) and
    RUN_CONTEXT=dev so the VM skips PR state checks and can post status to the test repo.
    """
    cfg = get_config()
    cfg.require_gcp()
    bucket = cfg.gcs_bucket
    github_output = require_env("GITHUB_OUTPUT")
    matrix_json = require_env("FILTERED_MATRIX_JSON")
    run_context = os.environ.get("RUN_CONTEXT", "dev")
    pr_number_raw = os.environ.get("PR_NUMBER", "").strip()
    pr_number = int(pr_number_raw) if pr_number_raw.isdigit() else None

    matrix = json.loads(matrix_json)
    rows = matrix.get("include", [])
    if not rows:
        raise RuntimeError("Empty matrix — nothing to trigger")
    projects = _project_rows(rows)
    if not projects:
        raise RuntimeError("Matrix has no valid project rows — nothing to trigger")

    ctx = cfg.bmt_status_context or _default_context_from_contract(
        "BMT_STATUS_CONTEXT",
        DEFAULT_STATUS_CONTEXT,
    )
    runtime_ctx = DEFAULT_RUNTIME_CONTEXT

    runtime_bucket_root = shared.runtime_bucket_root_uri(bucket)
    triggered_at = Instant.now().format_iso(unit="second")
    sha = _resolve_source_sha()
    if not _is_full_sha(sha):
        raise RuntimeError("Unable to resolve a valid 40-char source SHA (HEAD_SHA or GITHUB_SHA).")
    ref = _resolve_source_ref()
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    workflow_run_id = os.environ.get("GITHUB_RUN_ID", "local")

    legs: list[dict[str, str]] = []
    for project in projects:
        run_id = _default_run_id(project, PROJECT_WIDE_BMT_ID)
        legs.append(
            {
                "project": project,
                "bmt_id": PROJECT_WIDE_BMT_ID,
                "run_id": run_id,
                "request_scope": "project_wide",
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
        "legs": legs,
        "status_context": ctx,
        "runtime_status_context": runtime_ctx,
        "description_pending": DEFAULT_DESCRIPTION_PENDING,
    }
    if pr_number is not None:
        run_payload["pull_request_number"] = pr_number

    run_trigger_uri_str = shared.run_trigger_uri(runtime_bucket_root, workflow_run_id)
    pending_trigger_uris = _list_pending_trigger_uris(runtime_bucket_root)
    blocking_triggers = [uri for uri in pending_trigger_uris if uri != run_trigger_uri_str]
    if blocking_triggers:
        sample = ", ".join(blocking_triggers[:3])
        extra = "" if len(blocking_triggers) <= 3 else f" (+{len(blocking_triggers) - 3} more)"
        raise RuntimeError(
            "VM runtime is busy: pending run trigger(s) already exist under runtime root. "
            f"Blocking triggers: {sample}{extra}. "
            "Wait for the active run to finish or clean stale trigger files before retrying."
        )
    try:
        shared.upload_json(run_trigger_uri_str, run_payload)
    except shared.GcloudError as exc:
        gh_error(f"Failed to write run trigger: {exc}")
        raise

    # Also publish to Pub/Sub for near-instant VM delivery (optional).
    pubsub_topic = cfg.bmt_pubsub_topic
    if pubsub_topic and cfg.gcp_project:
        from google.cloud import pubsub_v1  # type: ignore[import-untyped]

        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(cfg.gcp_project, pubsub_topic)
        future = publisher.publish(topic_path, json.dumps(run_payload).encode())
        future.result(timeout=_PUBSUB_PUBLISH_TIMEOUT_SEC)
        print(f"Published trigger to Pub/Sub topic {pubsub_topic!r}")

    manifest = {"legs": legs}
    write_github_output(github_output, "manifest", json.dumps(manifest, separators=(",", ":")))
    write_github_output(github_output, "run_trigger_uri", run_trigger_uri_str)
    write_github_output(github_output, "requested_leg_count", str(len(legs)))
    write_github_output(github_output, "requested_legs", json.dumps(legs, separators=(",", ":")))
    print(
        f"Triggered run {workflow_run_id} with {len(legs)} project request(s); "
        "VM will resolve runtime-supported BMTs per project and report status to GitHub"
    )
