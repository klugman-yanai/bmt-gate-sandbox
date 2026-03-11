"""Shared repository path constants for tools and CI.

Single source of truth for default config/runtime roots. Env contract and behavioral
defaults live in tools/repo/vars_contract.py; infra-derived vars from Terraform. See
tools/shared/env_contract.default_contract_path().
"""

# Default roots for code mirror and runtime seed (relative to repo root).
DEFAULT_CONFIG_ROOT = "gcp/code"
DEFAULT_RUNTIME_ROOT = "gcp/runtime"

# Terraform is source of truth for repo vars; no legacy config paths.
# Use shared env_contract.default_contract_path() for the contract.
