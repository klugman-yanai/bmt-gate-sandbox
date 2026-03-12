"""Shared repository path constants for tools and CI.

Single source of truth for default config/runtime roots. Env contract and behavioral
defaults live in tools/repo/vars_contract.py; infra-derived vars from Terraform. See
tools/shared/env_contract.default_contract_path().

All paths are pathlib.Path; relative ones are relative to repo root. Resolve against
repo root when needed: (repo_root / DEFAULT_CONFIG_ROOT).resolve().
"""

from pathlib import Path

# Default roots for code mirror and runtime seed (relative to repo root).
DEFAULT_CONFIG_ROOT = Path("gcp/code")
DEFAULT_RUNTIME_ROOT = Path("gcp/runtime")

# BMT local layout (runner libs + shared native deps). Relative to repo root.
# Override with BMT_ROOT env (e.g. "gcp/bmt" or absolute path).
DEFAULT_BMT_ROOT = Path("gcp/bmt")
BMT_DEPS_SUBDIR = Path("dependencies")
BMT_PROJECT_LIB_SUBDIR = Path("lib")

# Terraform is source of truth for repo vars; no legacy config paths.
# Use shared env_contract.default_contract_path() for the contract.
