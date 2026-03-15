"""VM-side logging: rotating file, optional stdout, and log-dump to GCS for debugging.

Used by vm_watcher and root_orchestrator so logs survive restarts and can be
retrieved when errors cannot be communicated via GitHub (e.g. before status post,
or when a user requests a dump). Idle timeout (see bmt_config.IDLE_TIMEOUT_SEC)
keeps the VM warm between triggers so consecutive workflow runs avoid cold starts
and so log-dump requests can be processed on the next poll.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Sane defaults: cap log size and keep a few rotated files to avoid filling disk
LOG_DIR_NAME: str = "logs"
VM_WATCHER_LOG_FILE: str = "vm_watcher.log"
ORCHESTRATOR_LOG_FILE: str = "root_orchestrator.log"
ROTATING_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MiB
ROTATING_BACKUP_COUNT: int = 3
# Max bytes to include in a single GCS log dump (tail of watcher + orchestrator)
DUMP_MAX_BYTES: int = 512 * 1024  # 512 KiB total for vm_watcher + root_orchestrator
DUMP_TOTAL_MAX_BYTES: int = 1024 * 1024  # 1 MiB total dump cap
# Runner log section (when reason_code is runner_failures or runner_timeout)
RUNNER_LOG_MAX_BYTES_PER_FILE: int = 64 * 1024  # 64 KiB per file
RUNNER_LOG_MAX_FILES: int = 20
RUNNER_LOG_MAX_TOTAL_BYTES: int = 512 * 1024  # 512 KiB total for runner section

VM_WATCHER_LOGGER_NAME: str = "gcp.image.vm_watcher"
ORCHESTRATOR_LOGGER_NAME: str = "gcp.image.root_orchestrator"


def _log_dir(workspace_root: Path) -> Path:
    """Directory for VM watcher and orchestrator log files."""
    d = workspace_root / LOG_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _configure_logger(
    log_dir: Path,
    log_file: Path,
    logger_name: str,
    *,
    also_stdout: bool = False,
    level: int = logging.DEBUG,
) -> None:
    """Shared setup: rotating file handler + optional stdout. Clears existing handlers."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    for h in list(logger.handlers):
        logger.removeHandler(h)
    handler = RotatingFileHandler(
        str(log_file),
        maxBytes=ROTATING_MAX_BYTES,
        backupCount=ROTATING_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if also_stdout:
        out = logging.StreamHandler()
        out.setLevel(logging.INFO)
        out.setFormatter(formatter)
        logger.addHandler(out)


def configure_vm_watcher_logging(
    workspace_root: Path,
    *,
    also_stdout: bool = True,
) -> None:
    """Configure rotating file (and optional stdout) logging for vm_watcher.

    Log file: workspace_root/logs/vm_watcher.log, with rotation by size.
    Callers pass bucket and runtime_bucket_root explicitly to dump_logs_to_gcs.
    """
    log_dir = _log_dir(workspace_root)
    log_file = log_dir / VM_WATCHER_LOG_FILE
    _configure_logger(log_dir, log_file, VM_WATCHER_LOGGER_NAME, also_stdout=also_stdout)


def configure_orchestrator_logging(workspace_root: Path, *, also_stdout: bool = False) -> None:
    """Configure rotating file logging for root_orchestrator (runs as subprocess of vm_watcher)."""
    log_dir = _log_dir(workspace_root)
    log_file = log_dir / ORCHESTRATOR_LOG_FILE
    _configure_logger(
        log_dir,
        log_file,
        ORCHESTRATOR_LOGGER_NAME,
        also_stdout=also_stdout,
        level=logging.DEBUG,
    )


def get_recent_log_content(
    workspace_root: Path,
    *,
    include_orchestrator: bool = True,
    max_bytes: int = DUMP_MAX_BYTES,
) -> str:
    """Read the tail of vm_watcher (and optionally root_orchestrator) log files.

    Uses tail-only reads (seek + read) to avoid loading full files. Returns up to
    max_bytes of the most recent log content per source, total capped at max_bytes.
    """
    log_dir = workspace_root / LOG_DIR_NAME
    parts: list[str] = []
    # Split budget between the two log sources
    per_source = max(4096, max_bytes // 2) if include_orchestrator else max_bytes

    def tail_one(basename: str, label: str, budget: int) -> None:
        primary = log_dir / basename
        candidates: list[tuple[int, Path]] = []
        if primary.is_file():
            candidates.append((0, primary))
        for i in range(1, ROTATING_BACKUP_COUNT + 1):
            p = log_dir / f"{basename}.{i}"
            if p.is_file():
                candidates.append((i, p))
        candidates.sort(key=lambda x: x[0])
        collected = bytearray()
        for _, path in candidates:
            try:
                size = path.stat().st_size
                with path.open("rb") as f:
                    f.seek(max(0, size - budget))
                    chunk = f.read()
                collected.extend(chunk)
            except OSError:
                continue
        if len(collected) > budget:
            collected = collected[-budget:]
        if collected:
            text = collected.decode("utf-8", errors="replace")
            parts.append(f"--- {label} ---\n{text}")

    tail_one(VM_WATCHER_LOG_FILE, "vm_watcher", per_source)
    if include_orchestrator:
        tail_one(ORCHESTRATOR_LOG_FILE, "root_orchestrator", per_source)

    return "\n".join(parts) if parts else "(no log files found)"


def _log_dumps_prefix(runtime_bucket_root: str) -> str:
    """Object prefix for log-dump objects (no leading slash)."""
    prefix = (runtime_bucket_root or "").strip().strip("/")
    if prefix:
        return f"{prefix}/log-dumps"
    return "log-dumps"


def _log_dump_requests_prefix(runtime_bucket_root: str) -> str:
    """Object prefix for log-dump request objects."""
    prefix = (runtime_bucket_root or "").strip().strip("/")
    if prefix:
        return f"{prefix}/log-dump-requests"
    return "log-dump-requests"


def _append_runner_log_tail(
    run_root: Path,
    content: list[str],
    *,
    max_bytes_per_file: int = RUNNER_LOG_MAX_BYTES_PER_FILE,
    max_files: int = RUNNER_LOG_MAX_FILES,
    max_total_bytes: int = RUNNER_LOG_MAX_TOTAL_BYTES,
) -> None:
    """Append tail of runner log files from run_root/logs/ to content. Safe I/O with caps."""
    logs_dir = run_root / "logs"
    if not logs_dir.is_dir():
        return
    candidates: list[Path] = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)
    total = 0
    for path in candidates[:max_files]:
        if total >= max_total_bytes:
            break
        try:
            size = path.stat().st_size
            with path.open("rb") as f:
                f.seek(max(0, size - max_bytes_per_file))
                chunk = f.read(min(max_bytes_per_file, max_total_bytes - total))
            text = chunk.decode("utf-8", errors="replace")
            content.append(f"--- Runner log: {path.name} ---\n{text}")
            total += len(chunk)
        except OSError:
            continue


def log_dump_object_info(
    bucket: str,
    runtime_bucket_root: str,
    object_suffix: str,
) -> tuple[str, str] | None:
    """Return (bucket_name, object_name) for the log-dump object for signing. None if invalid."""
    from gcp.image.gcs_helpers import _parse_gcs_uri

    try:
        if runtime_bucket_root.startswith("gs://"):
            bucket, runtime_bucket_root = _parse_gcs_uri(runtime_bucket_root)
        prefix = _log_dumps_prefix(runtime_bucket_root)
        name = f"{prefix}/{object_suffix}.log" if prefix else f"{object_suffix}.log"
        return (bucket, name)
    except ValueError:
        return None


def dump_logs_to_gcs(
    bucket: str,
    runtime_bucket_root: str,
    object_suffix: str,
    content: str,
) -> bool:
    """Upload log content to GCS at gs://bucket/<runtime_prefix>/log-dumps/<suffix>.log."""
    from gcp.image.gcs_helpers import _gcloud_upload_text, _parse_gcs_uri

    try:
        if runtime_bucket_root.startswith("gs://"):
            bucket, runtime_bucket_root = _parse_gcs_uri(runtime_bucket_root)
        prefix = _log_dumps_prefix(runtime_bucket_root)
        name = f"{prefix}/{object_suffix}.log" if prefix else f"{object_suffix}.log"
        uri = f"gs://{bucket}/{name}"
        return _gcloud_upload_text(uri, content)
    except ValueError:
        return False


def list_log_dump_requests(bucket: str, runtime_bucket_root: str) -> list[str]:
    """List full gs:// URIs of log-dump request objects (caller may then download and delete)."""
    from gcp.image.gcs_helpers import _gcs_list

    prefix = _log_dump_requests_prefix(runtime_bucket_root)
    if prefix:
        list_uri = f"gs://{bucket}/{prefix}/"
    else:
        list_uri = f"gs://{bucket}/log-dump-requests/"
    return _gcs_list(list_uri)


def process_log_dump_requests(
    bucket: str,
    runtime_bucket_root: str,
    workspace_root: Path,
) -> None:
    """If any log-dump request exists, fulfill it, write response with signed URL, then delete (one per call)."""
    from gcp.image.gcs_helpers import (
        LOG_DUMP_SIGNED_URL_EXPIRY_DAYS,
        _gcloud_download_json,
        _gcloud_rm,
        _gcloud_upload_json,
        _parse_gcs_uri,
        generate_signed_url,
    )

    uris = list_log_dump_requests(bucket, runtime_bucket_root)
    if not uris:
        return
    request_uri = uris[0]
    downloaded = _gcloud_download_json(request_uri)
    if isinstance(downloaded, tuple):
        payload, err = downloaded
        if err or not isinstance(payload, dict):
            _gcloud_rm(request_uri)
            return
    else:
        payload = downloaded if isinstance(downloaded, dict) else None
    if not payload:
        _gcloud_rm(request_uri)
        return
    request_id = str(payload.get("request_id") or payload.get("requested_at") or "unknown").strip()
    if not request_id or request_id == "unknown":
        request_id = request_uri.split("/")[-1].replace(".json", "")
    content = get_recent_log_content(workspace_root, include_orchestrator=True)
    suffix = re.sub(r"[^a-zA-Z0-9_.-]", "_", request_id)
    if not dump_logs_to_gcs(bucket, runtime_bucket_root, suffix, content):
        return
    try:
        if runtime_bucket_root.startswith("gs://"):
            bucket, runtime_bucket_root = _parse_gcs_uri(runtime_bucket_root)
    except ValueError:
        _gcloud_rm(request_uri)
        return
    prefix = _log_dumps_prefix(runtime_bucket_root)
    object_name = f"{prefix}/{suffix}.log" if prefix else f"{suffix}.log"
    signed_url = generate_signed_url(bucket, object_name)
    response_payload: dict[str, str | int] = {"expires_in_days": LOG_DUMP_SIGNED_URL_EXPIRY_DAYS}
    if signed_url:
        response_payload["signed_url"] = signed_url
    req_prefix = _log_dump_requests_prefix(runtime_bucket_root)
    response_name = f"{req_prefix}/{request_id}.response.json" if req_prefix else f"{request_id}.response.json"
    response_uri = f"gs://{bucket}/{response_name}"
    _gcloud_upload_json(response_uri, response_payload)
    _gcloud_rm(request_uri)
