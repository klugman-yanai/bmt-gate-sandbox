"""Smoke tests for scripts/assemble_release.py (CI uses --skip-secrets)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
    assert (wf / "bmt-handoff.yml").is_file()
    assert (wf / "build-and-test.yml").is_file()
    assert (wf / "clang-format-auto-fix.yml").is_file()
    assert (wf / "internal" / "trigger-ci.yml").is_file()
    assert (wf / "internal" / "code-owner-enforcement.yml").is_file()
    root_yml = list(wf.glob("*.yml"))
    assert len(root_yml) == 4, f"expected 4 root workflows, got {[p.name for p in root_yml]}"
    assert (wf / "trigger-ci-pr.yml").is_file()
