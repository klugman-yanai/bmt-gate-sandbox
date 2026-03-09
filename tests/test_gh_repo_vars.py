"""Tests for repo vars drift tooling with branch-rule sourced status context."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools"))

import gh_repo_vars as repo_vars  # type: ignore[import-not-found]  # noqa: E402


def _cp(*, rc: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_load_contract_parses_branch_rule_checks(tmp_path: Path) -> None:
    contract = {
        "contexts": {
            "github_repo_vars": {
                "required": ["GCS_BUCKET"],
                "optional": ["BMT_STATUS_CONTEXT"],
            }
        },
        "defaults": {"BMT_STATUS_CONTEXT": "BMT Gate"},
        "consistency_checks": {
            "repo_var_vs_branch_required_status_context": [
                {
                    "repo_var": "BMT_STATUS_CONTEXT",
                    "branch": "dev",
                    "context_substring": "bmt",
                }
            ]
        },
    }
    contract_path = tmp_path / "env_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    ordered, required, defaults, checks = repo_vars._load_contract(contract_path)

    assert ordered == ["GCS_BUCKET", "BMT_STATUS_CONTEXT"]
    assert required == {"GCS_BUCKET"}
    assert defaults["BMT_STATUS_CONTEXT"] == "BMT Gate"
    assert len(checks) == 1
    assert checks[0].repo_var == "BMT_STATUS_CONTEXT"
    assert checks[0].branch == "dev"
    assert checks[0].context_substring == "bmt"


def test_resolve_branch_rule_values_uses_single_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd == ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]:
            return _cp(stdout="owner/repo\n")
        if cmd == ["gh", "api", "repos/owner/repo/rules/branches/dev"]:
            payload = [
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [
                            {"context": "BMT Gate"},
                        ]
                    },
                }
            ]
            return _cp(stdout=json.dumps(payload))
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(repo_vars, "_run", _fake_run)

    checks = [repo_vars.RepoVarBranchStatusContextCheck(repo_var="BMT_STATUS_CONTEXT", branch="dev")]
    resolved, available = repo_vars._resolve_branch_rule_repo_var_values(
        checks,
        declared={},
        current={"BMT_STATUS_CONTEXT": "final-gate"},
        defaults={"BMT_STATUS_CONTEXT": "BMT Gate"},
    )

    assert resolved == {"BMT_STATUS_CONTEXT": "BMT Gate"}
    assert available["BMT_STATUS_CONTEXT"] == ["BMT Gate"]


def test_resolve_branch_rule_values_ambiguous_prefers_current(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd == ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]:
            return _cp(stdout="owner/repo\n")
        if cmd == ["gh", "api", "repos/owner/repo/rules/branches/dev"]:
            payload = [
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [
                            {"context": "build-and-test"},
                            {"context": "BMT Gate"},
                        ]
                    },
                }
            ]
            return _cp(stdout=json.dumps(payload))
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(repo_vars, "_run", _fake_run)

    checks = [repo_vars.RepoVarBranchStatusContextCheck(repo_var="BMT_STATUS_CONTEXT", branch="dev")]
    resolved, _available = repo_vars._resolve_branch_rule_repo_var_values(
        checks,
        declared={},
        current={"BMT_STATUS_CONTEXT": "BMT Gate"},
        defaults={},
    )

    assert resolved["BMT_STATUS_CONTEXT"] == "BMT Gate"


def test_resolve_branch_rule_values_selector_miss_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd == ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]:
            return _cp(stdout="owner/repo\n")
        if cmd == ["gh", "api", "repos/owner/repo/rules/branches/dev"]:
            payload = [
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [
                            {"context": "build-and-test"},
                        ]
                    },
                }
            ]
            return _cp(stdout=json.dumps(payload))
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(repo_vars, "_run", _fake_run)

    checks = [
        repo_vars.RepoVarBranchStatusContextCheck(
            repo_var="BMT_STATUS_CONTEXT",
            branch="dev",
            context_substring="bmt",
        )
    ]
    with pytest.raises(RuntimeError, match="context_substring"):
        repo_vars._resolve_branch_rule_repo_var_values(
            checks,
            declared={},
            current={},
            defaults={},
        )
