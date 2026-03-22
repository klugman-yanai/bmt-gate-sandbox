"""Helpers for Cloud Run workflow rendering and IAM derivation."""

from __future__ import annotations

from pathlib import Path

_WORKFLOW_TIMEOUT_TOKEN = "__CONNECTOR_TIMEOUT_SEC__"
_GITHUB_APP_SECRET_NAMES = (
    "GITHUB_APP_ID",
    "GITHUB_APP_INSTALLATION_ID",
    "GITHUB_APP_PRIVATE_KEY",
    "GITHUB_APP_DEV_ID",
    "GITHUB_APP_DEV_INSTALLATION_ID",
    "GITHUB_APP_DEV_PRIVATE_KEY",
)


def render_workflow_source(template_path: Path, connector_timeout_sec: int) -> str:
    if connector_timeout_sec <= 0:
        raise ValueError(f"connector_timeout_sec must be positive, got {connector_timeout_sec}")

    template = template_path.read_text(encoding="utf-8")
    if _WORKFLOW_TIMEOUT_TOKEN not in template:
        raise ValueError(f"workflow template missing token {_WORKFLOW_TIMEOUT_TOKEN}")

    return template.replace(_WORKFLOW_TIMEOUT_TOKEN, str(connector_timeout_sec))


def github_app_secret_names() -> list[str]:
    return list(_GITHUB_APP_SECRET_NAMES)
