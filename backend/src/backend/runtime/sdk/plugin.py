"""Contributor plugin contract."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from backend.runtime.models import PluginManifest
from backend.runtime.plugin_errors import PluginLoadError
from backend.runtime.sdk.compatibility import ensure_plugin_api_version_supported
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.results import (
    PLUGIN_EXECUTE_EXCEPTION_RAW_KEY,
    CaseArtifacts,
    CaseMetrics,
    CaseResult,
    CaseStatus,
    ExecutionMode,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)

TConfig = TypeVar("TConfig", bound=BaseModel)

_DEFAULT_MAX_GRACE_CASE_FAILURES = 1
_BATCH_CMD_TIMEOUT_DEFAULT_SEC = 6 * 3600
_BATCH_CMD_TIMEOUT_MAX_SEC = 7 * 24 * 3600


def parse_max_grace_case_failures(plugin_config: dict[str, Any]) -> int:
    """Read ``max_grace_case_failures`` from ``plugin_config`` with coercion and safe bounds.

    Use this for pure parsing; :class:`BmtPlugin` delegates :meth:`~BmtPlugin.max_grace_case_failures`
    here so overrides stay optional and :class:`~backend.runtime.sdk.protocols.SupportsGraceCaseLimits`
    implementations stay simple.
    """
    raw = plugin_config.get("max_grace_case_failures", _DEFAULT_MAX_GRACE_CASE_FAILURES)
    if raw is None:
        return _DEFAULT_MAX_GRACE_CASE_FAILURES
    try:
        n = int(raw)
    except (TypeError, ValueError):
        logging.getLogger(__name__).warning(
            "Invalid max_grace_case_failures=%r; using default %s",
            raw,
            _DEFAULT_MAX_GRACE_CASE_FAILURES,
        )
        return _DEFAULT_MAX_GRACE_CASE_FAILURES
    if n < 0:
        logging.getLogger(__name__).warning("max_grace_case_failures must be >= 0; got %s, using 0", n)
        return 0
    return n


class BmtPlugin(ABC):
    """Abstract base for a staged BMT leg (prepare → execute → score → evaluate).

    Attributes:
        plugin_name: Must match ``plugin.json`` (``PluginManifest.plugin_name``).
        api_version: Declared contract version; validated against supported set.

    The runtime calls :meth:`prepare`, then :meth:`execute`, :meth:`score`, and :meth:`evaluate`
    inside a ``try``/``finally`` that always runs :meth:`teardown` when preparation succeeded.
    Override :meth:`teardown` for handles, temp dirs, or clients.

    Structural typing: implementations satisfy :class:`~backend.runtime.sdk.protocols.BmtPluginProtocol`
    and :class:`~backend.runtime.sdk.protocols.SupportsGraceCaseLimits` for gating helpers.
    """

    plugin_name: str = "default"
    api_version: str = "v1"

    @property
    def log(self) -> logging.Logger:
        """Logger named after the plugin implementation module."""
        return logging.getLogger(self.__class__.__module__)

    def validate_against_loaded_manifest(self, manifest: PluginManifest) -> None:
        """Ensure ``plugin.json`` matches :attr:`plugin_name` and :attr:`api_version`.

        Called from :func:`~backend.runtime.plugin_loader.load_plugin` after the
        entrypoint is instantiated.
        """
        if self.plugin_name != manifest.plugin_name:
            raise PluginLoadError(
                f"plugin.json plugin_name={manifest.plugin_name!r} does not match "
                f"{self.__class__.__qualname__}.plugin_name={self.plugin_name!r}"
            )
        if self.api_version != manifest.api_version:
            raise PluginLoadError(
                f"plugin.json api_version={manifest.api_version!r} does not match "
                f"{self.__class__.__qualname__}.api_version={self.api_version!r}"
            )
        ensure_plugin_api_version_supported(manifest.api_version)

    def teardown(self, context: ExecutionContext, prepared: PreparedAssets) -> None:
        """Release resources after ``prepare`` succeeds.

        **Order:** The runtime runs ``prepare``, then ``execute``, ``score``, and ``evaluate`` inside a
        ``try``, and always calls ``teardown`` in ``finally`` when ``prepare`` returned successfully—even
        if ``execute``, ``score``, or ``evaluate`` raised. If ``prepare`` itself raises, ``teardown`` is
        **not** called. Override in plugins that allocate temp dirs, handles, or external clients.
        """
        return

    @staticmethod
    def require_runner(context: ExecutionContext) -> Path:
        """Return the configured runner path or raise ``FileNotFoundError``."""
        if context.runner_path is None:
            raise FileNotFoundError(f"Runner path is not configured for {context.bmt_manifest.bmt_slug}")
        return context.runner_path

    @staticmethod
    def prepared_assets_from_context(context: ExecutionContext) -> PreparedAssets:
        """Default :meth:`prepare` mapping: dataset, workspace, and runner path from context."""
        return PreparedAssets(
            dataset_root=context.dataset_root,
            workspace_root=context.workspace_root,
            runner_path=context.runner_path,
        )

    @staticmethod
    def runner_env_with_deps(context: ExecutionContext) -> dict[str, str]:
        """Environment fragment for native runners (e.g. ``LD_LIBRARY_PATH`` when ``deps_root`` is set)."""
        env: dict[str, str] = {}
        if context.deps_root is not None and context.deps_root.is_dir():
            existing = os.environ.get("LD_LIBRARY_PATH", "").strip()
            env["LD_LIBRARY_PATH"] = f"{context.deps_root}:{existing}" if existing else str(context.deps_root)
        return env

    @staticmethod
    def resolve_runner_template_path(context: ExecutionContext) -> Path:
        """Resolve ``runner.template_path`` against the process current working directory.

        The BMT runtime sets CWD to a stable root (see tests ``conftest``); use this helper
        instead of re-deriving template paths in each plugin.
        """
        return (Path.cwd() / context.bmt_manifest.runner.template_path).resolve()

    def parse_plugin_config(self, context: ExecutionContext, model: type[TConfig]) -> TConfig:
        """Parse ``context.bmt_manifest.plugin_config`` with a Pydantic model (``extra`` policy is the model's)."""
        return model.model_validate(context.bmt_manifest.plugin_config)

    @staticmethod
    def resolve_workspace_file(workspace_root: Path, relative_path: str) -> Path | None:
        """Return a file path under ``workspace_root`` if it exists and is non-escaping; else ``None``."""
        rel = str(relative_path).strip()
        if not rel:
            return None
        p = Path(rel)
        if p.is_absolute():
            logging.getLogger(__name__).warning("workspace-relative path must be relative, got %s", relative_path)
            return None
        candidate = (workspace_root / rel).resolve()
        base = workspace_root.resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            logging.getLogger(__name__).warning(
                "Path escapes workspace (resolved %s not under %s)",
                candidate,
                base,
            )
            return None
        return candidate if candidate.is_file() else None

    def max_grace_case_failures(self, plugin_config: dict[str, Any]) -> int:
        """Delegate to :func:`parse_max_grace_case_failures`; override for custom grace policy."""
        return parse_max_grace_case_failures(plugin_config)

    @staticmethod
    def batch_command_timeout_seconds() -> float:
        """Upper bound for batch subprocess runs (``BATCH_COMMAND_TIMEOUT_SEC`` env)."""
        raw = os.environ.get("BATCH_COMMAND_TIMEOUT_SEC", "").strip()
        if not raw:
            return float(_BATCH_CMD_TIMEOUT_DEFAULT_SEC)
        try:
            sec = int(raw)
        except ValueError:
            logging.getLogger(__name__).warning(
                "Invalid BATCH_COMMAND_TIMEOUT_SEC=%r; using default 6h",
                raw,
            )
            return float(_BATCH_CMD_TIMEOUT_DEFAULT_SEC)
        if sec <= 0:
            return float(_BATCH_CMD_TIMEOUT_DEFAULT_SEC)
        return float(min(sec, _BATCH_CMD_TIMEOUT_MAX_SEC))

    def execution_failure_result(
        self,
        exc: BaseException,
        *,
        prepared: PreparedAssets,
        context: ExecutionContext,
        execution_mode_used: ExecutionMode | str = ExecutionMode.UNKNOWN,
        case_id: str = "_execute_",
    ) -> ExecutionResult:
        """Normalize an unexpected exception from :meth:`execute` into a single failed :class:`CaseResult`."""
        self.log.exception("%s execute failed for bmt=%s", self.__class__.__name__, context.bmt_manifest.bmt_slug)
        mode = ExecutionMode(execution_mode_used) if isinstance(execution_mode_used, str) else execution_mode_used
        return ExecutionResult(
            execution_mode_used=mode,
            case_results=[
                CaseResult(
                    case_id=case_id,
                    input_path=prepared.dataset_root,
                    exit_code=-1,
                    status=CaseStatus.FAILED,
                    metrics=CaseMetrics(root={}),
                    artifacts=CaseArtifacts(root={}),
                    runner_case_diagnostic=f"{type(exc).__name__}:{exc}",
                )
            ],
            raw_summary={PLUGIN_EXECUTE_EXCEPTION_RAW_KEY: True},
        )

    @abstractmethod
    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        """Resolve assets needed before execution."""

    @abstractmethod
    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        """Run a BMT leg and return normalized results."""

    @abstractmethod
    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult:
        """Convert normalized execution output into a score."""

    @abstractmethod
    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        """Return pass/fail semantics for the score."""
