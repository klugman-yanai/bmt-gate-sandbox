"""Shared helpers for loading the repository env contract.

Contract and behavioral defaults live in repo vars_contract (Python). When path
is None or the contract module path, the contract is built from that module plus
infra/branch-status-context.json. When path is a file (e.g. tests), load that JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bmtcontract.constants import ENV_CLOUD_RUN_REGION, ENV_GCP_PROJECT, ENV_GCS_BUCKET

from tools.repo.paths import repo_root


def _contract_module_path() -> Path:
    return repo_root() / "tools" / "repo" / "vars_contract.py"


def default_contract_path() -> Path:
    """Path to the contract module (contract is built from Python, not a file)."""
    return _contract_module_path()


def _branch_status_context_path() -> Path:
    return repo_root() / "infra" / "branch-status-context.json"


def _build_contract_from_python() -> dict[str, Any]:
    """Build contract from vars_contract + branch-status-context.json."""
    from tools.repo.vars_contract import REPO_VARS_CONTRACT

    required = list(REPO_VARS_CONTRACT.required)
    optional = list(REPO_VARS_CONTRACT.optional)
    secrets = list(REPO_VARS_CONTRACT.manual_vars)
    optional = [s for s in optional if s not in required]
    optional.extend(s for s in secrets if s not in optional)

    defaults = REPO_VARS_CONTRACT.default_dict()

    consistency_checks: dict[str, Any] = {"repo_vs_vm_metadata": [ENV_GCS_BUCKET]}
    branch_path = _branch_status_context_path()
    if branch_path.is_file():
        with branch_path.open(encoding="utf-8") as f:
            branch_data = json.load(f)
        if isinstance(branch_data, dict):
            bc = branch_data.get("repo_var_vs_branch_required_status_context")
            if isinstance(bc, list):
                consistency_checks["repo_var_vs_branch_required_status_context"] = bc

    return {
        "version": 1,
        "description": "Contract built from vars_contract and branch-status-context.",
        "contexts": {
            "github_repo_vars": {"required": required, "optional": optional},
            "cloud_run_runtime_env": {
                "required": [ENV_GCS_BUCKET, ENV_GCP_PROJECT],
                "optional": [ENV_CLOUD_RUN_REGION],
            },
            "local_dev_env": {"optional": [ENV_GCS_BUCKET, ENV_GCP_PROJECT, ENV_CLOUD_RUN_REGION]},
        },
        "consistency_checks": consistency_checks,
        "defaults": defaults,
        "recommended_minimal_input": required,
    }


def load_env_contract(path: str | None = None) -> dict[str, Any]:
    """Load env contract. If path is None or the contract module path, build from Python. Else load JSON file (tests)."""
    if path is None:
        return _build_contract_from_python()
    contract_path = Path(path).expanduser().resolve()
    if contract_path == _contract_module_path().resolve():
        return _build_contract_from_python()
    if not contract_path.is_file():
        raise FileNotFoundError(f"Contract not found: {contract_path}")
    with contract_path.open(encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid env contract at {contract_path}: expected top-level object")
    return payload


def list_context_vars(contract: dict[str, Any], context: str, kind: str) -> list[str]:
    contexts = contract.get("contexts", {})
    if not isinstance(contexts, dict):
        return []
    section = contexts.get(context, {})
    if not isinstance(section, dict):
        return []
    values = section.get(kind, [])
    if not isinstance(values, list):
        return []
    return [str(v) for v in values if isinstance(v, str)]


def list_repo_vs_vm_metadata_vars(contract: dict[str, Any]) -> list[str]:
    checks = contract.get("consistency_checks", {})
    if not isinstance(checks, dict):
        return []
    values = checks.get("repo_vs_vm_metadata", [])
    if not isinstance(values, list):
        return []
    return [str(v) for v in values if isinstance(v, str)]


def list_repo_var_vs_branch_required_status_context_checks(contract: dict[str, Any]) -> list[dict[str, str]]:
    checks = contract.get("consistency_checks", {})
    if not isinstance(checks, dict):
        return []
    values = checks.get("repo_var_vs_branch_required_status_context", [])
    if not isinstance(values, list):
        return []

    out: list[dict[str, str]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        repo_var = str(item.get("repo_var", "")).strip()
        branch = str(item.get("branch", "")).strip()
        if not repo_var or not branch:
            continue
        row: dict[str, str] = {"repo_var": repo_var, "branch": branch}
        context_substring_raw = item.get("context_substring")
        if isinstance(context_substring_raw, str):
            context_substring = context_substring_raw.strip()
            if context_substring:
                row["context_substring"] = context_substring
        out.append(row)
    return out
