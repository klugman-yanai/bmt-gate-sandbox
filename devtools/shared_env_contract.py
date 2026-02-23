"""Shared helpers for loading the repository env contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_contract_path() -> Path:
    return _repo_root() / "config" / "env_contract.json"


def load_env_contract(path: str | None = None) -> dict[str, Any]:
    contract_path = Path(path).expanduser().resolve() if path else default_contract_path()
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
