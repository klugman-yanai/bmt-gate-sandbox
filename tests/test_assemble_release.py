"""Smoke tests for scripts/assemble_release.py (CI uses --skip-secrets)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parent.parent


def test_assemble_release_skip_secrets() -> None:
    env = {**os.environ, "RELEASE_SKIP_SECRETS": "1"}
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "assemble_release.py")],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    manifest = REPO / ".github-release" / "bmt_release.json"
    data = json.loads(manifest.read_text())
    assert len(data["source_sha"]) >= 7
    assert data["skip_secrets"] is True
    wf = REPO / ".github-release" / "workflows"
    assert (wf / "internal" / "trigger-ci.yml").is_file()
    assert (wf / "internal" / "code-owner-enforcement.yml").is_file()
    root_names = {p.name for p in wf.glob("*.yml")}
    required_root = frozenset(
        {
            "bmt-handoff.yml",
            "build-and-test.yml",
            "clang-format-auto-fix.yml",
        }
    )
    missing = required_root - root_names
    assert not missing, (
        f"missing root workflows {sorted(missing)}; have {sorted(root_names)} (extra root YAMLs are allowed)"
    )
