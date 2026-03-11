"""Shared helpers for loading the repository env contract.

Terraform is the source of truth. The contract is built from
infra/terraform/repo-vars-mapping.json and infra/branch-status-context.json.
Legacy config/env_contract.json paths are still supported for tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_contract_path() -> Path:
    """Path to the Terraform repo-vars mapping (source of truth for var list)."""
    return _repo_root() / "infra" / "terraform" / "repo-vars-mapping.json"


def _branch_status_context_path() -> Path:
    return _repo_root() / "infra" / "branch-status-context.json"


def _is_terraform_mapping_path(path: Path) -> bool:
    try:
        path = path.resolve()
        mapping = default_contract_path().resolve()
        return path == mapping or "repo-vars-mapping.json" in path.parts
    except Exception:
        return False


def _build_contract_from_terraform_mapping() -> dict[str, Any]:
    """Build a contract dict from Terraform mapping + branch-status-context (same shape as legacy)."""
    mapping_path = default_contract_path()
    if not mapping_path.is_file():
        raise FileNotFoundError(f"Terraform mapping not found: {mapping_path}")
    with mapping_path.open(encoding="utf-8") as f:
        mapping = json.load(f)
    if not isinstance(mapping, dict):
        raise ValueError("repo-vars-mapping.json must be a JSON object")

    required = list(mapping.get("required_from_terraform") or [])
    optional = list(mapping.get("optional_from_terraform") or [])
    secrets = list(mapping.get("secrets_not_in_terraform") or [])
    if not isinstance(required, list):
        required = []
    if not isinstance(optional, list):
        optional = []
    if not isinstance(secrets, list):
        secrets = []
    required = [str(v) for v in required if isinstance(v, str)]
    optional = [str(v) for v in optional if isinstance(v, str)]
    optional.extend(str(s) for s in secrets if isinstance(s, str) and s not in optional)

    defaults_raw = mapping.get("defaults") or {}
    defaults: dict[str, str] = {}
    if isinstance(defaults_raw, dict):
        for k, v in defaults_raw.items():
            if isinstance(k, str) and k:
                defaults[k] = str(v)

    consistency_checks: dict[str, Any] = {"repo_vs_vm_metadata": ["GCS_BUCKET"]}
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
        "description": "Contract built from Terraform repo-vars-mapping and branch-status-context.",
        "contexts": {
            "github_repo_vars": {"required": required, "optional": optional},
            "vm_metadata": {"required": ["GCS_BUCKET"], "optional": ["BMT_REPO_ROOT"]},
            "vm_runtime_env": {"optional": []},
            "local_dev_env": {"optional": ["GCS_BUCKET", "GCP_PROJECT", "GCP_ZONE", "BMT_VM_NAME"]},
        },
        "consistency_checks": consistency_checks,
        "defaults": defaults,
        "recommended_minimal_input": required,
    }


def load_env_contract(path: str | None = None) -> dict[str, Any]:
    """Load env contract. If path is Terraform mapping or None, build from Terraform + branch-status."""
    if path is None:
        contract_path = default_contract_path()
    else:
        contract_path = Path(path).expanduser().resolve()
    if not contract_path.is_file():
        raise FileNotFoundError(f"Contract not found: {contract_path}")
    if path is None or _is_terraform_mapping_path(contract_path):
        return _build_contract_from_terraform_mapping()
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
