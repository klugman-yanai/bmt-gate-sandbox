#!/usr/bin/env python3
"""Run the BMT watcher on the VM: validate runtime, load GitHub App secrets, run vm_watcher.py, then self-stop.

Invoked by startup_entrypoint.sh or systemd. Reads GCS_BUCKET, BMT_REPO_ROOT, etc. from VM metadata or env.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from gcp.image.config.bmt_config import get_config
from gcp.image.path_utils import VM_WATCHER_SCRIPT

METADATA_BASE = "http://metadata.google.internal/computeMetadata/v1"
METADATA_HEADERS = {"Metadata-Flavor": "Google"}

_log_file_holder: list[str | None] = [None]


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _log(_msg: str) -> None:
    sys.stdout.write(f"[{_now_iso()}] [run_watcher] {_msg}\n")
    sys.stdout.flush()


def _log_err(_msg: str) -> None:
    sys.stderr.write(f"[{_now_iso()}] [run_watcher] {_msg}\n")
    sys.stderr.flush()


def _write_health_marker(stage: str, *, status: str = "ok", detail: str = "") -> None:
    """Best-effort health marker for handshake preflight checks."""
    bucket = os.environ.get("GCS_BUCKET", "").strip()
    if not bucket:
        return
    instance = _read_meta_simple("instance/name") or os.environ.get("BMT_LIVE_VM", "").strip()
    if not instance:
        return
    payload = {
        "instance": instance,
        "stage": stage,
        "status": status,
        "detail": detail,
        "updated_at": _now_iso(),
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tf:
        tf.write(json.dumps(payload, indent=2) + "\n")
        tmp_path = tf.name
    uri = f"gs://{bucket}/triggers/status/health/{instance}.json"
    try:
        subprocess.run(
            ["gcloud", "storage", "cp", tmp_path, uri, "--quiet"],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()


def _read_meta(key: str) -> str:
    """Read instance attribute from GCP metadata server."""
    import urllib.request

    url = f"{METADATA_BASE}/instance/attributes/{key}"
    req = urllib.request.Request(url, headers=METADATA_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode("utf-8").strip()
    except Exception:
        return ""


def _read_meta_simple(path: str) -> str:
    """Read simple metadata path (e.g. instance/name, project/project-id)."""
    import urllib.request

    url = f"{METADATA_BASE}/{path}"
    req = urllib.request.Request(url, headers=METADATA_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode("utf-8").strip()
    except Exception:
        return ""


def _stop_instance_best_effort(exit_code: int) -> None:
    self_stop = os.environ.get("BMT_SELF_STOP", "1").strip()
    if self_stop != "1":
        _log(f"Self-stop disabled (BMT_SELF_STOP={self_stop}); leaving VM running.")
        return
    instance = _read_meta_simple("instance/name")
    zone_full = _read_meta_simple("instance/zone")
    zone = zone_full.split("/")[-1] if zone_full else ""
    project = _read_meta_simple("project/project-id")
    if not instance or not zone or not project:
        _log_err(f"Could not resolve instance metadata for self-stop (exit={exit_code}).")
        return
    _log(f"Stopping VM instance={instance} zone={zone} project={project} exit_code={exit_code}")
    r = subprocess.run(
        ["gcloud", "compute", "instances", "stop", instance, "--zone", zone, "--project", project],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode == 0:
        _log("Self-stop succeeded via gcloud CLI.")
        return
    _log_err("gcloud stop failed; attempting Compute API fallback.")
    import json
    import urllib.request

    token_url = f"{METADATA_BASE}/instance/service-accounts/default/token"
    req = urllib.request.Request(token_url, headers=METADATA_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            token_json = json.loads(resp.read().decode("utf-8"))
    except Exception:
        _log_err("Unable to obtain metadata access token for API self-stop.")
        return
    access_token = (token_json.get("access_token") or "").strip()
    if not access_token:
        _log_err("Unable to obtain metadata access token for API self-stop.")
        return
    stop_url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/stop"
    stop_req = urllib.request.Request(
        stop_url,
        data=b"",
        method="POST",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(stop_req, timeout=30) as resp:
            _log(f"Self-stop succeeded via Compute API fallback (HTTP {resp.status}).")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            _log("Self-stop succeeded via Compute API fallback (HTTP 409).")
        else:
            _log_err(f"Compute API self-stop failed (HTTP {e.code}).")
    except Exception as e:
        _log_err(f"Compute API self-stop failed: {e}")


def _upload_log_and_stop(exit_code: int) -> None:
    log_file = _log_file_holder[0]
    if log_file and Path(log_file).is_file():
        bucket = os.environ.get("GCS_BUCKET", "").strip()
        if bucket:
            vm_name = _read_meta_simple("instance/name") or "unknown"
            ts = _now_stamp()
            dest = f"gs://{bucket}/logs/{vm_name}-{ts}.log"
            try:
                r = subprocess.run(
                    ["gcloud", "storage", "cp", log_file, dest, "--quiet"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if r.returncode == 0:
                    _log("Uploaded startup log to GCS.")
                else:
                    _log_err("Watcher log upload to GCS failed.")
            except OSError:
                _log_err("gcloud not available; skipping startup log upload.")
    _stop_instance_best_effort(exit_code)


def _access_secret(secret_name: str, project: str, location: str | None) -> str:
    cmd = ["gcloud", "secrets", "versions", "access", "latest", "--secret", secret_name, "--project", project]
    if location:
        cmd.extend(["--location", location])
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def _access_secret_with_retry(secret_name: str, project: str, location: str | None, max_attempts: int = 3) -> str:
    delay = 2
    for attempt in range(1, max_attempts + 1):
        out = _access_secret(secret_name, project, location)
        if out:
            return out
        if attempt < max_attempts:
            _log_err(f"Secret access attempt {attempt}/{max_attempts} failed for {secret_name}; retrying in {delay}s.")
            time.sleep(delay)
            delay *= 2
    return ""


def _get_first_secret(candidates: list[str], suffix: str, project: str, location: str | None) -> tuple[str, str]:
    for c in candidates:
        value = _access_secret_with_retry(f"{c}_{suffix}", project, location)
        if value:
            return value, c
    return "", ""


def _load_github_app_credentials(env_label: str, prefix: str, project: str, location: str | None) -> None:
    alias_prefix = f"GH_APP_{prefix[11:]}" if prefix.startswith("GITHUB_APP_") else ""
    candidates = [prefix]
    if alias_prefix and alias_prefix != prefix:
        candidates.append(alias_prefix)
    app_id, selected = _get_first_secret(candidates, "ID", project, location)
    if not app_id:
        _log(f"Info: {env_label}: GitHub App secrets not found/readable ({prefix}_ID) in project {project}.")
        return
    installation_id, inst_sel = _get_first_secret(candidates, "INSTALLATION_ID", project, location)
    selected = selected or inst_sel
    private_key, pk_sel = _get_first_secret(candidates, "PRIVATE_KEY", project, location)
    selected = selected or pk_sel
    if not installation_id or not private_key:
        _log_err(f"Warning: {env_label}: secret set {prefix}_* partially available but values missing.")
        return
    if selected and selected != prefix:
        _log_err(f"Warning: {env_label}: using alias secret prefix {selected}_*; prefer canonical {prefix}_*.")
    os.environ[f"{prefix}_ID"] = app_id
    os.environ[f"{prefix}_INSTALLATION_ID"] = installation_id
    os.environ[f"{prefix}_PRIVATE_KEY"] = private_key
    _log(f"Loaded GitHub App credentials for {env_label} from {prefix}_*")


def _validate_venv_imports(python_bin: str) -> bool:
    r = subprocess.run(
        [
            python_bin,
            "-c",
            """
import importlib.util
import sys
required = ["jwt", "cryptography", "httpx", "google.cloud.storage", "whenever"]
missing = [n for n in required if importlib.util.find_spec(n) is None]
if importlib.util.find_spec("google.cloud.pubsub_v1") is None and importlib.util.find_spec("google.cloud.pubsub") is None:
    missing.append("google.cloud.pubsub_v1|google.cloud.pubsub")
if missing:
    print("Missing required pre-baked modules:", ", ".join(missing), file=sys.stderr)
    sys.exit(1)
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.returncode == 0


def _setup_env_and_config() -> tuple[str, str, str, str] | None:
    """Set GCS_BUCKET/GCP_PROJECT from metadata if needed, load config, set BMT_REPO_ROOT and pubsub. Returns (bucket, project, repo_root, sub_effective) or None on failure."""
    if not os.environ.get("GCS_BUCKET"):
        os.environ["GCS_BUCKET"] = _read_meta("GCS_BUCKET")
    if not os.environ.get("GCP_PROJECT"):
        os.environ["GCP_PROJECT"] = _read_meta("GCP_PROJECT")
    cfg = get_config(runtime=os.environ)
    repo_root = cfg.effective_repo_root
    os.environ["BMT_REPO_ROOT"] = repo_root
    sub_effective = cfg.effective_pubsub_subscription or ""
    if sub_effective:
        os.environ["BMT_PUBSUB_SUBSCRIPTION"] = sub_effective
    bucket = os.environ.get("GCS_BUCKET", "").strip()
    if not bucket:
        _log_err("Set GCS_BUCKET or VM metadata GCS_BUCKET")
        return None
    project = os.environ.get("GCP_PROJECT", "").strip() or _read_meta_simple("project/project-id")
    os.environ["GCP_PROJECT"] = project
    _log(f"Config: BMT_REPO_ROOT={repo_root} GCS_BUCKET={bucket} GCP_PROJECT={project or '<unset>'}")
    if os.path.ismount("/mnt/audio_data"):
        os.environ["BMT_DATASET_LOCAL_PATH"] = "/mnt/audio_data"
        _log("BMT_DATASET_LOCAL_PATH=/mnt/audio_data (gcsfuse mount)")
    return bucket, project, repo_root, sub_effective


def _resolve_workspace_root() -> None:
    """Set BMT_WORKSPACE_ROOT to HOME/bmt_workspace if not already set."""
    if os.environ.get("BMT_WORKSPACE_ROOT"):
        return
    home_dir = Path(os.environ.get("HOME", "/root"))
    os.environ["BMT_WORKSPACE_ROOT"] = str(home_dir / "bmt_workspace")
    _log(f"Workspace root: {os.environ['BMT_WORKSPACE_ROOT']}")


def _ensure_venv_and_watcher(repo_root: str) -> str | None:
    """Validate watcher script and venv python; return venv python path or None on failure."""
    repo_root_path = Path(repo_root)
    venv_python = repo_root_path / ".venv" / "bin" / "python"
    watcher_path = repo_root_path / VM_WATCHER_SCRIPT
    if not watcher_path.is_file():
        _log_err(f"Missing watcher entrypoint: {watcher_path}")
        return None
    if not venv_python.is_file() or not os.access(venv_python, os.X_OK):
        _log_err(f"Missing pre-baked python at {venv_python}; rebuild/provision image.")
        return None
    _log("Phase: validating pre-baked runtime")
    if not _validate_venv_imports(str(venv_python)):
        _log_err("Pre-baked runtime import validation failed; rebuild/provision image.")
        return None
    _log("Pre-baked runtime validation passed.")
    return str(venv_python)


def _configure_secrets_and_creds(project: str) -> None:
    """Set regional Secret Manager endpoint and load GitHub App credentials."""
    secrets_location = os.environ.get("BMT_SECRETS_LOCATION", "").strip()
    if not secrets_location:
        zone_full = _read_meta_simple("instance/zone")
        if zone_full:
            secrets_location = zone_full.split("/")[-1].rsplit("-", 1)[0]
    if secrets_location:
        subprocess.run(
            [
                "gcloud",
                "config",
                "set",
                "api_endpoint_overrides/secretmanager",
                f"https://secretmanager.{secrets_location}.rep.googleapis.com/",
            ],
            capture_output=True,
            check=False,
        )
        _log(f"Configured regional Secret Manager endpoint: {secrets_location}")
    _log("Phase: loading GitHub App credentials from Secret Manager")
    _load_github_app_credentials("test environment", "GITHUB_APP_TEST", project, secrets_location or None)
    _load_github_app_credentials("prod environment", "GITHUB_APP_PROD", project, secrets_location or None)


def _launch_watcher(repo_root: str, bucket: str, venv_python: str, sub_effective: str, project: str) -> int:
    """Build watcher args, run subprocess, return exit code."""
    watcher_args = [
        venv_python,
        VM_WATCHER_SCRIPT,
        "--bucket",
        bucket,
        "--workspace-root",
        os.environ["BMT_WORKSPACE_ROOT"],
        "--exit-after-run",
        "--idle-timeout-sec",
        os.environ.get("BMT_IDLE_TIMEOUT_SEC", "600"),
    ]
    sub = sub_effective.strip()
    if sub and project:
        watcher_args.extend(["--subscription", f"projects/{project}/subscriptions/{sub}", "--gcp-project", project])
        _log(f"Pub/Sub subscription: projects/{project}/subscriptions/{sub}")
    proc = subprocess.run(watcher_args, cwd=repo_root, env=os.environ, check=False)
    if proc.returncode != 0:
        _log_err(f"Watcher exited with non-zero status: {proc.returncode}")
    return proc.returncode


def main() -> int:
    exit_code = 0
    try:
        ts = _now_stamp()
        log_path = Path(tempfile.gettempdir()) / f"bmt-startup-{ts}.log"
        _log_file_holder[0] = str(log_path)
        with log_path.open("a"):
            pass
        _log(f"Phase: startup; log file={_log_file_holder[0]}")
        _write_health_marker("startup")

        config_triple = _setup_env_and_config()
        if config_triple is None:
            _write_health_marker("config_failed", status="error", detail="missing_or_invalid_config")
            return 1
        bucket, project, repo_root, sub_effective = config_triple
        _write_health_marker("config_loaded")
        _resolve_workspace_root()

        venv_python = _ensure_venv_and_watcher(repo_root)
        if venv_python is None:
            _write_health_marker("runtime_validation_failed", status="error", detail="venv_or_watcher_invalid")
            return 1
        _write_health_marker("runtime_validated")
        _configure_secrets_and_creds(project)
        _write_health_marker("secrets_loaded")

        _log("Phase: launching vm_watcher.py")
        _write_health_marker("watcher_launching")
        _write_health_marker("watcher_running")
        exit_code = _launch_watcher(repo_root, bucket, venv_python, sub_effective, project)
        status = "ok" if exit_code == 0 else "error"
        _write_health_marker("watcher_exited", status=status, detail=f"exit_code={exit_code}")
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
        _write_health_marker("startup_failed", status="error", detail=f"system_exit={exit_code}")
    except Exception as e:
        _log_err(str(e))
        exit_code = 1
        _write_health_marker("startup_failed", status="error", detail=str(e))
    finally:
        _log(f"Phase: exit handler; exit_code={exit_code}")
        _upload_log_and_stop(exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
