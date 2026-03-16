"""Callable entry points for watcher and orchestrator (L5 — imports heavy modules).

These accept typed config objects and bridge to the existing implementation.
Phase 3 will inline the logic; for now these delegate to vm_watcher.main()
and root_orchestrator via subprocess (matching current behavior).
"""

from __future__ import annotations

import argparse
import logging
import os

from gcp.image.entrypoint_config import OrchestratorConfig, WatcherConfig

logger = logging.getLogger(__name__)


def run_watcher(config: WatcherConfig) -> int:
    """Run the trigger watcher. Bridges typed config to vm_watcher.main()."""
    # Ensure env vars that vm_watcher and downstream code read are set
    os.environ.setdefault("GCS_BUCKET", config.bucket)
    os.environ.setdefault("BMT_REPO_ROOT", str(config.repo_root))
    if config.gcp_project:
        os.environ.setdefault("GCP_PROJECT", config.gcp_project)
    os.environ.setdefault("BMT_WORKSPACE_ROOT", str(config.workspace_root))
    if not config.self_stop:
        os.environ["BMT_SELF_STOP"] = "0"

    # Build an argparse.Namespace matching what vm_watcher.main() expects
    args = argparse.Namespace(
        bucket=config.bucket,
        poll_interval_sec=config.poll_interval_sec,
        workspace_root=str(config.workspace_root),
        exit_after_run=config.exit_after_run,
        idle_timeout_sec=config.idle_timeout_sec,
        subscription=config.subscription,
        gcp_project=config.gcp_project,
    )

    # Patch vm_watcher.parse_args to return our pre-built args, then call main()
    from gcp.image import vm_watcher

    _original_parse = vm_watcher.parse_args
    vm_watcher.parse_args = lambda: args  # type: ignore[assignment]
    try:
        return vm_watcher.main()
    finally:
        vm_watcher.parse_args = _original_parse  # type: ignore[assignment]


def run_orchestrator(config: OrchestratorConfig) -> int:
    """Run a single BMT leg. Bridges typed config to root_orchestrator."""
    os.environ.setdefault("GCS_BUCKET", config.bucket)
    os.environ.setdefault("BMT_REPO_ROOT", str(config.repo_root))

    from gcp.image import root_orchestrator

    # Build argparse.Namespace matching root_orchestrator expectations
    args = argparse.Namespace(
        bucket=config.bucket,
        project=config.project,
        bmt_id=config.bmt_id,
        run_id=config.run_id,
        workspace_root=str(config.workspace_root),
        run_context=config.run_context,
        summary_out=str(config.summary_out),
    )

    # root_orchestrator.main() uses parse_args internally; patch it
    _original_parse = root_orchestrator.parse_args
    root_orchestrator.parse_args = lambda: args  # type: ignore[assignment]
    try:
        return root_orchestrator.main()
    finally:
        root_orchestrator.parse_args = _original_parse  # type: ignore[assignment]
