"""BMT config: optional JSON file with env overlay; built-in defaults if file missing (stdlib only)."""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = ".github/bmt/config/bmt-config.json"
_CONFIG_CACHE: BmtConfig | None = None


@dataclass(frozen=True)
class BmtConfig:
    """Central BMT/GCP config. Required fields must be set (by file or env)."""

    gcs_bucket: str
    gcp_wif_provider: str
    gcp_sa_email: str
    gcp_project: str
    gcp_zone: str
    bmt_vm_name: str
    bmt_status_context: str = "BMT Gate"
    bmt_runtime_context: str = "BMT Runtime"
    bmt_runtime_backend: str = ""
    bmt_cloud_run_job: str = ""
    bmt_cloud_run_region: str = ""
    bmt_pubsub_topic: str = ""
    bmt_handshake_timeout_sec: int = 180
    bmt_preempt_on_pr_stale_queue: str = "1"
    bmt_trigger_stale_sec: int = 900
    bmt_trigger_metadata_keep_recent: int = 2

    def require_gcp(self) -> None:
        """Raise if any required GCP/BMT field is empty."""
        for name in (
            "gcs_bucket",
            "gcp_wif_provider",
            "gcp_sa_email",
            "gcp_project",
            "gcp_zone",
            "bmt_vm_name",
        ):
            val = getattr(self, name)
            if not (val and str(val).strip()):
                raise RuntimeError(f"Required config {name!r} is not set or empty")


def _coerce_int(val: Any, default: int) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def load_bmt_config(
    config_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> BmtConfig:
    """Load BMT config from JSON file, overlay env (env wins). Return BmtConfig."""
    env_dict: dict[str, str] = dict(env) if env is not None else dict(os.environ)
    path_str_raw = config_path or env_dict.get("BMT_CONFIG_PATH") or DEFAULT_CONFIG_PATH
    path_str = str(path_str_raw).strip() if path_str_raw else DEFAULT_CONFIG_PATH
    path = Path(path_str)
    if not path.is_absolute():
        cwd = env_dict.get("GITHUB_WORKSPACE") or os.getcwd()
        path = Path(cwd) / path

    raw: dict[str, Any] = {}
    if path.is_file():
        with contextlib.suppress(OSError, json.JSONDecodeError):
            raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raw = {}

    def _get(key: str, default: str = "") -> str:
        env_key = key.upper()
        if env_key in env_dict and str(env_dict.get(env_key, "")).strip():
            return str(env_dict[env_key]).strip()
        return str(raw.get(key, default) or "").strip()

    return BmtConfig(
        gcs_bucket=_get("GCS_BUCKET"),
        gcp_wif_provider=_get("GCP_WIF_PROVIDER"),
        gcp_sa_email=_get("GCP_SA_EMAIL"),
        gcp_project=_get("GCP_PROJECT"),
        gcp_zone=_get("GCP_ZONE"),
        bmt_vm_name=_get("BMT_VM_NAME"),
        bmt_status_context=_get("BMT_STATUS_CONTEXT", "BMT Gate"),
        bmt_runtime_context=_get("BMT_RUNTIME_CONTEXT", "BMT Runtime"),
        bmt_runtime_backend=_get("BMT_RUNTIME_BACKEND"),
        bmt_cloud_run_job=_get("BMT_CLOUD_RUN_JOB"),
        bmt_cloud_run_region=_get("BMT_CLOUD_RUN_REGION"),
        bmt_pubsub_topic=_get("BMT_PUBSUB_TOPIC"),
        bmt_handshake_timeout_sec=_coerce_int(_get("BMT_HANDSHAKE_TIMEOUT_SEC") or "180", 180),
        bmt_preempt_on_pr_stale_queue=_get("BMT_PREEMPT_ON_PR_STALE_QUEUE", "1"),
        bmt_trigger_stale_sec=_coerce_int(_get("BMT_TRIGGER_STALE_SEC") or "900", 900),
        bmt_trigger_metadata_keep_recent=_coerce_int(
            _get("BMT_TRIGGER_METADATA_KEEP_RECENT") or "2", 2
        ),
    )


def get_config() -> BmtConfig:
    """Load config once and cache. Use for CLI entrypoints."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_bmt_config()
    return _CONFIG_CACHE


def reset_config_cache() -> None:
    """Clear the config cache. Use from tests to force reload."""
    global _CONFIG_CACHE
    _CONFIG_CACHE = None
