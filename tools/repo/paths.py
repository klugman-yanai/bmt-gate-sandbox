"""Shared repository path constants for tools and CI.

Single source of truth for default config/runtime roots. Env contract and behavioral
defaults live in tools/repo/vars_contract.py; infra-derived vars from Terraform. See
tools/shared/env_contract.default_contract_path().

All paths are pathlib.Path; relative ones are relative to repo root. Resolve against
repo root when needed: (repo_root() / DEFAULT_CONFIG_ROOT).resolve().
"""

from pathlib import Path


def repo_root() -> Path:
    """Resolve repo root by walking up to a directory containing pyproject.toml, backend/, and infra/."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "backend").is_dir() and (parent / "infra").is_dir():
            return parent
    raise RuntimeError(f"Unable to resolve repo root from {here}")


# Default roots (relative to repo root).
DEFAULT_CONFIG_ROOT = Path("backend")
DEFAULT_STAGE_ROOT = Path("benchmarks")
# Legacy alias; prefer DEFAULT_STAGE_ROOT in new code.
DEFAULT_RUNTIME_ROOT = DEFAULT_STAGE_ROOT

# Other canonical roots (relative to repo root).
CI_ROOT = Path("ci")
CI_RESOURCES = CI_ROOT / "src" / "bmt_gate" / "resources"
INFRA_TERRAFORM = Path("infra/terraform")
INFRA_SCRIPTS = Path("infra/scripts")
IMAGE_SCRIPTS = Path("backend/scripts")
TOOLS_SCRIPTS = Path("tools/scripts")

# BMT local layout (runner libs + shared native deps). Relative to repo root.
DEFAULT_BMT_ROOT = Path("local")
BMT_DEPS_SUBDIR = Path("dependencies")
BMT_PROJECT_LIB_SUBDIR = Path("lib")
