"""Shared repository path constants for tools and CI.

Single source of truth for default config/runtime roots. Env contract and behavioral
defaults live in tools/repo/vars_contract.py; infra-derived vars from Terraform. See
tools/shared/env_contract.default_contract_path().

All paths are pathlib.Path; relative ones are relative to repo root. Resolve against
repo root when needed: (repo_root() / DEFAULT_CONFIG_ROOT).resolve().
"""

from pathlib import Path


def repo_root() -> Path:
    """Resolve repo root by walking up to a directory containing pyproject.toml, gcp/, and infra/."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "gcp").is_dir() and (parent / "infra").is_dir():
            return parent
    raise RuntimeError(f"Unable to resolve repo root from {here}")


# Default roots for VM mirror and runtime seed (relative to repo root).
DEFAULT_CONFIG_ROOT = Path("gcp/image")
DEFAULT_RUNTIME_ROOT = Path("gcp/remote")

# Other canonical roots (relative to repo root).
GITHUB_BMT_ROOT = Path(".github/bmt")
INFRA_TERRAFORM = Path("infra/terraform")
INFRA_SCRIPTS = Path("infra/scripts")
IMAGE_SCRIPTS = Path("gcp/image/scripts")
TOOLS_SCRIPTS = Path("tools/scripts")

# BMT local layout (runner libs + shared native deps). Relative to repo root.
# Override with BMT_ROOT env (e.g. "gcp/local" or absolute path).
DEFAULT_BMT_ROOT = Path("gcp/local")
BMT_DEPS_SUBDIR = Path("dependencies")
BMT_PROJECT_LIB_SUBDIR = Path("lib")

# Terraform is source of truth for repo vars; no legacy config paths.
# Use shared env_contract.default_contract_path() for the contract.
