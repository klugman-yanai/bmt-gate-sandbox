"""Canonical stage mirror paths under ``benchmarks/`` (bucket 1:1 layout).

Use these helpers when building :class:`~backend.runtime.models.RunnerConfig` or documenting
``bmt.json`` prefixes so contributors do not hard-code divergent strings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from backend.runtime.models import RunnerConfig

# POSIX prefix relative to stage root (``benchmarks/``).
SHARED_DEPENDENCIES_PREFIX: Final[str] = "projects/shared/dependencies"


def shared_dependencies_dir(stage_root: Path) -> Path:
    """Directory for cross-project native libraries (ONNX, TensorFlow Lite, …)."""
    return stage_root.joinpath(*SHARED_DEPENDENCIES_PREFIX.split("/"))


def native_runner_uri(project: str) -> str:
    """Default ``runner.uri`` for a Kardome-style binary under the project ``lib/`` tree."""
    return f"projects/{project}/lib/kardome_runner"


def runner_config_native_kardome(project: str) -> RunnerConfig:
    """Opinionated :class:`RunnerConfig` for native stdout Kardome legs (shared deps + template)."""
    return RunnerConfig(
        uri=native_runner_uri(project),
        deps_prefix=SHARED_DEPENDENCIES_PREFIX,
        template_path="backend/src/backend/runtime/assets/runner_input.template.json",
    )


def resolve_posix_under_stage(stage_root: Path, posix_prefix: str) -> Path:
    """Turn a manifest-style prefix (``projects/sk/inputs/x``) into a filesystem path."""
    rel = str(posix_prefix).strip().strip("/")
    if not rel:
        return stage_root
    return stage_root.joinpath(*rel.split("/"))
