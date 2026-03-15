"""Trigger: write run trigger to GCS, preflight queue cleanup."""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

from gcp.image.config.bmt_config import (
    DEFAULT_RUNTIME_CONTEXT,
    PREEMPT_ON_PR_STALE_QUEUE,
    TRIGGER_METADATA_KEEP_RECENT,
    TRIGGER_STALE_SEC,
    BmtConfig,
)
from whenever import Instant

from ci import config, core, gcs
from ci.actions import gh_error, write_github_output

try:
    from tools.repo.vars_contract import REPO_VARS_CONTRACT
except Exception:
    REPO_VARS_CONTRACT = None

DEFAULT_STATUS_CONTEXT: str = BmtConfig().bmt_status_context
_PUBSUB_PUBLISH_TIMEOUT_SEC = 30
DEFAULT_DESCRIPTION_PENDING = "BMT runtime in progress; status will update when complete."
PROJECT_WIDE_BMT_ID = "__all__"
_FULL_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")


def _default_context_from_contract(var_name: str, fallback: str) -> str:
    if REPO_VARS_CONTRACT is not None:
        try:
            defaults = REPO_VARS_CONTRACT.default_dict()
            ctx = defaults.get(var_name)
            if ctx and str(ctx).strip():
                return str(ctx).strip()
        except Exception:
            pass
    for base in (Path.cwd(), Path(__file__).resolve().parents[2]):
        contract_path = base / core.DEFAULT_ENV_CONTRACT_PATH
        if not contract_path.is_file():
            continue
        if contract_path.suffix == ".json":
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
    prefix = f"{runtime_bucket_root}/triggers/runs/"
    try:
        return [uri for uri in gcs.list_prefix(prefix) if uri.endswith(".json")]
    except gcs.GcsError as exc:
        raise RuntimeError(f"Failed to list pending triggers at {prefix}: {exc}") from exc


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


def _default_run_id(project: str, bmt_id: str) -> str:
    now = Instant.now().format_iso(unit="second", basic=True)
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    sha = _resolve_source_sha()[:12]
    raw = f"gh-{run_id}-{attempt}-{project}-{bmt_id}-{sha or now}"
    return core.sanitize_run_id(raw)


def _trigger_payload_is_valid(uri: str) -> bool:
    payload, err = gcs.download_json(uri)
    if not payload or err:
        return False
    if not (
        isinstance(payload.get("workflow_run_id"), (str, int))
        and str(payload.get("workflow_run_id", ""))
    ):
        return False
    repo = payload.get("repository")
    if not (isinstance(repo, str) and "/" in repo):
        return False
    sha = payload.get("sha")
    if not (isinstance(sha, str) and _FULL_SHA_RE.fullmatch(sha)):
        return False
    ref = payload.get("ref")
    if not (isinstance(ref, str) and ref.startswith("refs/")):
        return False
    bucket = payload.get("bucket")
    if not (isinstance(bucket, str) and len(bucket) > 0):
        return False
    legs = payload.get("legs")
    if not isinstance(legs, list) or len(legs) == 0:
        return False
    for leg in legs:
        if not isinstance(leg, dict) or not (
            str(leg.get("project", "")).strip()
            and str(leg.get("bmt_id", "")).strip()
            and str(leg.get("run_id", "")).strip()
        ):
            return False
    return True


def _trigger_identity(uri: str) -> tuple[str, str, str]:
    payload, _ = gcs.download_json(uri)
    if not payload:
        return ("", "", "")
    return (
        str(payload.get("repository", "")),
        str(payload.get("run_context", "")),
        str(payload.get("pull_request_number", "")),
    )


def _trigger_age_seconds(uri: str, *, now: Instant | None = None) -> int | None:
    payload, _ = gcs.download_json(uri)
    if not payload:
        return None
    raw = payload.get("triggered_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        triggered_at = Instant.parse_iso(value)
    except (ValueError, TypeError):
        return None
    now_inst = now if now is not None else Instant.now()
    return max(int(now_inst.timestamp() - triggered_at.timestamp()), 0)


def _trim_trigger_family_keep_recent(prefix_uri: str, keep_recent: int) -> int:
    uris = [u for u in gcs.list_prefix(prefix_uri) if u.endswith(".json")]
    if not uris:
        return 0
    run_ids = sorted(
        (
            u.split("/")[-1].replace(".json", "")
            for u in uris
            if u.split("/")[-1].replace(".json", "")
        ),
        reverse=True,
    )
    keep_set = set(run_ids[:keep_recent])
    removed = 0
    for u in uris:
        rid = u.split("/")[-1].replace(".json", "")
        if rid not in keep_set:
            try:
                gcs.delete_object(u)
                removed += 1
            except gcs.GcsError:
                pass
    return removed


class TriggerManager:
    def __init__(self, cfg: Any) -> None:
        self._cfg = cfg

    @classmethod
    def from_env(cls) -> TriggerManager:
        return cls(config.get_config())

    def write(self) -> None:
        self._cfg.require_gcp()
        bucket = self._cfg.gcs_bucket
        github_output = core.require_env("GITHUB_OUTPUT")
        matrix_json = core.require_env("FILTERED_MATRIX_JSON")
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

        ctx = self._cfg.bmt_status_context or _default_context_from_contract(
            "BMT_STATUS_CONTEXT", DEFAULT_STATUS_CONTEXT
        )
        runtime_bucket_root = core.bucket_root_uri(bucket)
        triggered_at = Instant.now().format_iso(unit="second")
        sha = _resolve_source_sha()
        if not _is_full_sha(sha):
            raise RuntimeError(
                "Unable to resolve a valid 40-char source SHA (HEAD_SHA or GITHUB_SHA)."
            )
        ref = _resolve_source_ref()
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        workflow_run_id = os.environ.get("GITHUB_RUN_ID", "local")

        legs = []
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

        run_payload: dict = {
            "workflow_run_id": workflow_run_id,
            "repository": repository,
            "sha": sha,
            "ref": ref,
            "run_context": run_context,
            "triggered_at": triggered_at,
            "bucket": bucket,
            "legs": legs,
            "status_context": ctx,
            "runtime_status_context": DEFAULT_RUNTIME_CONTEXT,
            "description_pending": DEFAULT_DESCRIPTION_PENDING,
        }
        if pr_number is not None:
            run_payload["pull_request_number"] = pr_number

        run_trigger_uri_str = core.run_trigger_uri(runtime_bucket_root, workflow_run_id)
        pending = _list_pending_trigger_uris(runtime_bucket_root)
        blocking = [u for u in pending if u != run_trigger_uri_str]
        if blocking:
            sample = ", ".join(blocking[:3])
            extra = "" if len(blocking) <= 3 else f" (+{len(blocking) - 3} more)"
            raise RuntimeError(
                f"VM runtime is busy: pending run trigger(s) exist. Blocking: {sample}{extra}. "
                "Wait for the active run to finish or clean stale trigger files."
            )
        try:
            gcs.upload_json(run_trigger_uri_str, run_payload)
        except gcs.GcsError as exc:
            gh_error(f"Failed to write run trigger: {exc}")
            raise

        if self._cfg.bmt_pubsub_topic and self._cfg.gcp_project:
            from google.cloud import pubsub_v1  # type: ignore[import-untyped]

            publisher = pubsub_v1.PublisherClient()
            topic_path = publisher.topic_path(self._cfg.gcp_project, self._cfg.bmt_pubsub_topic)
            future = publisher.publish(topic_path, json.dumps(run_payload).encode())
            future.result(timeout=_PUBSUB_PUBLISH_TIMEOUT_SEC)
            print(f"Published trigger to Pub/Sub topic {self._cfg.bmt_pubsub_topic!r}")

        write_github_output(
            github_output, "manifest", json.dumps({"legs": legs}, separators=(",", ":"))
        )
        write_github_output(github_output, "run_trigger_uri", run_trigger_uri_str)
        write_github_output(github_output, "requested_leg_count", str(len(legs)))
        write_github_output(
            github_output, "requested_legs", json.dumps(legs, separators=(",", ":"))
        )
        print(
            f"Triggered run {workflow_run_id} with {len(legs)} project request(s); VM will report status to GitHub"
        )

    def preflight_queue(self) -> None:
        run_id = core.workflow_run_id()
        run_context = os.environ.get("RUN_CONTEXT", "dev")
        keep_recent = max(1, TRIGGER_METADATA_KEEP_RECENT)
        root = core.workflow_runtime_root()
        runs_prefix = f"{root}/triggers/runs/"
        current_uri = f"{runs_prefix}{run_id}.json"

        path = core.require_env("GITHUB_OUTPUT")
        out = Path(path)
        with out.open("a", encoding="utf-8") as f:
            f.write("restart_vm=false\nstale_cleanup_count=0\n")

        existing = [u for u in gcs.list_prefix(runs_prefix) if u.endswith(".json")]
        blocking = []
        invalid = []
        for uri in existing:
            if uri == current_uri:
                continue
            if _trigger_payload_is_valid(uri):
                blocking.append(uri)
            else:
                invalid.append(uri)

        for uri in invalid:
            with contextlib.suppress(gcs.GcsError):
                gcs.delete_object(uri)
            rid = uri.split("/")[-1].replace(".json", "")
            for sub in ("acks", "status"):
                with contextlib.suppress(gcs.GcsError):
                    gcs.delete_object(f"{root}/triggers/{sub}/{rid}.json")

        if not blocking:
            pass
        elif run_context == "pr" and PREEMPT_ON_PR_STALE_QUEUE:
            current_pr = os.environ.get("PR_NUMBER", "").strip()
            current_repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
            if not current_pr or not current_repo:
                raise RuntimeError(
                    "RUN_CONTEXT=pr requires PR_NUMBER and GITHUB_REPOSITORY for same-PR stale cleanup."
                )
            same_pr = [
                u for u in blocking if _trigger_identity(u) == (current_repo, "pr", current_pr)
            ]
            [u for u in blocking if u not in same_pr]
            removed = 0
            for uri in same_pr:
                try:
                    gcs.delete_object(uri)
                    removed += 1
                except gcs.GcsError:
                    pass
                rid = uri.split("/")[-1].replace(".json", "")
                for sub in ("acks", "status"):
                    with contextlib.suppress(gcs.GcsError):
                        gcs.delete_object(f"{root}/triggers/{sub}/{rid}.json")
            with out.open("a", encoding="utf-8") as f:
                f.write(f"stale_cleanup_count={removed}\n")
                if removed > 0:
                    f.write("restart_vm=true\n")
        else:
            if run_context == "pr" and not PREEMPT_ON_PR_STALE_QUEUE:
                return
            now = Instant.now()
            stale = [
                u for u in blocking if (_trigger_age_seconds(u, now=now) or 0) >= TRIGGER_STALE_SEC
            ]
            len(blocking) - len(stale)
            removed = 0
            for uri in stale:
                try:
                    gcs.delete_object(uri)
                    removed += 1
                except gcs.GcsError:
                    pass
                rid = uri.split("/")[-1].replace(".json", "")
                for sub in ("acks", "status"):
                    with contextlib.suppress(gcs.GcsError):
                        gcs.delete_object(f"{root}/triggers/{sub}/{rid}.json")
            with out.open("a", encoding="utf-8") as f:
                f.write(f"stale_cleanup_count={removed}\n")
                if removed > 0:
                    f.write("restart_vm=true\n")

        remaining = [u for u in gcs.list_prefix(runs_prefix) if u.endswith(".json")]
        trim_runs = (
            0
            if remaining
            else _trim_trigger_family_keep_recent(f"{root}/triggers/runs/", keep_recent)
        )
        trim_acks = _trim_trigger_family_keep_recent(f"{root}/triggers/acks/", keep_recent)
        trim_status = _trim_trigger_family_keep_recent(f"{root}/triggers/status/", keep_recent)
        if trim_runs + trim_acks + trim_status > 0:
            print(
                f"::notice::Metadata trim: runs={trim_runs} acks={trim_acks} status={trim_status}"
            )
