#!/usr/bin/env python3
"""SK project BMT manager.

Runs per-file runner invocations by creating transient JSON configs from
project template and applying BMT-specific runtime overrides.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class SKManagerError(RuntimeError):
    """Raised for manager execution/config errors."""


_FORCED_WAV_PATH_KEYS = {
    "REF_PATH",
    "QUIET_PATH",
    "ZONE1_PATH",
    "ZONE2_PATH",
    "ZONE3_PATH",
    "ZONE4_PATH",
    "ZONE5_PATH",
    "ZONE6_PATH",
    "CALIB_BIN_PATH",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SK project BMT manager")
    _ = parser.add_argument("--bucket", required=True)
    _ = parser.add_argument("--project-id", required=True)
    _ = parser.add_argument("--bmt-id", required=True)
    _ = parser.add_argument("--jobs-config", required=True)
    _ = parser.add_argument("--workspace-root", default=".")
    _ = parser.add_argument("--run-context", choices=["dev", "pr", "manual"], default="manual")
    _ = parser.add_argument("--run-id", default="")
    _ = parser.add_argument("--limit", type=int, default=int(os.environ.get("LIMIT", "0")))
    _ = parser.add_argument(
        "--max-jobs",
        type=int,
        default=int(os.environ.get("MAX_JOBS", str(os.cpu_count() or 4))),
    )
    _ = parser.add_argument("--summary-out", default="manager_summary.json")
    _ = parser.add_argument("--human", action="store_true")
    return parser.parse_args()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _code_bucket_root(bucket: str) -> str:
    return f"gs://{bucket}/code"


def _runtime_bucket_root(bucket: str) -> str:
    return f"gs://{bucket}/runtime"


def _default_cache_root() -> Path:
    preferred = Path("~/bmt_workspace/cache").expanduser()
    legacy = Path("~/sk_runtime/cache").expanduser()
    if legacy.exists() and not preferred.exists():
        print("Warning: using legacy cache root ~/sk_runtime/cache")
        return legacy.resolve()
    return preferred.resolve()


def _bucket_uri(bucket_root: str, path_or_uri: str) -> str:
    if path_or_uri.startswith("gs://"):
        return path_or_uri
    return f"{bucket_root}/{path_or_uri.lstrip('/')}"


def _gcs_exists(uri: str) -> bool:
    proc = subprocess.run(
        ["gcloud", "storage", "ls", uri],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


def _gcloud_cp(src: str, dst: Path | str) -> None:
    dst_path = Path(dst) if not isinstance(dst, Path) else dst
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    _ = subprocess.run(
        ["gcloud", "storage", "cp", src, str(dst_path), "--quiet"], check=True, capture_output=True, text=True
    )


def _gcloud_upload(src: Path, dst_uri: str) -> None:
    _ = subprocess.run(
        ["gcloud", "storage", "cp", str(src), dst_uri, "--quiet"], check=True, capture_output=True, text=True
    )


def _gcloud_rsync(src: str, dst: Path | str, delete: bool = False) -> None:
    dst_path = Path(dst) if not isinstance(dst, Path) else dst
    dst_path.mkdir(parents=True, exist_ok=True)
    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if delete:
        cmd.append("--delete-unmatched-destination-objects")
    cmd.extend([src, str(dst_path), "--quiet"])
    _ = subprocess.run(cmd, check=True, capture_output=True, text=True)


# Exclude Python/uv cache and bloat when uploading dirs to GCS (e.g. logs, outputs).
_UPLOAD_EXCLUDE = (
    r"__pycache__",
    r"\.pyc$",
    r"\.pyo$",
    r"(^|/)\.venv(/|$)",
    r"(^|/)venv(/|$)",
    r"(^|/)\.uv(/|$)",
    r"(^|/)\.mypy_cache(/|$)",
    r"(^|/)\.pytest_cache(/|$)",
    r"(^|/)\.ruff_cache(/|$)",
    r"(^|/)\.tox(/|$)",
    r"(^|/)\.eggs(/|$)",
    r"(^|/)[^/]+\.egg-info(/|$)",
    r"\.egg$",
)


def _gcloud_rsync_to_gcs(src: Path | str, dst_uri: str, delete: bool = False) -> None:
    src_path = Path(src) if not isinstance(src, Path) else src
    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if delete:
        cmd.append("--delete-unmatched-destination-objects")
    for pattern in _UPLOAD_EXCLUDE:
        cmd.extend(["--exclude", pattern])
    cmd.extend([str(src_path), dst_uri, "--quiet"])
    _ = subprocess.run(cmd, check=True, capture_output=True, text=True)


# Compatibility helper aliases used by tests and external monkeypatching.
def bucket_uri(bucket_root: str, path_or_uri: str) -> str:
    return _bucket_uri(bucket_root, path_or_uri)


def gcs_exists(uri: str) -> bool:
    return _gcs_exists(uri)


def gcloud_cp(src: str, dst: Path | str) -> None:
    _gcloud_cp(src, dst)


def _gcloud_ls_json(uri: str, recursive: bool = False) -> list[dict[str, Any]]:
    cmd = ["gcloud", "storage", "ls", "--json"]
    if recursive:
        cmd.append("--recursive")
    cmd.append(uri)
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    out = (proc.stdout or "").strip()
    if not out:
        return []
    data = json.loads(out)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _gcs_object_meta(uri: str) -> dict[str, Any] | None:
    entries = _gcloud_ls_json(uri)
    if not entries:
        return None
    entry = entries[0]
    return {
        "name": str(entry.get("name") or uri),
        "generation": str(entry.get("generation") or ""),
        "size": int(entry.get("size") or 0),
        "updated": str(entry.get("updated") or ""),
    }


def _manifest_digest(entries: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for entry in entries:
        name = str(entry.get("name") or "")
        generation = str(entry.get("generation") or "")
        size = str(entry.get("size") or "")
        if not name:
            continue
        rows.append(f"{name}|{generation}|{size}")
    rows.sort()
    h = hashlib.sha256()
    for row in rows:
        h.update(row.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SKManagerError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _set_dotted(cfg: dict[str, Any], dotted_key: str, value: Any) -> None:
    cursor: dict[str, Any] = cfg
    parts = dotted_key.split(".")
    if not parts:
        return
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value


def _counter_regex(bmt_cfg: dict[str, Any]) -> re.Pattern[str]:
    parsing = bmt_cfg.get("parsing", {})
    if isinstance(parsing, dict):
        pattern = str(parsing.get("counter_pattern", "")).strip()
        if pattern:
            return re.compile(pattern)
        keyword = str(parsing.get("keyword", "NAMUH")).strip()
        return re.compile(rf"Hi {re.escape(keyword)} counter = (\d+)")
    return re.compile(r"Hi NAMUH counter = (\d+)")


def _rewrite_json_paths_for_wav(cfg: dict[str, Any], wav_path: Path, output_path: Path) -> None:
    wav_value = str(wav_path.resolve())
    output_value = str(output_path.resolve())

    cfg["MICS_PATH"] = wav_value
    cfg["KARDOME_OUTPUT_PATH"] = output_value
    if "USER_OUTPUT_PATH" in cfg:
        cfg["USER_OUTPUT_PATH"] = output_value

    for key in _FORCED_WAV_PATH_KEYS:
        if key in cfg:
            cfg[key] = wav_value

    protected = {"MICS_PATH", "KARDOME_OUTPUT_PATH", "USER_OUTPUT_PATH"}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if isinstance(value, (dict, list)):
                    walk(value)
                    continue
                if key in protected:
                    continue
                if isinstance(value, str) and key.endswith("_PATH"):
                    stripped = value.strip()
                    if not stripped or stripped.startswith("/tmp/dummy"):
                        node[key] = wav_value
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(cfg)


def _read_counter(log_path: Path, counter_re: re.Pattern[str]) -> int:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = counter_re.findall(text)
    if not matches:
        return 0
    return int(matches[-1])


def _resolve_last_passing_run_id(bucket_root: str, results_prefix: str) -> str | None:
    """Read current.json from GCS; return last_passing run_id or None if missing/invalid."""
    uri = bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/current.json")
    if not gcs_exists(uri):
        return None
    with tempfile.TemporaryDirectory(prefix="sk_pointer_") as tmp_dir:
        local_path = Path(tmp_dir) / "current.json"
        gcloud_cp(uri, local_path)
        data = _load_json(local_path)
    run_id = data.get("last_passing")
    return str(run_id).strip() if run_id else None


def _read_result_file(
    bucket_root: str, results_prefix: str, filename: str
) -> tuple[float | None, dict[str, Any] | None]:
    uri = bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/{filename}")
    if not gcs_exists(uri):
        return None, None
    with tempfile.TemporaryDirectory(prefix="sk_result_file_") as tmp_dir:
        local_path = Path(tmp_dir) / filename
        gcloud_cp(uri, local_path)
        data = _load_json(local_path)
        score = data.get("aggregate_score")
        return (float(score), data) if score is not None else (None, data)


def _effective_gate_comparison(bmt_id: str, comparison: str) -> str:
    """Normalize comparison and enforce false-reject semantics."""
    normalized = comparison.strip().lower()
    if bmt_id.startswith("false_reject") and normalized == "lte":
        return "gte"
    return normalized


def _all_failures_are_timeouts(file_results: list[dict[str, Any]]) -> bool:
    """True if every non-zero exit in file_results is a timeout (exit_code 124 or error timeout_after_)."""
    failed = [r for r in file_results if int(r.get("exit_code", 0)) != 0]
    if not failed:
        return False
    for r in failed:
        if int(r.get("exit_code", 0)) != 124:
            return False
        err = (r.get("error") or "").strip()
        if err and "timeout_after_" not in err:
            return False
    return True


def _gate_result(
    comparison: str,
    current_score: float,
    last_score: float | None,
    failed_count: int,
    run_context: str,
    tolerance_abs: float = 0.0,
    baseline_zero_is_missing: bool = True,
) -> dict[str, Any]:
    if failed_count > 0:
        return {
            "comparison": comparison,
            "last_score": last_score,
            "current_score": current_score,
            "passed": False,
            "reason": "runner_failures",
        }

    # Treat missing or zero baseline as bootstrap: accept current score as new baseline.
    # Managers that legitimately expect a zero baseline can set baseline_zero_is_missing=False.
    if last_score is None or (baseline_zero_is_missing and last_score == 0):
        return {
            "comparison": comparison,
            "last_score": last_score,
            "current_score": current_score,
            "passed": True,
            "reason": "bootstrap_no_previous_result",
        }

    tol = abs(tolerance_abs)
    if comparison == "gte":
        passed = current_score >= last_score - tol
        reason = "score_gte_last" if passed else "score_below_last"
    elif comparison == "lte":
        passed = current_score <= last_score + tol
        reason = "score_lte_last" if passed else "score_above_last"
    else:
        raise SKManagerError(f"Unsupported gate comparison: {comparison}")

    return {
        "comparison": comparison,
        "last_score": last_score,
        "current_score": current_score,
        "passed": passed,
        "reason": reason,
    }


def _resolve_status(gate: dict[str, Any], warning_policy: dict[str, Any]) -> tuple[str, str]:
    reason = str(gate.get("reason", "unknown"))
    if not bool(gate.get("passed")):
        return "fail", reason

    if reason == "bootstrap_no_previous_result" and bool(warning_policy.get("bootstrap_without_baseline", False)):
        return "warning", "bootstrap_without_baseline"

    return "pass", reason


def _run_one(
    wav_path: Path,
    inputs_root: Path,
    outputs_dir: Path,
    logs_dir: Path,
    runtime_dir: Path,
    runner_path: Path,
    template_cfg: dict[str, Any],
    num_source_test: int | None,
    enable_overrides: dict[str, Any],
    counter_re: re.Pattern[str],
    runner_env: dict[str, str],
) -> dict[str, Any]:
    rel = wav_path.relative_to(inputs_root)
    output_path = outputs_dir / rel
    log_path = logs_dir / rel.with_suffix(rel.suffix + ".log")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = copy.deepcopy(template_cfg)
    _rewrite_json_paths_for_wav(cfg, wav_path, output_path)
    if num_source_test is not None:
        cfg["NUM_SOURCE_TEST"] = int(num_source_test)

    for dotted_key, value in enable_overrides.items():
        _set_dotted(cfg, dotted_key, value)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=runtime_dir, delete=False) as temp_file:
        json.dump(cfg, temp_file, indent=2)
        temp_path = Path(temp_file.name)

    exit_code = 1
    error: str = ""
    try:
        runner_cmd = [str(runner_path), str(temp_path)]
        custom_loader = runner_path.parent / "ld-linux-x86-64.so.2"
        if custom_loader.is_file():
            runner_cmd = [
                str(custom_loader),
                "--library-path",
                str(runner_path.parent.resolve()),
                str(runner_path),
                str(temp_path),
            ]
        with log_path.open("w", encoding="utf-8") as log_file:
            proc = subprocess.run(
                runner_cmd,
                cwd=str(runtime_dir),
                env=runner_env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
            )
            exit_code = proc.returncode
    finally:
        temp_path.unlink(missing_ok=True)

    counter = _read_counter(log_path, counter_re)
    return {
        "file": str(rel),
        "exit_code": exit_code,
        "namuh_count": counter,
        "status": "ok" if exit_code == 0 else "failed",
        "log": str(log_path),
        "output": str(output_path),
        "error": error,
    }


def _mark_cache(cache_stats: dict[str, Any], key: str, hit: bool) -> None:
    cache_stats["states"][key] = "hit" if hit else "miss"
    if hit:
        cache_stats["cache_hits"].append(key)
    else:
        cache_stats["cache_misses"].append(key)


def main() -> int:
    args = parse_args()
    run_id = args.run_id.strip()
    started_at = _now_iso()
    start_timestamp = time.monotonic()
    runtime_bucket_root = _runtime_bucket_root(args.bucket)
    code_bucket_root = _code_bucket_root(args.bucket)
    runtime_prefix = "runtime"

    # Check if progress tracking is enabled
    enable_progress = (
        os.environ.get("BMT_STATUS_BUCKET")
        and os.environ.get("BMT_STATUS_RUN_ID")
        and os.environ.get("BMT_STATUS_LEG_INDEX") is not None
    )
    if enable_progress:
        # Import progress tracking modules
        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        try:
            status_file = importlib.import_module("status_file")
            progress_bucket = os.environ["BMT_STATUS_BUCKET"]
            progress_runtime_prefix = os.environ.get("BMT_STATUS_RUNTIME_PREFIX", runtime_prefix)
            progress_run_id = os.environ["BMT_STATUS_RUN_ID"]
            progress_leg_index = int(os.environ["BMT_STATUS_LEG_INDEX"])
        except (ImportError, ValueError, KeyError):
            enable_progress = False
    else:
        status_file = None  # type: ignore[assignment]
        progress_bucket = None
        progress_runtime_prefix = None
        progress_run_id = None
        progress_leg_index = None

    jobs_cfg = _load_json(Path(args.jobs_config))
    bmts = jobs_cfg.get("bmts", {})
    bmt_cfg = bmts.get(args.bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise SKManagerError(f"Unknown BMT id: {args.bmt_id}")
    if not bool(bmt_cfg.get("enabled", True)):
        raise SKManagerError(f"BMT is disabled: {args.bmt_id}")

    run_root = Path(args.workspace_root).expanduser().resolve()
    staging_dir = run_root / "staging"
    runtime_dir = run_root / "runtime"
    outputs_dir = run_root / "outputs"
    logs_dir = run_root / "logs"
    results_dir = run_root / "results"
    archive_dir = run_root / "archive"
    for d in (staging_dir, runtime_dir, outputs_dir, logs_dir, results_dir, archive_dir):
        d.mkdir(parents=True, exist_ok=True)

    paths_cfg = bmt_cfg.get("paths", {})
    if not isinstance(paths_cfg, dict):
        raise SKManagerError("paths must be an object")

    runner_cfg = bmt_cfg.get("runner", {})
    if not isinstance(runner_cfg, dict):
        raise SKManagerError("runner must be an object")

    runner_uri = _bucket_uri(runtime_bucket_root, str(runner_cfg["uri"]))
    runner_deps_prefix = str(runner_cfg.get("deps_prefix", "")).strip()
    template_uri = _bucket_uri(code_bucket_root, str(bmt_cfg["template_uri"]))
    dataset_uri = _bucket_uri(runtime_bucket_root, str(paths_cfg["dataset_prefix"]))
    outputs_prefix = str(paths_cfg["outputs_prefix"]).rstrip("/")
    results_prefix = str(paths_cfg["results_prefix"]).rstrip("/")
    logs_prefix = str(paths_cfg.get("logs_prefix", f"{results_prefix}/logs")).rstrip("/")

    runtime_cfg = bmt_cfg.get("runtime", {}) if isinstance(bmt_cfg.get("runtime"), dict) else {}
    cache_cfg = runtime_cfg.get("cache", {}) if isinstance(runtime_cfg.get("cache"), dict) else {}
    cache_enabled = bool(cache_cfg.get("enabled", True))
    cache_default = str(_default_cache_root())
    cache_root = Path(str(cache_cfg.get("root", cache_default))).expanduser().resolve()
    dataset_ttl_sec = int(cache_cfg.get("dataset_ttl_sec", 300) or 300)
    cache_base = cache_root / args.project_id / args.bmt_id
    cache_meta_dir = cache_base / "meta"
    cache_runner_dir = cache_base / "runner_bundle"
    cache_template_path = cache_base / "input_template.json"
    cache_dataset_dir = cache_base / "dataset"
    cache_meta_dir.mkdir(parents=True, exist_ok=True)

    cache_stats: dict[str, Any] = {"cache_hits": [], "cache_misses": [], "states": {}}
    sync_durations_sec: dict[str, float] = {}

    # Runner cache
    runner_bundle_uri = runner_uri.rsplit("/", 1)[0].rstrip("/")
    runner_manifest_path = cache_meta_dir / "runner_bundle_meta.json"
    runner_manifest_entries = _gcloud_ls_json(f"{runner_bundle_uri}/", recursive=True)
    if runner_deps_prefix:
        deps_uri = _bucket_uri(runtime_bucket_root, runner_deps_prefix).rstrip("/") + "/"
        runner_manifest_entries.extend(_gcloud_ls_json(deps_uri, recursive=True))
    runner_digest = _manifest_digest(runner_manifest_entries)

    runner_hit = False
    runner_rel_name = Path(runner_uri).name
    runner_path = cache_runner_dir / runner_rel_name
    if cache_enabled and runner_manifest_path.is_file() and runner_path.is_file():
        manifest = _load_json(runner_manifest_path)
        runner_hit = str(manifest.get("digest", "")) == runner_digest

    if not runner_hit:
        t0 = time.monotonic()
        _gcloud_rsync(f"{runner_bundle_uri}/", cache_runner_dir)
        if runner_deps_prefix:
            deps_uri = _bucket_uri(runtime_bucket_root, runner_deps_prefix).rstrip("/") + "/"
            _gcloud_rsync(deps_uri, cache_runner_dir)
        if not runner_path.is_file():
            _gcloud_cp(runner_uri, runner_path)
        sync_durations_sec["runner_bundle_sync"] = round(time.monotonic() - t0, 3)
        _write_json(
            runner_manifest_path,
            {
                "timestamp": _now_iso(),
                "digest": runner_digest,
                "runner_uri": runner_uri,
                "runner_bundle_uri": runner_bundle_uri,
                "deps_prefix": runner_deps_prefix,
            },
        )

    _mark_cache(cache_stats, "runner_bundle", runner_hit)

    # Extract runner binary generation for verdict runner identity.
    runner_build_id = "unknown"
    for _entry in runner_manifest_entries:
        _entry_name = str(_entry.get("name") or "")
        if Path(_entry_name).name == runner_rel_name:
            _gen = str(_entry.get("generation") or "").strip()
            if _gen:
                runner_build_id = _gen
            break

    # Template cache
    template_meta_path = cache_meta_dir / "template_meta.json"
    template_remote_meta = _gcs_object_meta(template_uri)
    if template_remote_meta is None:
        raise SKManagerError(f"Template object missing: {template_uri}")

    template_hit = False
    if cache_enabled and template_meta_path.is_file() and cache_template_path.is_file():
        cached_meta = _load_json(template_meta_path)
        template_hit = str(cached_meta.get("generation", "")) == str(
            template_remote_meta.get("generation", "")
        ) and int(cached_meta.get("size", -1)) == int(template_remote_meta.get("size", -2))

    if not template_hit:
        t0 = time.monotonic()
        _gcloud_cp(template_uri, cache_template_path)
        sync_durations_sec["template_sync"] = round(time.monotonic() - t0, 3)
        _write_json(
            template_meta_path,
            {
                "timestamp": _now_iso(),
                "generation": str(template_remote_meta.get("generation", "")),
                "size": int(template_remote_meta.get("size", 0)),
                "template_uri": template_uri,
            },
        )

    _mark_cache(cache_stats, "template", template_hit)

    # Dataset cache (TTL based)
    dataset_meta_path = cache_meta_dir / "dataset_meta.json"
    dataset_hit = False
    if cache_enabled and dataset_meta_path.is_file() and cache_dataset_dir.is_dir():
        dataset_meta = _load_json(dataset_meta_path)
        last_sync_epoch = float(dataset_meta.get("last_sync_epoch", 0.0) or 0.0)
        age = datetime.now(UTC).timestamp() - last_sync_epoch
        dataset_hit = str(dataset_meta.get("source_uri", "")) == dataset_uri and age <= float(dataset_ttl_sec)

    if cache_enabled:
        if not dataset_hit:
            t0 = time.monotonic()
            _gcloud_rsync(dataset_uri.rstrip("/") + "/", cache_dataset_dir)
            sync_durations_sec["dataset_sync"] = round(time.monotonic() - t0, 3)
            _write_json(
                dataset_meta_path,
                {
                    "timestamp": _now_iso(),
                    "source_uri": dataset_uri,
                    "last_sync_epoch": datetime.now(UTC).timestamp(),
                    "dataset_ttl_sec": dataset_ttl_sec,
                },
            )
        inputs_root = cache_dataset_dir
    else:
        # No persistent dataset cache: always sync into run workspace.
        inputs_root = staging_dir / "inputs"
        t0 = time.monotonic()
        _gcloud_rsync(dataset_uri.rstrip("/") + "/", inputs_root)
        sync_durations_sec["dataset_sync"] = round(time.monotonic() - t0, 3)

    _mark_cache(cache_stats, "dataset", dataset_hit)

    if not runner_path.is_file():
        raise SKManagerError(f"Runner binary missing after sync: {runner_path}")
    if not cache_template_path.is_file():
        raise SKManagerError(f"Template missing after sync: {cache_template_path}")

    runner_path.chmod(runner_path.stat().st_mode | 0o111)
    custom_loader = runner_path.parent / "ld-linux-x86-64.so.2"
    if custom_loader.is_file():
        custom_loader.chmod(custom_loader.stat().st_mode | 0o111)

    runtime_env = dict(os.environ)
    env_overrides = runtime_cfg.get("env_overrides", {}) if isinstance(runtime_cfg.get("env_overrides"), dict) else {}
    if not isinstance(env_overrides, dict):
        raise SKManagerError("runtime.env_overrides must be an object")
    for key, value in env_overrides.items():
        runtime_env[str(key)] = str(value)
    staged_lib_path = str(runner_path.parent.resolve())
    existing_ld = str(runtime_env.get("LD_LIBRARY_PATH", "")).strip()
    runtime_env["LD_LIBRARY_PATH"] = f"{staged_lib_path}:{existing_ld}" if existing_ld else staged_lib_path

    wav_files = sorted(inputs_root.rglob("*.wav"))
    if args.limit > 0:
        wav_files = wav_files[: args.limit]
    if not wav_files:
        raise SKManagerError(f"No wav files found under dataset: {dataset_uri}")

    template_cfg = _load_json(cache_template_path)
    num_source_test = runtime_cfg.get("num_source_test")
    enable_overrides = runtime_cfg.get("enable_overrides", {})
    if not isinstance(enable_overrides, dict):
        raise SKManagerError("runtime.enable_overrides must be an object")

    counter_re = _counter_regex(bmt_cfg)

    total = len(wav_files)
    max_workers = max(1, args.max_jobs)
    file_results: list[dict[str, Any]] = []

    if args.human:
        print(f"Running {args.project_id}.{args.bmt_id} on {total} wav files")

    setup_end_timestamp = time.monotonic()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _run_one,
                wav,
                inputs_root,
                outputs_dir,
                logs_dir,
                runtime_dir,
                runner_path,
                template_cfg,
                int(num_source_test) if num_source_test is not None else None,
                enable_overrides,
                counter_re,
                runtime_env,
            ): wav
            for wav in wav_files
        }
        for idx, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            file_results.append(result)
            if args.human:
                print(f"[{idx}/{total}] {result['file']} count={result['namuh_count']} exit={result['exit_code']}")

            # Update progress in status file
            if enable_progress and status_file:
                with suppress(Exception):
                    status_file.update_leg_progress(
                        progress_bucket,
                        progress_runtime_prefix or runtime_prefix,
                        progress_run_id,
                        progress_leg_index,
                        files_completed=idx,
                        files_total=total,
                    )

    execution_end_timestamp = time.monotonic()
    file_results.sort(key=lambda item: item["file"])
    failed_count = sum(1 for item in file_results if int(item["exit_code"]) != 0)
    raw_score = sum(int(item["namuh_count"]) for item in file_results) / len(file_results) if file_results else 0.0
    aggregate_score = raw_score

    gate_cfg = bmt_cfg.get("gate", {}) if isinstance(bmt_cfg.get("gate"), dict) else {}
    warning_policy = bmt_cfg.get("warning_policy", {}) if isinstance(bmt_cfg.get("warning_policy"), dict) else {}
    demo_cfg = bmt_cfg.get("demo", {}) if isinstance(bmt_cfg.get("demo"), dict) else {}
    demo_force_pass = bool(demo_cfg.get("force_pass", False))
    comparison = _effective_gate_comparison(args.bmt_id, str(gate_cfg.get("comparison", "gte")))
    tolerance_abs = float(gate_cfg.get("tolerance_abs", 0.0) or 0.0)

    # Baseline from pointer-resolved snapshot (current.json -> last_passing -> latest.json).
    last_passing_run_id = _resolve_last_passing_run_id(runtime_bucket_root, results_prefix)
    if last_passing_run_id is None:
        last_score, previous_latest = None, None
    else:
        last_score, previous_latest = _read_result_file(
            runtime_bucket_root, f"{results_prefix}/snapshots/{last_passing_run_id}", "latest.json"
        )
    delta_from_previous = (aggregate_score - last_score) if last_score is not None else None
    gate = _gate_result(comparison, aggregate_score, last_score, failed_count, args.run_context, tolerance_abs)
    status, reason_code = _resolve_status(gate, warning_policy)
    # Distinguish timeout from other runner failures so UI and logs show the root cause.
    if reason_code == "runner_failures" and failed_count > 0 and _all_failures_are_timeouts(file_results):
        reason_code = "runner_timeout"
        gate = {**gate, "reason": "runner_timeout"}
    if demo_force_pass and status == "fail":
        status = "pass"
        reason_code = "demo_force_pass"

    ts_iso = _now_iso()
    ts_compact = _now_stamp()
    snapshot_id = run_id or f"local_{ts_compact}"
    snapshot_prefix = f"{results_prefix}/snapshots/{snapshot_id}"
    latest_local = results_dir / "latest.json"

    result = {
        "timestamp": ts_iso,
        "project_id": args.project_id,
        "bmt_id": args.bmt_id,
        "status": status,
        "reason_code": reason_code,
        "demo_force_pass": demo_force_pass,
        "aggregate_score": aggregate_score,
        "raw_aggregate_score": raw_score,
        "delta_from_previous": delta_from_previous,
        "failed_count": failed_count,
        "gate": gate,
        "file_results": file_results,
        "previous_latest": previous_latest,
        "artifacts": {
            "runner_uri": runner_uri,
            "template_uri": template_uri,
            "dataset_uri": dataset_uri,
            "results_prefix": results_prefix,
            "logs_prefix": logs_prefix,
            "outputs_prefix": outputs_prefix,
        },
        "cache_stats": cache_stats,
        "sync_stats": {"sync_durations_sec": sync_durations_sec},
    }

    _write_json(latest_local, result)

    artifact_upload_stats: dict[str, Any] = {
        "uploaded_results": [],
        "logs_uploaded": False,
        "outputs_uploaded": False,
        "durations_sec": {},
    }

    # Upload all results under snapshot prefix (no canonical writes).
    t0 = time.monotonic()
    _gcloud_upload(latest_local, _bucket_uri(runtime_bucket_root, f"{snapshot_prefix}/latest.json"))
    artifact_upload_stats["durations_sec"]["results_latest_upload"] = round(time.monotonic() - t0, 3)
    artifact_upload_stats["uploaded_results"].append("latest.json")

    ci_verdict_uri = ""
    if run_id:
        finished_at = _now_iso()
        ci_verdict: dict[str, Any] = {
            "run_id": run_id,
            "project_id": args.project_id,
            "bmt_id": args.bmt_id,
            "status": status,
            "reason_code": reason_code,
            "aggregate_score": aggregate_score,
            "runner": {
                "name": runner_rel_name,
                "build_id": runner_build_id,
                "source_ref": "",
            },
            "gate": gate,
            "timestamps": {
                "started_at": started_at,
                "finished_at": finished_at,
            },
            "artifacts": {
                "latest_json_uri": _bucket_uri(runtime_bucket_root, f"{snapshot_prefix}/latest.json"),
                "logs_uri": _bucket_uri(runtime_bucket_root, f"{snapshot_prefix}/logs"),
            },
        }
        verdict_local = results_dir / "ci_verdicts" / f"{run_id}.json"
        _write_json(verdict_local, ci_verdict)
        ci_verdict_uri = _bucket_uri(runtime_bucket_root, f"{snapshot_prefix}/ci_verdict.json")
        t0 = time.monotonic()
        _gcloud_upload(verdict_local, ci_verdict_uri)
        artifact_upload_stats["durations_sec"]["ci_verdict_upload"] = round(time.monotonic() - t0, 3)
        artifact_upload_stats["uploaded_results"].append("ci_verdict.json")

    # Upload logs under snapshot prefix only.
    t0 = time.monotonic()
    _gcloud_rsync_to_gcs(
        logs_dir,
        _bucket_uri(runtime_bucket_root, f"{snapshot_prefix}/logs"),
        delete=True,
    )
    artifact_upload_stats["durations_sec"]["logs_upload"] = round(time.monotonic() - t0, 3)
    artifact_upload_stats["logs_uploaded"] = True

    # Upload outputs only when explicitly enabled for the current context.
    artifacts_cfg = bmt_cfg.get("artifacts", {}) if isinstance(bmt_cfg.get("artifacts"), dict) else {}
    upload_outputs_enabled = bool(artifacts_cfg.get("upload_outputs", False))
    upload_outputs_contexts_raw = artifacts_cfg.get("upload_outputs_contexts", ["manual"])
    upload_outputs_contexts = {
        str(item).strip()
        for item in (upload_outputs_contexts_raw if isinstance(upload_outputs_contexts_raw, list) else [])
        if str(item).strip()
    }
    context_allowed = not upload_outputs_contexts or args.run_context in upload_outputs_contexts
    should_upload_outputs = upload_outputs_enabled and context_allowed

    artifact_upload_stats["upload_outputs_enabled"] = upload_outputs_enabled
    artifact_upload_stats["upload_outputs_contexts"] = sorted(upload_outputs_contexts)
    artifact_upload_stats["run_context"] = args.run_context

    if should_upload_outputs:
        t0 = time.monotonic()
        _gcloud_rsync_to_gcs(
            outputs_dir,
            _bucket_uri(runtime_bucket_root, outputs_prefix),
            delete=False,
        )
        artifact_upload_stats["durations_sec"]["outputs_upload"] = round(time.monotonic() - t0, 3)
        artifact_upload_stats["outputs_uploaded"] = True

    # Calculate orchestration timing
    completed_at = _now_iso()
    total_duration_sec = int(time.monotonic() - start_timestamp)
    setup_sec = int(setup_end_timestamp - start_timestamp)
    execution_sec = int(execution_end_timestamp - setup_end_timestamp)
    upload_sec = total_duration_sec - setup_sec - execution_sec

    manager_summary = {
        "timestamp": ts_iso,
        "project_id": args.project_id,
        "bmt_id": args.bmt_id,
        "run_context": args.run_context,
        "run_id": run_id,
        "status": status,
        "reason_code": reason_code,
        "demo_force_pass": demo_force_pass,
        "passed": bool(gate["passed"]),
        "reason": gate.get("reason"),
        "aggregate_score": aggregate_score,
        "raw_aggregate_score": raw_score,
        "last_score": gate.get("last_score"),
        "gate": gate,
        "delta_from_previous": delta_from_previous,
        "failed_count": failed_count,
        "latest_json": str(latest_local),
        "ci_verdict_uri": ci_verdict_uri,
        "cache_stats": cache_stats,
        "sync_stats": {"sync_durations_sec": sync_durations_sec},
        "artifact_upload_stats": artifact_upload_stats,
        "orchestration_timing": {
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_sec": total_duration_sec,
            "stages": {
                "setup_sec": setup_sec,
                "execution_sec": execution_sec,
                "upload_sec": upload_sec,
            },
        },
    }
    _write_json(Path(args.summary_out), manager_summary)

    state = status.upper()
    print(f"SK_BMT_GATE={state} BMT={args.bmt_id} SCORE={aggregate_score:.3f} " + f"RAW={raw_score:.3f}")

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SKManagerError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(2) from None
