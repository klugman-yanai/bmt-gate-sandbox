"""BmtManagerProtocol and BaseBmtManager — the canonical contributor API contract.

BmtManagerProtocol defines the structural contract: any type satisfying these method
signatures can be used by the orchestrator. BaseBmtManager is an ABC that implements the
Protocol and provides shared orchestration defaults (collect_input_files, run).

Contributors subclass BaseBmtManager, override the abstract methods, and mark each
override with ``@override``. Config is injected via the constructor — no CLI parsing.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from gcp.image.models import (
    FileRunResult,
    GateResult,
    ManagerConfig,
    RunnerIdentity,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structural contract (Protocol)
# ---------------------------------------------------------------------------


@runtime_checkable
class BmtManagerProtocol(Protocol):
    """Structural contract for a BMT manager.

    The orchestrator types against this Protocol so alternative implementations
    (wrappers, adapters, test doubles) remain valid without subclassing.

    All parameters and return types use value classes — no ``dict[str, Any]``.
    """

    def setup_assets(self) -> None:
        """Download/cache runner, template, dataset, and any other assets."""
        ...

    def collect_input_files(self, inputs_root: Path) -> list[Path]:
        """Return the list of input files to process from ``inputs_root``."""
        ...

    def run_file(self, input_file: Path, inputs_root: Path) -> FileRunResult:
        """Run the BMT on a single input file and return a typed result."""
        ...

    def compute_score(self, file_results: list[FileRunResult]) -> float:
        """Compute the aggregate score from per-file results."""
        ...

    def get_runner_identity(self) -> RunnerIdentity:
        """Return metadata identifying the runner binary used."""
        ...

    def evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[FileRunResult],
    ) -> GateResult:
        """Evaluate pass/fail for this run. Returns a typed GateResult."""
        ...

    def run(self) -> int:
        """Execute the full BMT orchestration. Returns exit code (0 = pass/warn, 1 = fail)."""
        ...


# ---------------------------------------------------------------------------
# Abstract base class (runtime contract + shared orchestration)
# ---------------------------------------------------------------------------


class BaseBmtManager(ABC):
    """ABC implementing BmtManagerProtocol with shared orchestration defaults.

    Contributors subclass this and override the abstract methods. The framework injects
    a validated ``ManagerConfig`` via the constructor — no CLI parsing in contributor code.

    Provides default implementations for:
    - ``collect_input_files``: recursive walk using config's ``input_file_extensions``
    - ``run``: the full orchestration loop (setup → collect → execute → gate → output)
    """

    def __init__(self, config: ManagerConfig) -> None:
        self.config = config

        # Convenience aliases from config
        self.project_id: str = config.leg_identity.project
        self.bmt_id: str = config.leg_identity.bmt_id
        self.run_id: str = config.leg_identity.run_id
        self.run_context: str = config.run_context
        self.max_jobs: int = max(1, config.max_jobs)
        self.limit: int = config.limit

        # Workspace paths
        self.workspace_root: Path = config.workspace_paths.workspace_root
        self.staging_dir: Path = config.workspace_paths.staging_dir
        self.runtime_dir: Path = config.workspace_paths.runtime_dir
        self.outputs_dir: Path = config.workspace_paths.outputs_dir
        self.logs_dir: Path = config.workspace_paths.logs_dir
        self.results_dir: Path = config.workspace_paths.results_dir
        self.cache_base: Path = config.workspace_paths.cache_base
        self.cache_meta_dir: Path = config.workspace_paths.cache_meta_dir

        # Bucket
        self.bucket_name: str = config.bucket_paths.bucket_name
        self.runtime_bucket_root: str = config.bucket_paths.runtime_root

        # Tracking (populated during run)
        self.cache_stats: dict[str, Any] = {"cache_hits": [], "cache_misses": [], "states": {}}
        self.sync_durations_sec: dict[str, float] = {}

    def _setup_dirs(self) -> None:
        """Create all workspace directories."""
        for d in (
            self.staging_dir,
            self.runtime_dir,
            self.outputs_dir,
            self.logs_dir,
            self.results_dir,
            self.cache_meta_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Abstract interface (contributors override these)
    # ------------------------------------------------------------------

    @abstractmethod
    def setup_assets(self) -> None:
        """Download/cache runner, template, and any other assets.

        Called after workspace dirs are created. Should populate any runner/template
        paths needed by ``run_file``.
        """

    @abstractmethod
    def run_file(self, input_file: Path, inputs_root: Path) -> FileRunResult:
        """Run the BMT on a single input file.

        Each project implements its own runner invocation and output parsing.
        Must return a typed ``FileRunResult``.
        """

    @abstractmethod
    def compute_score(self, file_results: list[FileRunResult]) -> float:
        """Compute the aggregate score from per-file results."""

    @abstractmethod
    def get_runner_identity(self) -> RunnerIdentity:
        """Return metadata identifying the runner binary used."""

    @abstractmethod
    def evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[FileRunResult],
    ) -> GateResult:
        """Evaluate pass/fail for this run."""

    # ------------------------------------------------------------------
    # Default implementations (contributors may override)
    # ------------------------------------------------------------------

    def collect_input_files(self, inputs_root: Path) -> list[Path]:
        """Recursively collect input files from ``inputs_root``.

        Uses ``config.jobs_config.input_file_extensions`` (default: ``["*.wav"]``).
        Applies ``self.limit`` if set. Override only for custom discovery.
        """
        extensions = self.config.jobs_config.input_file_extensions or ["*.wav"]
        all_files: list[Path] = []
        for pattern in extensions:
            all_files.extend(inputs_root.rglob(pattern))
        all_files.sort()
        if self.limit > 0:
            all_files = all_files[: self.limit]
        return all_files

    def get_inputs_root(self) -> Path:
        """Return the root directory containing input files.

        ``setup_assets`` should set ``self._inputs_root`` before this is called.
        """
        return getattr(self, "_inputs_root", self.staging_dir / "inputs")

    def run(self) -> int:
        """Execute the full BMT orchestration. Returns 0 (pass/warn) or 1 (fail).

        Orchestration steps: setup_dirs → setup_assets → collect → execute pool →
        gate evaluation. Contributors normally do not override this.
        """
        start_timestamp = time.monotonic()

        self._setup_dirs()
        self.setup_assets()

        inputs_root = self.get_inputs_root()
        input_files = self.collect_input_files(inputs_root)
        if not input_files:
            raise RuntimeError(f"No input files found under: {inputs_root}")

        setup_end_timestamp = time.monotonic()

        # Execute file pool
        file_results: list[FileRunResult] = []
        with ThreadPoolExecutor(max_workers=self.max_jobs) as pool:
            futures = {pool.submit(self.run_file, f, inputs_root): f for f in input_files}
            for future in as_completed(futures):
                file_results.append(future.result())

        file_results.sort(key=lambda r: r.file)
        execution_end_timestamp = time.monotonic()

        # Gate evaluation
        failed_count = sum(1 for r in file_results if r.exit_code != 0)
        aggregate_score = self.compute_score(file_results)
        gate = self.evaluate_gate(aggregate_score, None, failed_count, file_results)

        status = "pass" if gate.passed else "fail"
        reason_code = gate.reason

        logger.info(
            "BMT %s/%s result: %s (score=%.4f, failed=%d, reason=%s)",
            self.project_id,
            self.bmt_id,
            status.upper(),
            aggregate_score,
            failed_count,
            reason_code,
        )

        _ = (start_timestamp, setup_end_timestamp, execution_end_timestamp)  # available for subclass timing

        return 1 if status == "fail" else 0
