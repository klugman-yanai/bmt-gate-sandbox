"""Tests for fallback terminal status emission (Python bmt post-handoff-timeout-status).

The post-handoff-timeout-status behavior is implemented in cli.commands.workflow
(run_post_handoff_timeout_status) and is exercised by the bmt-failure-fallback action.
When the full CLI includes the workflow module, add unit tests here that mock
github_api.should_post_failure_status and post_commit_status to assert posting
vs skipping when context is already terminal.
"""

from __future__ import annotations
