"""Shared repository path constants for tools and CI.

Single source of truth for default config/runtime roots. Env contract and behavioral
defaults live in tools/repo/vars_contract.py; infra-derived vars from Pulumi. See
tools/shared/env_contract.default_contract_path().

All paths are pathlib.Path; relative ones are relative to repo root. Resolve against
repo root when needed: (repo_root() / DEFAULT_CONFIG_ROOT).resolve().

Key exports:
  WorkspaceLayout  — frozen dataclass owning all local path roots.
  DEFAULT_CONFIG_ROOT, DEFAULT_STAGE_ROOT — bare constants (use WorkspaceLayout.default() in new tools).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def repo_root() -> Path:
    """Resolve repo root by walking up to a directory containing pyproject.toml, gcp/, and infra/."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "gcp").is_dir() and (parent / "infra").is_dir():
            return parent
    raise RuntimeError(f"Unable to resolve repo root from {here}")


# Default roots for VM mirror and staging area (relative to repo root).
DEFAULT_CONFIG_ROOT = Path("gcp/image")
DEFAULT_STAGE_ROOT = Path("gcp/stage")
# Legacy alias; prefer DEFAULT_STAGE_ROOT in new code.
DEFAULT_RUNTIME_ROOT = DEFAULT_STAGE_ROOT

# Other canonical roots (relative to repo root).
GITHUB_BMT_ROOT = Path(".github/bmt")
INFRA_PULUMI = Path("infra/pulumi")


def pulumi_dir() -> Path:
    """Pulumi project directory (infra/pulumi) resolved from repo root."""
    return repo_root() / INFRA_PULUMI


INFRA_SCRIPTS = Path("infra/scripts")
TOOLS_SCRIPTS = Path("tools/scripts")

# BMT local layout (runner libs + shared native deps). Relative to repo root.
# Override with BMT_ROOT env (e.g. "gcp/local" or absolute path).
DEFAULT_BMT_ROOT = Path("gcp/local")
BMT_DEPS_SUBDIR = Path("dependencies")
BMT_PROJECT_LIB_SUBDIR = Path("lib")

# Pulumi is source of truth for repo vars; no legacy config paths.
# Use shared env_contract.default_contract_path() for the contract.


@dataclass(frozen=True)
class WorkspaceLayout:
    """Single typed config for all local path roots in the dev workspace.

    Owning all local path roots in one place means that changing any root is a
    one-line change to ``WorkspaceLayout.default()``, and every tool that receives
    a ``WorkspaceLayout`` instance will automatically pick up the change.

    Attributes:
        stage_root:  gcp/stage/ — local staging mirror of GCS (renamed from gcp/remote/).
        image_root:  gcp/image/ — VM code baked into image (read-only locally).
        mnt_root:    gcp/mnt/   — FUSE mount points (gitignored, opt-in).
        data_root:   data/      — local dataset archives and optional scratch data.

    Note: transient execution workspaces are not part of WorkspaceLayout.
    Cloud Run and local runs create per-run scratch directories separately.
    """

    stage_root: Path
    image_root: Path
    mnt_root: Path
    data_root: Path

    @classmethod
    def default(cls) -> WorkspaceLayout:
        """Canonical defaults for a fresh repo checkout."""
        return cls(
            stage_root=DEFAULT_STAGE_ROOT,
            image_root=DEFAULT_CONFIG_ROOT,
            mnt_root=Path("gcp/mnt"),
            data_root=Path("data"),
        )

    @classmethod
    def from_env(cls) -> WorkspaceLayout:
        """Construct from environment variables, falling back to defaults.

        Override any root via:
          BMT_STAGE_ROOT  — overrides stage_root (gcp/stage/)
          BMT_IMAGE_ROOT  — overrides image_root (gcp/image/)
          BMT_MNT_ROOT    — overrides mnt_root   (gcp/mnt/)
          BMT_DATA_ROOT   — overrides data_root   (data/)
        """
        defaults = cls.default()

        def _p(env_key: str, default: Path) -> Path:
            raw = (os.environ.get(env_key) or "").strip()
            return Path(raw) if raw else default

        return cls(
            stage_root=_p("BMT_STAGE_ROOT", defaults.stage_root),
            image_root=_p("BMT_IMAGE_ROOT", defaults.image_root),
            mnt_root=_p("BMT_MNT_ROOT", defaults.mnt_root),
            data_root=_p("BMT_DATA_ROOT", defaults.data_root),
        )
