"""Tests for fallback terminal status emission helper in workflow shell commands."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _run_shell(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )


def test_post_handoff_timeout_status_posts_error_when_allowed(tmp_path: Path) -> None:
    calls_file = tmp_path / "calls.txt"
    script = f"""
set -euo pipefail
source .github/scripts/workflows/github_api.sh
source .github/scripts/workflows/cmd/failure.sh
gh_should_post_failure_status() {{ return 0; }}
gh_post_status() {{ printf '%s\\n' "$*" > "{calls_file}"; return 0; }}
bmt_cmd_post_handoff_timeout_status
"""
    env = os.environ.copy()
    env.update(
        {
            "REPOSITORY": "owner/repo",
            "HEAD_SHA": "abc123",
            "GITHUB_TOKEN": "token",
            "BMT_STATUS_CONTEXT": "BMT Gate",
        }
    )

    result = _run_shell(script, env)

    assert result.returncode == 0, result.stderr
    logged = calls_file.read_text(encoding="utf-8").strip()
    assert "owner/repo" in logged
    assert "abc123" in logged
    assert "error" in logged
    assert "BMT Gate" in logged
    assert "BMT cancelled: VM handshake timeout before pickup." in logged


def test_post_handoff_timeout_status_skips_when_context_already_terminal(tmp_path: Path) -> None:
    calls_file = tmp_path / "calls.txt"
    script = f"""
set -euo pipefail
source .github/scripts/workflows/github_api.sh
source .github/scripts/workflows/cmd/failure.sh
gh_should_post_failure_status() {{ return 1; }}
gh_post_status() {{ printf 'called' > "{calls_file}"; return 0; }}
bmt_cmd_post_handoff_timeout_status
"""
    env = os.environ.copy()
    env.update(
        {
            "REPOSITORY": "owner/repo",
            "HEAD_SHA": "abc123",
            "GITHUB_TOKEN": "token",
            "BMT_STATUS_CONTEXT": "BMT Gate",
        }
    )

    result = _run_shell(script, env)

    assert result.returncode == 0, result.stderr
    assert not calls_file.exists()
