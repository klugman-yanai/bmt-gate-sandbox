"""Resolve results_prefix from project BMT jobs config (bmt_jobs.json)."""

from __future__ import annotations

import json
from pathlib import Path


def resolve_results_prefix(config_root: str | Path, project: str, bmt_id: str) -> str:
    """Load jobs config for project and return results_prefix for the given bmt_id.

    Jobs path: config_root / projects / project / bmt_jobs.json.
    Returns bmts[bmt_id].paths.results_prefix, stripped of trailing slash.
    """
    root = Path(config_root).resolve()
    jobs_path = root / "projects" / project / "bmt_jobs.json"
    if not jobs_path.is_file():
        raise FileNotFoundError(f"Jobs config not found: {jobs_path}")

    payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    bmts = payload.get("bmts")
    if not isinstance(bmts, dict):
        raise ValueError(f"Invalid jobs schema in {jobs_path}: missing object key 'bmts'")

    bmt_cfg = bmts.get(bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise KeyError(f"BMT id '{bmt_id}' is not defined for project '{project}' in {jobs_path}")

    paths = bmt_cfg.get("paths")
    if not isinstance(paths, dict):
        raise ValueError(f"BMT '{bmt_id}' missing 'paths' in {jobs_path}")

    prefix = paths.get("results_prefix")
    if not prefix or not isinstance(prefix, str):
        raise ValueError(f"BMT '{bmt_id}' missing or invalid 'paths.results_prefix' in {jobs_path}")

    return str(prefix).rstrip("/")
