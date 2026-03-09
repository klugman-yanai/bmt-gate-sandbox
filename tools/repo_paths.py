"""Shared repository path constants for tools and CI.

Single source of truth for default config/runtime roots and config file paths
so that scripts stay in sync when the layout is renamed.
"""

# Default roots for code mirror and runtime seed (relative to repo root).
DEFAULT_CONFIG_ROOT = "deploy/code"
DEFAULT_RUNTIME_ROOT = "deploy/runtime"

# Config file paths relative to repo root.
DEFAULT_ENV_CONTRACT_PATH = "config/env_contract.json"
DEFAULT_REPO_VARS_PATH = "config/repo_vars.toml"
