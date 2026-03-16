"""Config loading and validation at the boundary (L2 — imports from L0 constants and L1 models).

Loads JSON config files, validates structure, and returns typed model instances.
No GCS or subprocess dependencies — callers provide the raw JSON or file path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gcp.image.models import BmtJobsConfig, BmtRegistry


def load_jobs_config(path: Path) -> BmtJobsConfig:
    """Load and validate bmt_jobs.json from a local path into a typed BmtJobsConfig."""
    raw = _load_json_file(path)
    _require_key(raw, "bmts", dict, path)
    return BmtJobsConfig.from_dict(raw)


def load_jobs_config_from_dict(data: dict[str, Any]) -> BmtJobsConfig:
    """Validate a parsed dict and return a typed BmtJobsConfig."""
    if not isinstance(data.get("bmts"), dict):
        raise ValueError("jobs config missing or invalid 'bmts' key")
    return BmtJobsConfig.from_dict(data)


def load_registry(path: Path) -> BmtRegistry:
    """Load and validate bmt_projects.json from a local path into a typed BmtRegistry."""
    raw = _load_json_file(path)
    return BmtRegistry.from_dict(raw)


def load_registry_from_dict(data: dict[str, Any]) -> BmtRegistry:
    """Validate a parsed dict and return a typed BmtRegistry."""
    return BmtRegistry.from_dict(data)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return data


def _require_key(data: dict[str, Any], key: str, expected_type: type, source: Path) -> None:
    val = data.get(key)
    if not isinstance(val, expected_type):
        raise ValueError(f"Config {source}: '{key}' must be {expected_type.__name__}, got {type(val).__name__}")
