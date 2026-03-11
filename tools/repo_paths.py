"""Shared repository path constants for tools and CI.

Single source of truth for default config/runtime roots. Env contract and repo vars
are Terraform-backed; see infra/terraform/repo-vars-mapping.json and
tools/shared_env_contract.default_contract_path().
"""

# Default roots for code mirror and runtime seed (relative to repo root).
DEFAULT_CONFIG_ROOT = "gcp/code"
DEFAULT_RUNTIME_ROOT = "gcp/runtime"

# Terraform is source of truth for repo vars; no legacy config paths.
# Use shared_env_contract.default_contract_path() for the contract.
