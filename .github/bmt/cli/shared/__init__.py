"""BMT shared runtime: constants, GCS/VM operations, config loading, and output helpers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

# ── Path defaults ──────────────────────────────────────────────────────────────

DEFAULT_CONFIG_ROOT = "remote/code"
DEFAULT_ENV_CONTRACT_PATH = "config/env_contract.json"

# ── Decision constants ─────────────────────────────────────────────────────────

DECISION_ACCEPTED = "accepted"
DECISION_ACCEPTED_WITH_WARNINGS = "accepted_with_warnings"
DECISION_REJECTED = "rejected"
DECISION_TIMEOUT = "timeout"

# ── Errors ─────────────────────────────────────────────────────────────────────


class ConfigError(RuntimeError):
    """Raised when CI config files are missing or invalid."""


class GcloudError(RuntimeError):
    """Raised when a gcloud command fails in a non-recoverable way."""


# ── URI helpers ────────────────────────────────────────────────────────────────

_RUN_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def bucket_uri(bucket_root: str, rel_path: str) -> str:
    return f"{bucket_root}/{rel_path.lstrip('/')}"


def code_bucket_root_uri(bucket: str) -> str:
    return f"gs://{bucket}/code"


def runtime_bucket_root_uri(bucket: str) -> str:
    return f"gs://{bucket}/runtime"


def sanitize_run_id(raw: str) -> str:
    value = _RUN_ID_SAFE.sub("-", raw.strip())
    value = value.strip("-._")
    if not value:
        raise ValueError("run_id is empty after sanitization")
    return value[:200]


def run_trigger_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/runs/{safe_run_id}.json")


def run_handshake_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/acks/{safe_run_id}.json")


def run_status_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/status/{safe_run_id}.json")


def decision_exit(decision: str) -> int:
    return 0 if decision in {DECISION_ACCEPTED, DECISION_ACCEPTED_WITH_WARNINGS} else 1


# ── Env helpers ────────────────────────────────────────────────────────────────


def require_env(name: str) -> str:
    """Return env var value or raise RuntimeError if unset/empty."""
    val = os.environ.get(name, "")
    if not val.strip():
        raise RuntimeError(f"Required env var {name!r} is not set or empty")
    return val.strip()


# ── GCS / VM operations ────────────────────────────────────────────────────────


def run_capture(cmd: list[str]) -> tuple[int, str]:
    """Run command; return (exit_code, stderr or stdout)."""
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    text = (proc.stderr or proc.stdout or "").strip()
    return proc.returncode, text


def run_capture_retry(cmd: list[str], attempts: int = 3, base_delay: float = 2.0) -> tuple[int, str]:
    """run_capture with exponential-backoff retry on non-zero exit (transient GCS errors)."""
    rc, text = 1, ""
    for attempt in range(1, attempts + 1):
        rc, text = run_capture(cmd)
        if rc == 0 or attempt >= attempts:
            return rc, text
        time.sleep(base_delay * (2 ** (attempt - 1)))
    return rc, text


def download_json(uri: str) -> tuple[dict[str, Any] | None, str | None]:
    """Download a GCS object as JSON; return (payload, None) or (None, error_message)."""
    with tempfile.TemporaryDirectory(prefix="ci_verdict_") as tmp_dir:
        local_path = Path(tmp_dir) / "payload.json"
        rc, err = run_capture_retry(["gcloud", "storage", "cp", uri, str(local_path)])
        if rc != 0:
            return None, err
        try:
            payload = json.loads(local_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return None, f"invalid_json: {exc}"
        if not isinstance(payload, dict):
            return None, "invalid_json: expected object"
        return payload, None


def upload_json(uri: str, payload: dict[str, Any]) -> None:
    """Upload a JSON object to GCS."""
    with tempfile.TemporaryDirectory(prefix="ci_trigger_") as tmp_dir:
        local_path = Path(tmp_dir) / "payload.json"
        local_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        rc, err = run_capture_retry(["gcloud", "storage", "cp", str(local_path), uri])
        if rc != 0:
            raise GcloudError(f"Failed to upload {uri}: {err}")


def gcs_exists(uri: str) -> bool:
    """Return True when an object exists in GCS."""
    rc, _ = run_capture(["gcloud", "storage", "ls", uri])
    return rc == 0


def vm_start(project: str, zone: str, instance_name: str) -> None:
    """Start a stopped Compute Engine instance."""
    cmd = ["gcloud", "compute", "instances", "start", instance_name, "--zone", zone, "--project", project]
    rc, err = run_capture(cmd)
    if rc != 0:
        raise GcloudError(f"Failed to start VM {instance_name}: {err}")


def vm_describe(project: str, zone: str, instance_name: str) -> dict[str, Any]:
    """Describe a Compute Engine instance as JSON."""
    cmd = [
        "gcloud",
        "compute",
        "instances",
        "describe",
        instance_name,
        "--zone",
        zone,
        "--project",
        project,
        "--format=json",
    ]
    rc, out = run_capture(cmd)
    if rc != 0:
        raise GcloudError(f"Failed to describe VM {instance_name}: {out}")
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        raise GcloudError(f"Invalid JSON while describing VM {instance_name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GcloudError(f"Invalid VM describe payload for {instance_name}: expected object")
    return payload


def vm_serial_output(project: str, zone: str, instance_name: str) -> str:
    """Fetch serial output text for a VM."""
    cmd = [
        "gcloud",
        "compute",
        "instances",
        "get-serial-port-output",
        instance_name,
        "--zone",
        zone,
        "--project",
        project,
    ]
    rc, out = run_capture(cmd)
    if rc != 0:
        raise GcloudError(f"Failed to get serial output for {instance_name}: {out}")
    return out


def vm_serial_output_retry(
    project: str, zone: str, instance_name: str, *, attempts: int = 4, base_delay_sec: float = 2.0
) -> str:
    """Fetch serial output with retry for startup races."""
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            return vm_serial_output(project, zone, instance_name)
        except GcloudError as exc:
            last_error = str(exc)
            if attempt >= attempts:
                break
            time.sleep(base_delay_sec * (2 ** (attempt - 1)))
    raise GcloudError(last_error or f"Failed to get serial output for {instance_name}")


def vm_add_metadata(
    project: str,
    zone: str,
    instance_name: str,
    metadata: dict[str, str],
    *,
    metadata_files: dict[str, Path] | None = None,
) -> None:
    """Set custom metadata keys and optional metadata-from-file values on a Compute Engine instance."""
    cmd = ["gcloud", "compute", "instances", "add-metadata", instance_name, "--zone", zone, "--project", project]
    if metadata:
        cmd.extend(["--metadata", ",".join(f"{k}={v}" for k, v in metadata.items())])
    if metadata_files:
        cmd.extend(["--metadata-from-file", ",".join(f"{k}={v}" for k, v in metadata_files.items())])
    if not metadata and not metadata_files:
        raise GcloudError(f"No metadata provided for {instance_name}")
    rc, err = run_capture(cmd)
    if rc != 0:
        raise GcloudError(f"Failed to update VM metadata for {instance_name}: {err}")


# ── Config loading ─────────────────────────────────────────────────────────────


def read_json_object(path: Path) -> dict[str, Any]:
    """Load and validate a JSON file as a single object; raises ConfigError if missing/invalid."""
    if not path.is_file():
        raise ConfigError(f"Missing JSON file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Expected JSON object at {path}")
    return data


def _parse_filter(raw: str) -> set[str]:
    s = (raw or "").strip()
    if not s:
        return set()
    # JSON array e.g. ["sk"] or ["SK"] (normalized to lowercase to match project keys)
    if s.startswith("["):
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return {str(x).strip().lower() for x in parsed if str(x).strip()}
    normalized = " ".join(s.lower().split())
    if normalized in {"all", "*", "all release runners", "all-release-runners", "all_release_runners"}:
        return set()
    return {item.strip().lower() for item in raw.replace(",", " ").split() if item.strip()}


def _projects_cfg(config_root: Path) -> dict[str, Any]:
    payload = read_json_object(config_root / "bmt_projects.json")
    projects = payload.get("projects", {})
    if not isinstance(projects, dict):
        raise ConfigError(f"Invalid projects object in {config_root / 'bmt_projects.json'}")
    return projects


def _project_cfg(config_root: Path, project: str) -> dict[str, Any]:
    cfg = _projects_cfg(config_root).get(project)
    if not isinstance(cfg, dict):
        raise ConfigError(f"Unknown project: {project}")
    return cfg


def _jobs_cfg(config_root: Path, project_cfg: dict[str, Any]) -> dict[str, Any]:
    jobs_rel = str(project_cfg.get("jobs_config", "")).strip()
    if not jobs_rel:
        raise ConfigError("Project missing jobs_config")
    jobs_path = config_root / jobs_rel
    payload = read_json_object(jobs_path)
    bmts = payload.get("bmts", {})
    if not isinstance(bmts, dict):
        raise ConfigError(f"Invalid bmts object in {jobs_path}")
    return bmts


def build_matrix(config_root: Path, project_filter_raw: str) -> dict[str, list[dict[str, str]]]:
    """Build CI job matrix (project, bmt_id) from bmt_projects.json and jobs configs."""
    project_filter = _parse_filter(project_filter_raw)
    include: list[dict[str, str]] = []
    for project, project_cfg in _projects_cfg(config_root).items():
        if not isinstance(project_cfg, dict):
            continue
        if not bool(project_cfg.get("enabled", True)):
            continue
        if project_filter and project not in project_filter:
            continue
        bmts = _jobs_cfg(config_root, project_cfg)
        for bmt_id, bmt_cfg in bmts.items():
            if isinstance(bmt_cfg, dict) and bool(bmt_cfg.get("enabled", True)):
                include.append({"project": project, "bmt_id": bmt_id})
    include.sort(key=lambda row: (row["project"], row["bmt_id"]))
    return {"include": include}


def resolve_bmt_cfg(config_root: Path, project: str, bmt_id: str) -> dict[str, Any]:
    project_cfg = _project_cfg(config_root, project)
    bmt_cfg = _jobs_cfg(config_root, project_cfg).get(bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise ConfigError(f"Unknown bmt_id: {project}.{bmt_id}")
    return bmt_cfg


def resolve_results_prefix(config_root: Path, project: str, bmt_id: str) -> str:
    """Return paths.results_prefix for the given project and bmt_id."""
    bmt_cfg = resolve_bmt_cfg(config_root, project, bmt_id)
    paths_cfg = bmt_cfg.get("paths", {})
    if not isinstance(paths_cfg, dict):
        raise ConfigError(f"BMT {project}.{bmt_id} paths must be an object")
    results_prefix = str(paths_cfg.get("results_prefix", "")).strip().rstrip("/")
    if not results_prefix:
        raise ConfigError(f"BMT {project}.{bmt_id} missing paths.results_prefix")
    return results_prefix


# ── GitHub output helpers ──────────────────────────────────────────────────────


def write_github_output(github_output: str | None, key: str, value: str) -> None:
    """Append key=value to GITHUB_OUTPUT file (silently no-ops if path is None)."""
    if not github_output:
        return
    with Path(github_output).open("a", encoding="utf-8") as fh:
        _ = fh.write(f"{key}={value}\n")
