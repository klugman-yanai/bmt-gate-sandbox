"""Runtime facade for the Cloud Run image entrypoint."""

from __future__ import annotations

import enum
import json
import logging
import os
import signal
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import FrameType


class RuntimeMode(enum.Enum):
    PLAN = "plan"
    TASK = "task"
    COORDINATOR = "coordinator"
    FINALIZE_FAILURE = "finalize-failure"
    DATASET_IMPORT = "dataset-import"
    LOCAL = "local"


MODE_ENV_VAR = "BMT_MODE"
WORKFLOW_RUN_ID_ENV_VAR = "BMT_WORKFLOW_RUN_ID"
TASK_PROFILE_ENV_VAR = "BMT_TASK_PROFILE"
TASK_INDEX_ENV_VAR = "CLOUD_RUN_TASK_INDEX"
RUNTIME_ROOT_ENV_VARS = ("BMT_RUNTIME_ROOT", "BMT_STAGE_ROOT")
WORKSPACE_ROOT_ENV_VAR = "BMT_FRAMEWORK_WORKSPACE"
DEFAULT_TASK_PROFILE = "standard"
DEFAULT_WORKFLOW_RUN_ID = "local-run"
SUPPORTED_MODES = ", ".join(mode.value for mode in RuntimeMode.__members__.values())

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeInvocation:
    mode: RuntimeMode
    workflow_run_id: str
    task_profile: str
    task_index: int
    stage_root: Path | None
    workspace_root: Path | None


@dataclass(slots=True)
class RuntimeRequestDraft:
    mode: RuntimeMode | None = None
    workflow_run_id: str = DEFAULT_WORKFLOW_RUN_ID
    task_profile: str = DEFAULT_TASK_PROFILE
    task_index: int = 0
    stage_root: Path | None = None
    workspace_root: Path | None = None


class RuntimeFacade:
    def __init__(self) -> None:
        self._draft = RuntimeRequestDraft()
        self.invocation: RuntimeInvocation | None = None
        self._selected_handler: Callable[[], int] | None = None
        self._handlers: dict[RuntimeMode, Callable[[], int]] = {}
        self._handlers[RuntimeMode.PLAN] = self._run_plan
        self._handlers[RuntimeMode.TASK] = self._run_task
        self._handlers[RuntimeMode.COORDINATOR] = self._run_coordinator
        self._handlers[RuntimeMode.FINALIZE_FAILURE] = self._run_finalize_failure
        self._handlers[RuntimeMode.DATASET_IMPORT] = self._run_dataset_import
        self._handlers[RuntimeMode.LOCAL] = self._run_local

    def bootstrap_runtime(self) -> RuntimeFacade:
        self._install_signal_handlers()
        return self

    def discover_runtime_mode(self) -> RuntimeFacade:
        self._draft.mode = self._read_mode()
        return self

    def load_run_identity(self) -> RuntimeFacade:
        self._draft.workflow_run_id = (os.environ.get(WORKFLOW_RUN_ID_ENV_VAR) or DEFAULT_WORKFLOW_RUN_ID).strip()
        return self

    def load_task_assignment(self) -> RuntimeFacade:
        self._draft.task_profile = (os.environ.get(TASK_PROFILE_ENV_VAR) or DEFAULT_TASK_PROFILE).strip()
        self._draft.task_index = int(os.environ.get(TASK_INDEX_ENV_VAR, "0"))
        return self

    def resolve_runtime_paths(self) -> RuntimeFacade:
        self._draft.stage_root = self._first_path(*RUNTIME_ROOT_ENV_VARS)
        self._draft.workspace_root = self._read_path(WORKSPACE_ROOT_ENV_VAR)
        return self

    def assemble_runtime_invocation(self) -> RuntimeFacade:
        if self._draft.mode is None:
            raise RuntimeError("Runtime mode must be discovered before assembling the runtime invocation")
        self.invocation = RuntimeInvocation(
            mode=self._draft.mode,
            workflow_run_id=self._draft.workflow_run_id,
            task_profile=self._draft.task_profile,
            task_index=self._draft.task_index,
            stage_root=self._draft.stage_root,
            workspace_root=self._draft.workspace_root,
        )
        return self

    @staticmethod
    def _install_signal_handlers() -> None:
        def handle_sigbus(signum: int, frame: FrameType | None) -> None:
            try:
                if frame is not None:
                    traceback.print_stack(frame)
            finally:
                signal.signal(signal.SIGBUS, signal.SIG_DFL)
                raise SystemExit(signum)

        def handle_graceful_stop(signum: int, _frame: FrameType | None) -> None:
            # Cloud Run sends SIGTERM before SIGKILL; convert so ``finally`` blocks can run.
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGBUS, handle_sigbus)
        signal.signal(signal.SIGTERM, handle_graceful_stop)
        signal.signal(signal.SIGINT, handle_graceful_stop)

    @staticmethod
    def _read_mode() -> RuntimeMode:
        raw_mode = (os.environ.get(MODE_ENV_VAR) or "").strip().lower()
        try:
            return RuntimeMode(raw_mode)
        except ValueError as error:
            raise RuntimeError(f"{MODE_ENV_VAR} must be one of: {SUPPORTED_MODES}") from error

    @staticmethod
    def _read_path(env_var: str) -> Path | None:
        raw_value = (os.environ.get(env_var) or "").strip()
        return Path(raw_value).resolve() if raw_value else None

    @classmethod
    def _first_path(cls, *env_vars: str) -> Path | None:
        for env_var in env_vars:
            resolved = cls._read_path(env_var)
            if resolved is not None:
                return resolved
        return None

    def resolve_runtime_stage(self) -> RuntimeFacade:
        if self.invocation is None:
            raise RuntimeError("Runtime invocation must be loaded before selecting a pipeline stage")
        self._selected_handler = self._handlers[self.invocation.mode]
        return self

    def execute_runtime_stage(self) -> int:
        if self._selected_handler is None:
            raise RuntimeError("Pipeline stage must be selected before execution")
        inv = self._require_invocation()
        _logger.info(
            "%s",
            json.dumps(
                {
                    "bmt_run_bootstrap": True,
                    "bmt_mode": inv.mode.value,
                    "workflow_run_id": inv.workflow_run_id,
                    "task_profile": inv.task_profile,
                    "task_index": inv.task_index,
                    "github_repository": (os.environ.get("GITHUB_REPOSITORY") or "").strip(),
                },
                separators=(",", ":"),
            ),
        )
        return self._selected_handler()

    def _require_invocation(self) -> RuntimeInvocation:
        if self.invocation is None:
            raise RuntimeError("Runtime invocation has not been loaded")
        return self.invocation

    def _run_plan(self) -> int:
        from gcp.image.runtime.entrypoint import run_plan_mode

        invocation = self._require_invocation()
        return run_plan_mode(
            workflow_run_id=invocation.workflow_run_id,
            stage_root=invocation.stage_root,
        )

    def _run_task(self) -> int:
        from gcp.image.runtime.entrypoint import run_task_mode

        invocation = self._require_invocation()
        return run_task_mode(
            workflow_run_id=invocation.workflow_run_id,
            task_profile=invocation.task_profile,
            task_index=invocation.task_index,
            stage_root=invocation.stage_root,
            workspace_root=invocation.workspace_root,
        )

    def _run_coordinator(self) -> int:
        from gcp.image.runtime.entrypoint import run_coordinator_mode

        invocation = self._require_invocation()
        return run_coordinator_mode(
            workflow_run_id=invocation.workflow_run_id,
            stage_root=invocation.stage_root,
        )

    def _run_finalize_failure(self) -> int:
        from gcp.image.runtime.entrypoint import run_finalize_failure_mode

        invocation = self._require_invocation()
        return run_finalize_failure_mode(
            workflow_run_id=invocation.workflow_run_id,
            stage_root=invocation.stage_root,
        )

    @staticmethod
    def _run_dataset_import() -> int:
        from gcp.image.runtime.entrypoint import run_dataset_import_mode

        return run_dataset_import_mode()

    def _run_local(self) -> int:
        from gcp.image.runtime.entrypoint import run_local_mode

        invocation = self._require_invocation()
        return run_local_mode(
            workflow_run_id=invocation.workflow_run_id,
            stage_root=invocation.stage_root,
            workspace_root=invocation.workspace_root,
        )
