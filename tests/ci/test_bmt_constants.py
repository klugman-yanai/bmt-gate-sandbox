"""Smoke test: bmt_constants facade re-exports all expected CI symbols."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_bmt_constants_exports_all_expected_symbols() -> None:
    from ci import bmt_constants  # noqa: PLC0415

    # Decision constants (from core.py usage)
    assert hasattr(bmt_constants, "DECISION_ACCEPTED")
    assert hasattr(bmt_constants, "DECISION_ACCEPTED_WITH_WARNINGS")
    assert hasattr(bmt_constants, "DECISION_REJECTED")
    assert hasattr(bmt_constants, "DECISION_TIMEOUT")
    assert hasattr(bmt_constants, "GateDecision")
    assert hasattr(bmt_constants, "sanitize_run_id")

    # Workflow dispatch constants (from workflow_dispatch.py usage)
    assert hasattr(bmt_constants, "DEFAULT_WORKFLOW_NAME")
    assert hasattr(bmt_constants, "ENV_GCP_PROJECT")
    assert hasattr(bmt_constants, "ENV_GCS_BUCKET")
    assert hasattr(bmt_constants, "ENV_CLOUD_RUN_REGION")
    assert hasattr(bmt_constants, "is_truthy_env_value")

    # Config constants (from config.py usage)
    assert hasattr(bmt_constants, "DEFAULT_CLOUD_RUN_REGION")
    assert hasattr(bmt_constants, "ENV_BMT_CONTROL_JOB")
    assert hasattr(bmt_constants, "ENV_BMT_STATUS_CONTEXT")
    assert hasattr(bmt_constants, "ENV_BMT_TASK_HEAVY_JOB")
    assert hasattr(bmt_constants, "ENV_BMT_TASK_STANDARD_JOB")
    assert hasattr(bmt_constants, "ENV_GCP_SA_EMAIL")
    assert hasattr(bmt_constants, "ENV_GCP_WIF_PROVIDER")
    assert hasattr(bmt_constants, "STATUS_CONTEXT")
