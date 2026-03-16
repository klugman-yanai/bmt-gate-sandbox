#!/usr/bin/env python3
"""Abstract base class for BMT managers.

Provides the generic orchestration skeleton (GCS caching, artifact upload,
gate evaluation, summary generation). Concrete subclasses implement the
project-specific parts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from pathlib import Path
from typing import Any

import orjson
from google.api_core import exceptions as gcs_exceptions
from google.cloud import storage as gcs_storage

try:
    from utils import (
        _bucket_uri,
        _now_iso,
        _now_stamp,
        _parse_gcs_uri as _utils_parse_gcs_uri,
        _runtime_bucket_root,
    )
except ImportError:
    from gcp.image.utils import (
        _bucket_uri,
        _now_iso,
        _now_stamp,
        _parse_gcs_uri as _utils_parse_gcs_uri,
        _runtime_bucket_root,
    )


# ---------------------------------------------------------------------------
# Module-level helpers (GCS / cache)
# ---------------------------------------------------------------------------

_gcs_client_holder: list[gcs_storage.Client | None] = [None]


def _get_gcs_client() -> gcs_storage.Client:
    if _gcs_client_holder[0] is None:
        _gcs_client_holder[0] = gcs_storage.Client()
    return _gcs_client_holder[0]


def _run_gcloud_capture_stderr(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run gcloud command; on failure log captured stderr then re-raise."""
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        if proc.stderr:
            logging.getLogger(__name__).warning("gcloud stderr: %s", proc.stderr.strip())
        if proc.stdout and proc.returncode != 0:
            logging.getLogger(__name__).info("gcloud stdout: %s", proc.stdout.strip())
        proc.check_returncode()
    return proc


# Exclude Python/uv cache and bloat when uploading dirs to GCS.
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


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return orjson.loads(path.read_bytes())  # type: ignore[no-any-return]


def _write_runner_config(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON config for a single runner invocation (e.g. kardome_runner).

    Uses orjson for speed. All BMTs/runners should use this for the same dump
    pattern per run.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2) + b"\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2) + b"\n")


def _default_cache_root() -> Path:
    preferred = Path("~/bmt_workspace/cache").expanduser()
    legacy = Path("~/sk_runtime/cache").expanduser()
    if legacy.exists() and not preferred.exists():
        return legacy.resolve()
    return preferred.resolve()


def _gcs_exists(uri: str) -> bool:
    bucket_name, blob_name = _utils_parse_gcs_uri(uri)
    try:
        return _get_gcs_client().bucket(bucket_name).blob(blob_name).exists()
    except (gcs_exceptions.GoogleAPICallError, OSError):
        return False


def _gcs_download_to_path(uri: str, dst: Path | str) -> None:
    """Download a single GCS object to a local path. Raises on 404/auth/network."""
    dst_path = Path(dst) if not isinstance(dst, Path) else dst
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    bucket_name, blob_name = _utils_parse_gcs_uri(uri)
    blob = _get_gcs_client().bucket(bucket_name).blob(blob_name)
    try:
        blob.download_to_filename(str(dst_path))
    except gcs_exceptions.NotFound:
        raise FileNotFoundError(f"GCS object not found: {uri}") from None
    except (gcs_exceptions.GoogleAPICallError, OSError):
        logging.getLogger(__name__).exception("Failed to download %s", uri)
        raise


def _gcs_upload_from_path(src: Path | str, dst_uri: str, content_type: str | None = None) -> None:
    """Upload a local file to GCS. Raises on auth/network error."""
    src_path = Path(src) if not isinstance(src, Path) else src
    bucket_name, blob_name = _utils_parse_gcs_uri(dst_uri)
    blob = _get_gcs_client().bucket(bucket_name).blob(blob_name)
    try:
        blob.upload_from_filename(str(src_path), content_type=content_type)
    except (gcs_exceptions.GoogleAPICallError, OSError):
        logging.getLogger(__name__).exception("Failed to upload %s -> %s", src_path, dst_uri)
        raise


def _gcloud_cp(src: str, dst: Path | str) -> None:
    """Download from GCS to local path (SDK-based). Kept name for callers."""
    _gcs_download_to_path(src, dst)


def _gcloud_upload(src: Path, dst_uri: str) -> None:
    """Upload local file to GCS (SDK-based). Kept name for callers."""
    ct = "application/json" if src.suffix.lower() == ".json" else None
    _gcs_upload_from_path(src, dst_uri, content_type=ct)


def _gcloud_rsync(src: str, dst: Path | str, *, delete: bool = False) -> None:
    dst_path = Path(dst) if not isinstance(dst, Path) else dst
    dst_path.mkdir(parents=True, exist_ok=True)
    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if delete:
        cmd.append("--delete-unmatched-destination-objects")
    cmd.extend([src, str(dst_path), "--quiet"])
    _run_gcloud_capture_stderr(cmd)


def _gcloud_rsync_to_gcs(src: Path | str, dst_uri: str, *, delete: bool = False) -> None:
    src_path = Path(src) if not isinstance(src, Path) else src
    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if delete:
        cmd.append("--delete-unmatched-destination-objects")
    for pattern in _UPLOAD_EXCLUDE:
        cmd.extend(["--exclude", pattern])
    cmd.extend([str(src_path), dst_uri, "--quiet"])
    _run_gcloud_capture_stderr(cmd)


def _gcloud_ls_json(uri: str, *, recursive: bool = False) -> list[dict[str, Any]]:
    cmd = ["gcloud", "storage", "ls", "--json"]
    if recursive:
        cmd.append("--recursive")
    cmd.append(uri)
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        if proc.stderr:
            logging.getLogger(__name__).warning("gcloud ls stderr: %s", proc.stderr.strip())
        return []
    out = (proc.stdout or "").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
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


def _mark_cache(cache_stats: dict[str, Any], key: str, *, hit: bool) -> None:
    cache_stats["states"][key] = "hit" if hit else "miss"
    if hit:
        cache_stats["cache_hits"].append(key)
    else:
        cache_stats["cache_misses"].append(key)


# ---------------------------------------------------------------------------
# Gate helpers
# ---------------------------------------------------------------------------


def _normalize_comparison(comparison: str) -> str:
    """Normalize and validate comparison for baseline gte/lte.

    Used by projects that implement baseline comparison in their _evaluate_gate
    (e.g. SK). Not used by the base; gate logic lives in project managers.
    """
    normalized = comparison.strip().lower()
    if normalized not in ("gte", "lte"):
        raise ValueError(f"gate.comparison must be 'gte' or 'lte', got: {comparison!r}")
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
    _run_context: str,
    tolerance_abs: float = 0.0,
    *,
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
        raise ValueError(f"Unsupported gate comparison: {comparison}")

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


def _resolve_last_passing_run_id(bucket_root: str, results_prefix: str) -> str | None:
    """Read current.json from GCS; return last_passing run_id or None if missing/invalid."""
    uri = _bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/current.json")
    bucket_name, blob_name = _utils_parse_gcs_uri(uri)
    blob = _get_gcs_client().bucket(bucket_name).blob(blob_name)
    try:
        if not blob.exists():
            return None
        text = blob.download_as_text(encoding="utf-8")
    except gcs_exceptions.NotFound:
        return None
    except (gcs_exceptions.GoogleAPICallError, OSError):
        logging.getLogger(__name__).exception("Failed to read pointer %s", uri)
        raise
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logging.getLogger(__name__).warning("Invalid JSON at %s: %s", uri, exc)
        return None
    run_id = data.get("last_passing")
    return str(run_id).strip() if run_id else None


def _read_result_file(
    bucket_root: str, results_prefix: str, filename: str
) -> tuple[float | None, dict[str, Any] | None]:
    """Read a result file (e.g. latest.json) from GCS. Returns (aggregate_score, data) or (None, None) on 404."""
    uri = _bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/{filename}")
    bucket_name, blob_name = _utils_parse_gcs_uri(uri)
    blob = _get_gcs_client().bucket(bucket_name).blob(blob_name)
    try:
        if not blob.exists():
            return None, None
        text = blob.download_as_text(encoding="utf-8")
    except gcs_exceptions.NotFound:
        return None, None
    except (gcs_exceptions.GoogleAPICallError, OSError):
        logging.getLogger(__name__).exception("Failed to read result file %s", uri)
        raise
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logging.getLogger(__name__).warning("Invalid JSON at %s: %s", uri, exc)
        return None, None
    score = data.get("aggregate_score")
    return (float(score), data) if score is not None else (None, data)


# ---------------------------------------------------------------------------
# Common arg parser
# ---------------------------------------------------------------------------


def parse_args(parser: argparse.ArgumentParser | None = None) -> argparse.Namespace:
    """Parse the common BMT manager arguments.

    Callers may pass a pre-constructed parser (e.g. one that already has
    project-specific arguments added) so that --help and usage reflect all
    options.
    """
    if parser is None:
        parser = argparse.ArgumentParser(description="Run BMT manager")
    _ = parser.add_argument("--bucket", required=True)
    _ = parser.add_argument("--project-id", required=True)
    _ = parser.add_argument("--bmt-id", required=True)
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


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class BmtManagerBase(ABC):
    """Abstract orchestrator for a single BMT run.

    Subclasses implement the project-specific parts via the abstract methods
    below.  The generic orchestration loop lives in :meth:`run`.
    """

    def __init__(self, args: argparse.Namespace, bmt_cfg: dict[str, Any]) -> None:
        self.args = args
        self.bmt_cfg = bmt_cfg

        # Core identifiers
        self.bucket: str = args.bucket
        self.project_id: str = args.project_id
        self.bmt_id: str = args.bmt_id
        self.run_id: str = args.run_id.strip()
        self.run_context: str = args.run_context
        self.max_jobs: int = max(1, args.max_jobs)
        self.limit: int = args.limit
        self.human: bool = args.human
        self.summary_out: Path = Path(args.summary_out)

        # Bucket root (1:1 mirror of gcp/stage; no runtime/ prefix)
        self.runtime_bucket_root: str = _runtime_bucket_root(args.bucket)

        # Local repo root (baked into VM image via Packer)
        try:
            from config.constants import DEFAULT_REPO_ROOT as _DEFAULT_REPO_ROOT  # type: ignore[import]
        except ImportError:
            try:
                from gcp.image.config.constants import DEFAULT_REPO_ROOT as _DEFAULT_REPO_ROOT
            except ImportError:
                _DEFAULT_REPO_ROOT = "/opt/bmt"
        self.repo_root: Path = Path(os.environ.get("BMT_REPO_ROOT", _DEFAULT_REPO_ROOT))

        # Workspace dirs (populated by _setup_dirs)
        self.workspace_root: Path = Path(args.workspace_root).expanduser().resolve()
        self.run_root: Path = self.workspace_root
        self.staging_dir: Path = self.run_root / "staging"
        self.runtime_dir: Path = self.run_root / "runtime"
        self.outputs_dir: Path = self.run_root / "outputs"
        self.logs_dir: Path = self.run_root / "logs"
        self.results_dir: Path = self.run_root / "results"
        self.archive_dir: Path = self.run_root / "archive"

        # Cache config
        runtime_cfg = bmt_cfg.get("runtime", {}) if isinstance(bmt_cfg.get("runtime"), dict) else {}
        self.runtime_cfg: dict[str, Any] = runtime_cfg
        cache_cfg = runtime_cfg.get("cache", {}) if isinstance(runtime_cfg.get("cache"), dict) else {}
        self.cache_cfg: dict[str, Any] = cache_cfg
        self.cache_enabled: bool = bool(cache_cfg.get("enabled", True))
        cache_default = str(_default_cache_root())
        self.cache_root: Path = Path(str(cache_cfg.get("root", cache_default))).expanduser().resolve()
        cache_base = self.cache_root / args.project_id / args.bmt_id
        self.cache_base: Path = cache_base
        self.cache_meta_dir: Path = cache_base / "meta"

    def _setup_dirs(self) -> None:
        """Create all workspace directories."""
        for d in (
            self.staging_dir,
            self.runtime_dir,
            self.outputs_dir,
            self.logs_dir,
            self.results_dir,
            self.archive_dir,
            self.cache_meta_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def setup_assets(self) -> None:
        """Download/cache runner, template, and any other assets needed before
        execution.  Called after workspace dirs are created.  Should populate
        ``self.runner_path`` (or equivalent) and update ``self.cache_stats``
        and ``self.sync_durations_sec`` as appropriate."""

    @abstractmethod
    def collect_input_files(self, inputs_root: Path) -> list[Path]:
        """Return the list of input files to process."""

    @abstractmethod
    def run_file(self, input_file: Path, inputs_root: Path) -> dict[str, Any]:
        """Run BMT on a single input file.

        Returns a result dict containing at minimum:
        - ``'file'``: str - relative path
        - ``'exit_code'``: int
        - ``'status'``: ``'ok'`` | ``'failed'``
        - ``'error'``: str
        """

    @abstractmethod
    def compute_score(self, file_results: list[dict[str, Any]]) -> float:
        """Compute aggregate score from per-file results."""

    @abstractmethod
    def get_runner_identity(self) -> dict[str, Any]:
        """Return a dict describing the runner (name, build_id, source_ref, …)."""

    # ------------------------------------------------------------------
    # Inputs root (may be overridden by setup_assets)
    # ------------------------------------------------------------------

    def get_inputs_root(self) -> Path:
        """Return the root directory containing input files.

        ``setup_assets`` should set ``self._inputs_root`` before this is
        called; the default falls back to ``staging_dir/inputs``.
        """
        return getattr(self, "_inputs_root", self.staging_dir / "inputs")

    # ------------------------------------------------------------------
    # Artifact URIs (may be overridden)
    # ------------------------------------------------------------------

    def _artifact_uris(self) -> dict[str, str]:
        """Return the artifact URI dict written into latest.json."""
        return {}

    # ------------------------------------------------------------------
    # Gate evaluation (project-specific; no default in base)
    # ------------------------------------------------------------------

    @abstractmethod
    def _evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compute pass/fail for this run.

        Each project implements this. Return a dict with at least: passed (bool),
        reason (str), and optionally current_score, last_score, comparison.
        The base does not interpret bmt_cfg[\"gate\"]; projects that use
        baseline gte/lte can read comparison and tolerance_abs from config and
        call _gate_result from this package.
        """
        ...

    # ------------------------------------------------------------------
    # Main orchestration loop
    # ------------------------------------------------------------------

    def _run_worker_pool(
        self,
        input_files: list[Path],
        inputs_root: Path,
        total: int,
        *,
        enable_progress: bool,
        status_file: Any,
        progress_bucket: str | None,
        progress_runtime_prefix: str | None,
        progress_run_id: str | None,
        progress_leg_index: int | None,
        runtime_prefix: str,
    ) -> tuple[list[dict[str, Any]], float]:
        """Run the file loop in a thread pool; return (file_results, execution_end_timestamp)."""
        file_results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.max_jobs) as pool:
            futures = {pool.submit(self.run_file, f, inputs_root): f for f in input_files}
            for idx, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                file_results.append(result)
                if self.human:
                    pass
                if (
                    enable_progress
                    and status_file
                    and progress_bucket is not None
                    and progress_run_id is not None
                    and progress_leg_index is not None
                ):
                    with suppress(Exception):
                        status_file.update_leg_progress(
                            progress_bucket,
                            progress_runtime_prefix or runtime_prefix,
                            progress_run_id,
                            progress_leg_index,
                            files_completed=idx,
                            files_total=total,
                        )
        return file_results, time.monotonic()

    def _run_gate_phase(
        self,
        file_results: list[dict[str, Any]],
        results_prefix: str,
        outputs_prefix: str,
    ) -> tuple[str, str, dict[str, Any], float, float, float | None, int, dict[str, Any] | None, bool]:
        """Evaluate gate and resolve status. Returns status, reason_code, gate, aggregate_score, raw_score, delta_from_previous, failed_count, previous_latest, demo_force_pass."""
        file_results_sorted = sorted(file_results, key=lambda item: item["file"])
        failed_count = sum(1 for item in file_results_sorted if int(item["exit_code"]) != 0)
        aggregate_score = self.compute_score(file_results_sorted)
        raw_score = aggregate_score
        warning_policy = (
            self.bmt_cfg.get("warning_policy", {}) if isinstance(self.bmt_cfg.get("warning_policy"), dict) else {}
        )
        demo_cfg = self.bmt_cfg.get("demo", {}) if isinstance(self.bmt_cfg.get("demo"), dict) else {}
        demo_force_pass = bool(demo_cfg.get("force_pass", False))

        last_passing_run_id = _resolve_last_passing_run_id(self.runtime_bucket_root, results_prefix)
        if last_passing_run_id is None:
            last_score: float | None = None
            previous_latest = None
        else:
            last_score, previous_latest = _read_result_file(
                self.runtime_bucket_root,
                f"{results_prefix}/snapshots/{last_passing_run_id}",
                "latest.json",
            )
        delta_from_previous = (aggregate_score - last_score) if last_score is not None else None
        gate = self._evaluate_gate(aggregate_score, last_score, failed_count, file_results_sorted)
        status, reason_code = _resolve_status(gate, warning_policy)
        if reason_code == "runner_failures" and failed_count > 0 and _all_failures_are_timeouts(file_results_sorted):
            reason_code = "runner_timeout"
            gate = {**gate, "reason": "runner_timeout"}
        if demo_force_pass and status == "fail":
            status = "pass"
            reason_code = "demo_force_pass"
        return (
            status,
            reason_code,
            gate,
            aggregate_score,
            raw_score,
            delta_from_previous,
            failed_count,
            previous_latest,
            demo_force_pass,
        )

    def _write_run_outputs(
        self,
        result_payload: dict[str, Any],
        latest_local: Path,
        snapshot_prefix: str,
        status: str,
        reason_code: str,
        gate: dict[str, Any],
        aggregate_score: float,
        raw_score: float,
        delta_from_previous: float | None,
        failed_count: int,
        *,
        demo_force_pass: bool,
        started_at: str,
        start_timestamp: float,
        setup_end_timestamp: float,
        execution_end_timestamp: float,
        outputs_prefix: str,
    ) -> int:
        """Write latest.json, upload artifacts, write manager summary. Returns 0 or 1."""
        _write_json(latest_local, result_payload)
        artifact_upload_stats: dict[str, Any] = {
            "uploaded_results": [],
            "logs_uploaded": False,
            "outputs_uploaded": False,
            "durations_sec": {},
        }
        t0 = time.monotonic()
        _gcloud_upload(
            latest_local,
            _bucket_uri(self.runtime_bucket_root, f"{snapshot_prefix}/latest.json"),
        )
        artifact_upload_stats["durations_sec"]["results_latest_upload"] = round(time.monotonic() - t0, 3)
        artifact_upload_stats["uploaded_results"].append("latest.json")
        ci_verdict_uri = ""
        if self.run_id:
            finished_at = _now_iso()
            runner_identity = self.get_runner_identity()
            ci_verdict: dict[str, Any] = {
                "run_id": self.run_id,
                "project_id": self.project_id,
                "bmt_id": self.bmt_id,
                "status": status,
                "reason_code": reason_code,
                "aggregate_score": aggregate_score,
                "runner": runner_identity,
                "gate": gate,
                "timestamps": {"started_at": started_at, "finished_at": finished_at},
                "artifacts": {
                    "latest_json_uri": _bucket_uri(self.runtime_bucket_root, f"{snapshot_prefix}/latest.json"),
                    "logs_uri": _bucket_uri(self.runtime_bucket_root, f"{snapshot_prefix}/logs"),
                },
            }
            verdict_local = self.results_dir / "ci_verdicts" / f"{self.run_id}.json"
            _write_json(verdict_local, ci_verdict)
            ci_verdict_uri = _bucket_uri(self.runtime_bucket_root, f"{snapshot_prefix}/ci_verdict.json")
            t0 = time.monotonic()
            _gcloud_upload(verdict_local, ci_verdict_uri)
            artifact_upload_stats["durations_sec"]["ci_verdict_upload"] = round(time.monotonic() - t0, 3)
            artifact_upload_stats["uploaded_results"].append("ci_verdict.json")
        t0 = time.monotonic()
        _gcloud_rsync_to_gcs(
            self.logs_dir,
            _bucket_uri(self.runtime_bucket_root, f"{snapshot_prefix}/logs"),
            delete=True,
        )
        artifact_upload_stats["durations_sec"]["logs_upload"] = round(time.monotonic() - t0, 3)
        artifact_upload_stats["logs_uploaded"] = True
        artifacts_cfg = self.bmt_cfg.get("artifacts", {}) if isinstance(self.bmt_cfg.get("artifacts"), dict) else {}
        upload_outputs_enabled = bool(artifacts_cfg.get("upload_outputs", False))
        upload_outputs_contexts_raw = artifacts_cfg.get("upload_outputs_contexts", ["manual"])
        upload_outputs_contexts = {
            str(item).strip()
            for item in (upload_outputs_contexts_raw if isinstance(upload_outputs_contexts_raw, list) else [])
            if str(item).strip()
        }
        context_allowed = not upload_outputs_contexts or self.run_context in upload_outputs_contexts
        should_upload_outputs = upload_outputs_enabled and context_allowed
        artifact_upload_stats["upload_outputs_enabled"] = upload_outputs_enabled
        artifact_upload_stats["upload_outputs_contexts"] = sorted(upload_outputs_contexts)
        artifact_upload_stats["run_context"] = self.run_context
        if should_upload_outputs:
            t0 = time.monotonic()
            _gcloud_rsync_to_gcs(
                self.outputs_dir,
                _bucket_uri(self.runtime_bucket_root, outputs_prefix),
                delete=False,
            )
            artifact_upload_stats["durations_sec"]["outputs_upload"] = round(time.monotonic() - t0, 3)
            artifact_upload_stats["outputs_uploaded"] = True
        completed_at = _now_iso()
        total_duration_sec = int(time.monotonic() - start_timestamp)
        setup_sec = int(setup_end_timestamp - start_timestamp)
        execution_sec = int(execution_end_timestamp - setup_end_timestamp)
        upload_sec = total_duration_sec - setup_sec - execution_sec
        manager_summary = {
            "timestamp": result_payload["timestamp"],
            "project_id": self.project_id,
            "bmt_id": self.bmt_id,
            "run_context": self.run_context,
            "run_id": self.run_id,
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
            "cache_stats": self.cache_stats,
            "sync_stats": {"sync_durations_sec": self.sync_durations_sec},
            "artifact_upload_stats": artifact_upload_stats,
            "orchestration_timing": {
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_sec": total_duration_sec,
                "stages": {"setup_sec": setup_sec, "execution_sec": execution_sec, "upload_sec": upload_sec},
            },
        }
        _write_json(self.summary_out, manager_summary)
        self._print_result_line(status, aggregate_score, raw_score)
        return 1 if status == "fail" else 0

    def run(self) -> int:
        """Execute the full BMT orchestration. Returns exit code (0 = pass/warn, 1 = fail)."""
        started_at = _now_iso()
        start_timestamp = time.monotonic()
        runtime_prefix = ""

        enable_progress = (
            bool(os.environ.get("BMT_STATUS_BUCKET"))
            and bool(os.environ.get("BMT_STATUS_RUN_ID"))
            and os.environ.get("BMT_STATUS_LEG_INDEX") is not None
        )
        status_file = None
        progress_bucket = None
        progress_runtime_prefix = None
        progress_run_id = None
        progress_leg_index = None
        if enable_progress:
            try:
                try:
                    from status import status_file as _sf  # type: ignore[import]
                except ImportError:
                    from gcp.image.github import status_file as _sf  # type: ignore[import]
                status_file = _sf
                progress_bucket = os.environ["BMT_STATUS_BUCKET"]
                progress_runtime_prefix = os.environ.get("BMT_STATUS_RUNTIME_PREFIX", runtime_prefix)
                progress_run_id = os.environ["BMT_STATUS_RUN_ID"]
                progress_leg_index = int(os.environ["BMT_STATUS_LEG_INDEX"])
            except (ImportError, ValueError, KeyError):
                enable_progress = False

        self._setup_dirs()
        self.cache_stats = {"cache_hits": [], "cache_misses": [], "states": {}}
        self.sync_durations_sec = {}

        self.setup_assets()
        inputs_root = self.get_inputs_root()
        input_files = self.collect_input_files(inputs_root)
        if not input_files:
            raise RuntimeError(f"No input files found under: {inputs_root}")
        total = len(input_files)
        setup_end_timestamp = time.monotonic()

        file_results, execution_end_timestamp = self._run_worker_pool(
            input_files,
            inputs_root,
            total,
            enable_progress=enable_progress,
            status_file=status_file,
            progress_bucket=progress_bucket,
            progress_runtime_prefix=progress_runtime_prefix,
            progress_run_id=progress_run_id,
            progress_leg_index=progress_leg_index,
            runtime_prefix=runtime_prefix,
        )
        file_results.sort(key=lambda item: item["file"])
        paths_cfg = self.bmt_cfg.get("paths", {}) or {}
        results_prefix = str(paths_cfg.get("results_prefix", "")).rstrip("/")
        outputs_prefix = str(paths_cfg.get("outputs_prefix", "")).rstrip("/")

        (
            status,
            reason_code,
            gate,
            aggregate_score,
            raw_score,
            delta_from_previous,
            failed_count,
            previous_latest,
            demo_force_pass,
        ) = self._run_gate_phase(file_results, results_prefix, outputs_prefix)

        ts_iso = _now_iso()
        ts_compact = _now_stamp()
        snapshot_id = self.run_id or f"local_{ts_compact}"
        snapshot_prefix = f"{results_prefix}/snapshots/{snapshot_id}"
        latest_local = self.results_dir / "latest.json"

        result_payload = {
            "timestamp": ts_iso,
            "project_id": self.project_id,
            "bmt_id": self.bmt_id,
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
            "artifacts": self._artifact_uris(),
            "cache_stats": self.cache_stats,
            "sync_stats": {"sync_durations_sec": self.sync_durations_sec},
        }
        return self._write_run_outputs(
            result_payload,
            latest_local,
            snapshot_prefix,
            status,
            reason_code,
            gate,
            aggregate_score,
            raw_score,
            delta_from_previous,
            failed_count,
            demo_force_pass=demo_force_pass,
            started_at=started_at,
            start_timestamp=start_timestamp,
            setup_end_timestamp=setup_end_timestamp,
            execution_end_timestamp=execution_end_timestamp,
            outputs_prefix=outputs_prefix,
        )

    def _print_result_line(self, status: str, aggregate_score: float, raw_score: float) -> None:
        """Print a one-line result summary.  Subclasses may override."""
        status.upper()
