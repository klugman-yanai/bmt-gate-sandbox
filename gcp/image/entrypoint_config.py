"""Entrypoint config loading (L2 — imports from L0 constants and L1 models only at load time).

Config comes from a **JSON payload file** (primary) with minimal env-var fallbacks
for truly environment-specific values (secrets, bucket when not in file).
No argparse, no Typer, no CLI parsing.

Usage:
    config = load_entrypoint_config("/path/to/config.json")
    # or: config = load_entrypoint_config()  -> reads BMT_CONFIG env var or well-known path
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Well-known config file locations (checked in order if no explicit path given)
_CONFIG_SEARCH_PATHS = (
    Path("/etc/bmt/config.json"),
    Path("config.json"),
    Path(".bmt/config.json"),
)

_DEFAULT_REPO_ROOT = "/opt/bmt"


@dataclass(frozen=True, slots=True)
class WatcherConfig:
    """Config for the watcher mode."""

    bucket: str
    workspace_root: Path
    repo_root: Path
    gcp_project: str = ""
    poll_interval_sec: int = 10
    exit_after_run: bool = True
    idle_timeout_sec: int = 600
    subscription: str = ""
    self_stop: bool = True


@dataclass(frozen=True, slots=True)
class OrchestratorConfig:
    """Config for the orchestrator mode (single-leg execution)."""

    bucket: str
    project: str
    bmt_id: str
    run_id: str
    workspace_root: Path
    repo_root: Path
    run_context: str = "manual"
    summary_out: Path = Path("manager_summary.json")


@dataclass(frozen=True, slots=True)
class TaskConfig:
    """Config for Cloud Run task mode (one leg, selected by CLOUD_RUN_TASK_INDEX)."""

    bucket: str
    trigger_object: str
    workspace_root: Path
    repo_root: Path = Path(_DEFAULT_REPO_ROOT)
    task_index: int = 0
    run_context: str = "ci"
    summary_out: Path = Path("manager_summary.json")


@dataclass(frozen=True, slots=True)
class CoordinatorEntrypointConfig:
    """Config for coordinator mode (post-execution aggregation)."""

    bucket: str
    workflow_run_id: str
    trigger_object: str
    workspace_root: Path
    repo_root: Path = Path(_DEFAULT_REPO_ROOT)


@dataclass(frozen=True, slots=True)
class EntrypointConfig:
    """Top-level entrypoint config. ``mode`` selects which sub-config is active."""

    mode: str  # "watcher" | "orchestrator" | "task" | "coordinator"
    watcher: WatcherConfig | None = None
    orchestrator: OrchestratorConfig | None = None
    task: TaskConfig | None = None
    coordinator_cfg: CoordinatorEntrypointConfig | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def load_entrypoint_config(config_path: str | Path | None = None) -> EntrypointConfig:
    """Load entrypoint config from a JSON file.

    Resolution order for config file path:
    1. Explicit ``config_path`` argument
    2. ``BMT_CONFIG`` env var
    3. Well-known paths: /etc/bmt/config.json, ./config.json, ./.bmt/config.json
    """
    try:
        path = _resolve_config_path(config_path)
        raw = _load_json(path)
    except FileNotFoundError:
        # Cloud Run mode can be configured fully from environment without a config file.
        raw = _env_fallback_config()
        if raw is None:
            raise
        path = Path("<env>")
    mode = str(raw.get("mode", "")).strip()
    if not mode:
        raise ValueError(f"Config {path}: 'mode' is required (watcher|orchestrator|task|coordinator)")

    if mode == "watcher":
        watcher = _build_watcher_config(raw, path)
        return EntrypointConfig(mode=mode, watcher=watcher, raw=raw)
    if mode == "orchestrator":
        orchestrator = _build_orchestrator_config(raw, path)
        return EntrypointConfig(mode=mode, orchestrator=orchestrator, raw=raw)
    if mode == "task":
        task = _build_task_config(raw, path)
        return EntrypointConfig(mode=mode, task=task, raw=raw)
    if mode == "coordinator":
        coord = _build_coordinator_entrypoint_config(raw, path)
        return EntrypointConfig(mode=mode, coordinator_cfg=coord, raw=raw)
    raise ValueError(f"Config {path}: unknown mode {mode!r} (expected watcher|orchestrator|task|coordinator)")


# ---------------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------------


def _resolve_config_path(explicit: str | Path | None) -> Path:
    if explicit is not None:
        p = Path(explicit)
        if not p.is_file():
            raise FileNotFoundError(f"Config file not found: {p}")
        return p

    env_path = os.environ.get("BMT_CONFIG", "").strip()
    if env_path:
        p = Path(env_path)
        if not p.is_file():
            raise FileNotFoundError(f"BMT_CONFIG points to missing file: {p}")
        return p

    for candidate in _CONFIG_SEARCH_PATHS:
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        "No config file found. Provide a path, set BMT_CONFIG env var, "
        f"or place config at one of: {', '.join(str(p) for p in _CONFIG_SEARCH_PATHS)}"
    )


def _env_fallback_config() -> dict[str, Any] | None:
    """Best-effort config from env for Cloud Run jobs.

    Used only when no file-based config is available.
    """
    trigger_object = os.environ.get("BMT_TRIGGER_OBJECT", "").strip() or os.environ.get(
        "TRIGGER_OBJECT", ""
    ).strip()
    if not trigger_object:
        return None

    mode = os.environ.get("BMT_MODE", "").strip() or "task"
    bucket = os.environ.get("GCS_BUCKET", "").strip() or os.environ.get("BUCKET", "").strip()
    workflow_run_id = os.environ.get("BMT_WORKFLOW_RUN_ID", "").strip() or os.environ.get(
        "WORKFLOW_RUN_ID", ""
    ).strip()

    return {
        "mode": mode,
        "bucket": bucket,
        "trigger_object": trigger_object,
        "workflow_run_id": workflow_run_id,
        "workspace_root": os.environ.get(
            "BMT_WORKSPACE_ROOT", str(Path(tempfile.gettempdir()) / "bmt_workspace")
        ),
        "repo_root": os.environ.get("BMT_REPO_ROOT", _DEFAULT_REPO_ROOT),
        "run_context": os.environ.get("RUN_CONTEXT", "ci"),
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return data


def _str_required(raw: dict[str, Any], key: str, source: Path) -> str:
    val = str(raw.get(key, "")).strip()
    if not val:
        # Fall back to env var with same name uppercased (for bucket, gcp_project)
        val = os.environ.get(key.upper(), "").strip()
    if not val:
        raise ValueError(f"Config {source}: '{key}' is required")
    return val


def _str_optional(raw: dict[str, Any], key: str, default: str = "") -> str:
    val = raw.get(key)
    if val is None:
        return os.environ.get(key.upper(), default).strip()
    return str(val).strip()


def _build_watcher_config(raw: dict[str, Any], source: Path) -> WatcherConfig:
    bucket = _str_required(raw, "bucket", source)
    # Fall back: GCS_BUCKET env var (the one truly env-specific value on a VM)
    if not bucket:
        bucket = os.environ.get("GCS_BUCKET", "").strip()
    return WatcherConfig(
        bucket=bucket,
        workspace_root=Path(raw.get("workspace_root") or os.environ.get("BMT_WORKSPACE_ROOT", "~/bmt_workspace"))
        .expanduser()
        .resolve(),
        repo_root=Path(raw.get("repo_root") or os.environ.get("BMT_REPO_ROOT", _DEFAULT_REPO_ROOT)),
        gcp_project=_str_optional(raw, "gcp_project"),
        poll_interval_sec=int(raw.get("poll_interval_sec", 10)),
        exit_after_run=raw.get("exit_after_run", True) is not False,
        idle_timeout_sec=int(raw.get("idle_timeout_sec", 600)),
        subscription=_str_optional(raw, "subscription"),
        self_stop=raw.get("self_stop", True) is not False,
    )


def _build_orchestrator_config(raw: dict[str, Any], source: Path) -> OrchestratorConfig:
    return OrchestratorConfig(
        bucket=_str_required(raw, "bucket", source),
        project=_str_required(raw, "project", source),
        bmt_id=_str_required(raw, "bmt_id", source),
        run_id=_str_required(raw, "run_id", source),
        workspace_root=Path(raw.get("workspace_root", ".")).expanduser().resolve(),
        repo_root=Path(raw.get("repo_root") or os.environ.get("BMT_REPO_ROOT", _DEFAULT_REPO_ROOT)),
        run_context=str(raw.get("run_context", "manual")),
        summary_out=Path(raw.get("summary_out", "manager_summary.json")),
    )


def _build_task_config(raw: dict[str, Any], source: Path) -> TaskConfig:
    task_index_str = os.environ.get("CLOUD_RUN_TASK_INDEX", str(raw.get("task_index", 0)))
    return TaskConfig(
        bucket=_str_required(raw, "bucket", source),
        trigger_object=_str_required(raw, "trigger_object", source),
        workspace_root=Path(raw.get("workspace_root", ".")).expanduser().resolve(),
        repo_root=Path(raw.get("repo_root") or os.environ.get("BMT_REPO_ROOT", _DEFAULT_REPO_ROOT)),
        task_index=int(task_index_str),
        run_context=str(raw.get("run_context", "ci")),
        summary_out=Path(raw.get("summary_out", "manager_summary.json")),
    )


def _build_coordinator_entrypoint_config(raw: dict[str, Any], source: Path) -> CoordinatorEntrypointConfig:
    return CoordinatorEntrypointConfig(
        bucket=_str_required(raw, "bucket", source),
        workflow_run_id=_str_required(raw, "workflow_run_id", source),
        trigger_object=_str_required(raw, "trigger_object", source),
        workspace_root=Path(raw.get("workspace_root", ".")).expanduser().resolve(),
        repo_root=Path(raw.get("repo_root") or os.environ.get("BMT_REPO_ROOT", _DEFAULT_REPO_ROOT)),
    )
