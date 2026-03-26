"""Shared test sentinels — single source of truth for synthetic values.

Using named sentinels instead of scattered magic strings makes tests easier to
read (``FAKE_SHA`` vs a raw 40-char hex string) and keeps values in one place
so they can be updated without a shotgun edit.

Production constants (e.g. ``STATUS_CONTEXT``) should be imported from their
canonical location (``backend.config.constants``) rather than duplicated here.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Git / GitHub
# ---------------------------------------------------------------------------
FAKE_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
"""40-char hex commit SHA for tests that need *some* valid-looking SHA."""

FAKE_SHA_ALT = "0123456789abcdef0123456789abcdef01234567"
"""Alternate SHA — use when a test needs two distinct values."""

FAKE_SHA_MISMATCH = "ffffffffffffffffffffffffffffffffffffffff"
"""SHA that intentionally differs from the above — for mismatch tests."""

FAKE_REPO = "owner/repo"
"""Synthetic ``GITHUB_REPOSITORY`` value (owner/name)."""

FAKE_HEAD_BRANCH = "main"
FAKE_HEAD_EVENT = "push"

# ---------------------------------------------------------------------------
# GCP / Cloud Run
# ---------------------------------------------------------------------------
FAKE_GCP_PROJECT = "demo-project"
FAKE_REGION = "europe-west4"
FAKE_BUCKET = "demo-bucket"
FAKE_CONTROL_JOB = "bmt-control"

# ---------------------------------------------------------------------------
# Workflow / BMT
# ---------------------------------------------------------------------------
FAKE_WORKFLOW_ID = "wf-123"
"""Default fake workflow-run-id for orchestration tests."""

FAKE_RUN_ID = "run-xyz"

SYNTH_PROJECT = "acme"
"""Synthetic project name for scaffold / integration tests."""

SYNTH_BMT_SLUG = "wake_word_quality"
"""Default BMT name (manifest ``bmt_slug``) paired with ``SYNTH_PROJECT``."""

# ---------------------------------------------------------------------------
# Artifact Registry
# ---------------------------------------------------------------------------
FAKE_IMAGE_BASE = "europe-west4-docker.pkg.dev/proj-x/my-repo/bmt-orchestrator"
"""Artifact Registry image base used in tag-probe tests."""
