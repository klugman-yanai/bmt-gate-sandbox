"""GCP console URL helpers (no I/O, no SDK dependency)."""

from __future__ import annotations

__all__ = ["workflow_execution_console_url"]


def workflow_execution_console_url(
    *, project: str, region: str, workflow_name: str, execution_name: str
) -> str:
    execution_id = execution_name.rsplit("/", 1)[-1].strip()
    return (
        "https://console.cloud.google.com/workflows/workflow/"
        f"{region}/{workflow_name}/execution/{execution_id}?project={project}"
    )
