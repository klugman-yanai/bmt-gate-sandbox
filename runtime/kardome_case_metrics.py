"""Load per-case counters from JSON beside the runner output WAV.

Older ``kardome_runner`` builds print counters to stdout. Newer builds should write
structured JSON next to the WAV; this module extracts a numeric metric value by key.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _coerce_numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return value
    return None


def _extract_metric_from_obj(
    obj: Any,
    *,
    metric_keys: tuple[str, ...],
    nested_keys: tuple[str, ...],
) -> float | None:
    if not isinstance(obj, dict):
        return None
    for key in metric_keys:
        got = _coerce_numeric(obj.get(key))
        if got is not None:
            return got
    for nest_key in nested_keys:
        nested = obj.get(nest_key)
        if isinstance(nested, dict):
            got = _extract_metric_from_obj(nested, metric_keys=metric_keys, nested_keys=nested_keys)
            if got is not None:
                return got
    return None


def _candidate_metric_json_paths(output_wav_path: Path) -> tuple[Path, ...]:
    return (
        output_wav_path.with_suffix(".bmt.json"),
        output_wav_path.parent / f"{output_wav_path.stem}_bmt_result.json",
    )


def read_metric_from_sidecar_json(
    output_wav_path: Path,
    *,
    metric_keys: tuple[str, ...],
    nested_keys: tuple[str, ...] = ("metrics", "bmt", "result"),
) -> tuple[float | None, Path | None]:
    """Read first matching numeric metric from known sidecar JSON locations."""
    for candidate in _candidate_metric_json_paths(output_wav_path):
        if not candidate.is_file():
            continue
        try:
            raw = candidate.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read metrics JSON %s: %s", candidate, exc)
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid metrics JSON %s: %s", candidate, exc)
            continue
        value = _extract_metric_from_obj(data, metric_keys=metric_keys, nested_keys=nested_keys)
        if value is None:
            logger.warning("Metrics JSON %s missing configured metric keys: %s", candidate, metric_keys)
            continue
        return value, candidate
    return None, None


def read_namuh_from_sidecar_json(output_wav_path: Path) -> tuple[int | None, Path | None]:
    """Backward-compatible helper for SK-style NAMUH counters."""
    value, path = read_metric_from_sidecar_json(
        output_wav_path,
        metric_keys=("namuh_count", "hi_namuh_count", "namuh", "hi_namuh"),
    )
    if value is None:
        return None, None
    return int(value), path
