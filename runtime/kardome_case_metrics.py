"""Per-case JSON beside the user output WAV: legacy key walk, or structured runner execution results (``calibration_kws`` picks the headline metric)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Must match ``case_format.const`` in runtime/schemas/krdm_runner_execution_results_v1.schema.json.
RUNNER_CASE_JSON_FORMAT_V1 = "krdm_runner_execution_results.1"


def _short_kardome_lib_version(raw: str) -> str:
    s = raw.replace("\x00", " ").strip()
    if not s:
        return ""
    return s.split()[0]


def _coerce_numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return value
    return None


def _primary_metric_runner_case_json(data: dict[str, Any]) -> float | None:
    if data.get("calibration_kws") is True:
        return _coerce_numeric(data.get("keyword_calib_count"))
    return _coerce_numeric(data.get("hi_namuh_count"))


def _runner_case_json_artifact_strings(data: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {"case_format": RUNNER_CASE_JSON_FORMAT_V1}
    v = data.get("kardome_lib_version")
    if isinstance(v, str) and v.strip():
        short = _short_kardome_lib_version(v)
        if short:
            out["kardome_lib_version"] = short[:200]
    gleo = data.get("gleo_per_channel")
    if isinstance(gleo, list):
        out["gleo_per_channel_json"] = json.dumps(gleo, separators=(",", ":"), ensure_ascii=False)[:20000]
    p = data.get("paths")
    if isinstance(p, dict):
        for k in ("mics", "refs", "user_output"):
            v = p.get(k)
            if isinstance(v, str):
                out[f"path_{k}"] = v[:2000]
    return out


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


def read_metric_from_bmt_case_json(
    output_wav_path: Path,
    *,
    metric_keys: tuple[str, ...],
    nested_keys: tuple[str, ...] = ("metrics", "bmt", "result"),
) -> tuple[float | None, Path | None, dict[str, str] | None]:
    """Metric value, path to the JSON file used, and optional artifact map for structured runner case output."""
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
        cf = data.get("case_format") if isinstance(data, dict) else None
        if isinstance(data, dict) and isinstance(cf, str) and cf.strip() == RUNNER_CASE_JSON_FORMAT_V1:
            value = _primary_metric_runner_case_json(data)
            if value is None:
                logger.warning("Runner case results JSON %s missing headline counters for mode", candidate)
                continue
            return value, candidate, _runner_case_json_artifact_strings(data)
        value = _extract_metric_from_obj(data, metric_keys=metric_keys, nested_keys=nested_keys)
        if value is None:
            logger.warning("Metrics JSON %s missing configured metric keys: %s", candidate, metric_keys)
            continue
        return value, candidate, None
    return None, None, None


def read_namuh_from_bmt_case_json(output_wav_path: Path) -> tuple[int | None, Path | None]:
    value, path, _ = read_metric_from_bmt_case_json(
        output_wav_path,
        metric_keys=("namuh_count", "hi_namuh_count", "namuh", "hi_namuh"),
    )
    if value is None:
        return None, None
    return int(value), path
