"""Load per-case NAMUH-style counters from JSON beside the runner output WAV.

Older ``kardome_runner`` builds print ``Hi … counter = N`` to stdout. New builds should write JSON next to the WAV; filenames and keys are implemented below."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _coerce_namuh_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _extract_namuh_from_obj(obj: Any) -> int | None:
    if not isinstance(obj, dict):
        return None
    for key in ("namuh_count", "hi_namuh_count", "namuh", "hi_namuh"):
        got = _coerce_namuh_int(obj.get(key))
        if got is not None:
            return got
    for nest_key in ("metrics", "bmt", "result"):
        nested = obj.get(nest_key)
        if isinstance(nested, dict):
            got = _extract_namuh_from_obj(nested)
            if got is not None:
                return got
    return None


def _candidate_metric_json_paths(output_wav_path: Path) -> tuple[Path, ...]:
    return (
        output_wav_path.with_suffix(".bmt.json"),
        output_wav_path.parent / f"{output_wav_path.stem}_bmt_result.json",
    )


def read_namuh_from_sidecar_json(output_wav_path: Path) -> tuple[int | None, Path | None]:
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
        value = _extract_namuh_from_obj(data)
        if value is None:
            logger.warning("Metrics JSON %s has no recognized namuh counter field", candidate)
            continue
        return value, candidate
    return None, None
