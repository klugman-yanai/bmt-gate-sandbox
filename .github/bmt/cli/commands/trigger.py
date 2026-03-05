"""Run trigger writing."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from cli import gcloud, models
from cli.shared import DEFAULT_ENV_CONTRACT_PATH, require_env, write_github_output

DEFAULT_STATUS_CONTEXT = "BMT Gate"
DEFAULT_RUNTIME_CONTEXT = "BMT Runtime"
DEFAULT_DESCRIPTION_PENDING = "BMT runtime in progress; status will update when complete."
PROJECT_WIDE_BMT_ID = "__all__"


def _default_context_from_contract(var_name: str, fallback: str) -> str:
    """Read an env-contract default value when present."""
    for base in (Path.cwd(), Path(__file__).resolve().parents[3]):
        contract_path = base / DEFAULT_ENV_CONTRACT_PATH
        if contract_path.is_file():
            try:
                with contract_path.open() as f:
                    contract = json.load(f)
                defaults = contract.get("defaults") or {}
                ctx = defaults.get(var_name)
                if ctx and str(ctx).strip():
                    return str(ctx).strip()
            except (OSError, json.JSONDecodeError, TypeError):
                pass
            break
    return fallback


def _list_pending_trigger_uris(runtime_bucket_root: str) -> list[str]:
    """List existing run trigger URIs under runtime root."""
    prefix = f"{runtime_bucket_root}/triggers/runs/"
    rc, out = gcloud.run_capture(["gcloud", "storage", "ls", prefix])
    if rc != 0:
        text = (out or "").lower()
        if "matched no objects" in text or "one or more urls matched no objects" in text:
            return []
        raise RuntimeError(f"Failed to list pending triggers at {prefix}: {out}")
    return [line.strip() for line in (out or "").splitlines() if line.strip().endswith(".json")]


def _default_run_id(project: str, bmt_id: str) -> str:
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    sha = _resolve_source_sha()[:12]
    raw = f"gh-{run_id}-{attempt}-{project}-{bmt_id}-{sha or now}"
    return models.sanitize_run_id(raw)


def _is_full_sha(value: str) -> bool:
    v = value.strip()
    return len(v) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in v)


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
    Reads FILTERED_MATRIX_JSON, RUN_CONTEXT, PR_NUMBER, GCS_BUCKET, GITHUB_OUTPUT."""
    bucket = require_env("GCS_BUCKET")
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

    ctx = (os.environ.get("BMT_STATUS_CONTEXT") or "").strip() or _default_context_from_contract(
        "BMT_STATUS_CONTEXT",
        DEFAULT_STATUS_CONTEXT,
    )
    runtime_ctx = (os.environ.get("BMT_RUNTIME_CONTEXT") or "").strip() or _default_context_from_contract(
        "BMT_RUNTIME_CONTEXT",
        DEFAULT_RUNTIME_CONTEXT,
    )

    runtime_bucket_root = models.runtime_bucket_root_uri(bucket)
    workflow_run_id = os.environ.get("GITHUB_RUN_ID", "local")
    run_trigger_uri_str = models.run_trigger_uri(runtime_bucket_root, workflow_run_id)

    runtime_backend = (os.environ.get("BMT_RUNTIME_BACKEND") or "vm").strip().lower()
    if runtime_backend != "cloud_run_job":
        # VM backend is a singleton: block if another run is already queued.
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

    triggered_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    sha = _resolve_source_sha()
    if not _is_full_sha(sha):
        raise RuntimeError("Unable to resolve a valid 40-char source SHA (HEAD_SHA or GITHUB_SHA).")
    ref = _resolve_source_ref()
    repository = os.environ.get("GITHUB_REPOSITORY", "")

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

    import time as _time

    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            gcloud.upload_json(run_trigger_uri_str, run_payload)
            last_exc = None
            break
        except gcloud.GcloudError as exc:
            last_exc = exc
            print(f"::warning::Trigger upload attempt {attempt}/3 failed: {exc}")
            if attempt < 3:
                _time.sleep(5 * attempt)
    if last_exc is not None:
        print(f"::error::Failed to write run trigger after 3 attempts: {last_exc}")
        raise last_exc

    manifest = {"legs": legs}
    write_github_output(github_output, "manifest", json.dumps(manifest, separators=(",", ":")))
    write_github_output(github_output, "run_trigger_uri", run_trigger_uri_str)
    write_github_output(github_output, "requested_leg_count", str(len(legs)))
    write_github_output(github_output, "requested_legs", json.dumps(legs, separators=(",", ":")))
    print(
        f"Triggered run {workflow_run_id} with {len(legs)} project request(s); "
        "VM will resolve runtime-supported BMTs per project and report status to GitHub"
    )
