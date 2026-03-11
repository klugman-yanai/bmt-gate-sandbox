"""Tests for repo vars drift tooling with branch-rule sourced status context."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import gh_repo_vars as repo_vars  # type: ignore[import-not-found]
import pytest
from shared_env_contract import default_contract_path


def _cp(*, rc: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_load_contract_parses_branch_rule_checks() -> None:
    """Load real contract (Python module + branch-status-context) and assert structure."""
    contract_path = default_contract_path()
    ordered, required, defaults, checks = repo_vars._load_contract(contract_path)

    assert "GCS_BUCKET" in required
    assert "BMT_STATUS_CONTEXT" in ordered
    assert defaults.get("BMT_STATUS_CONTEXT") == "BMT Gate"
    assert len(checks) >= 1
    bmt_check = next((c for c in checks if c.repo_var == "BMT_STATUS_CONTEXT" and c.branch == "dev"), None)
    assert bmt_check is not None
    assert bmt_check.context_substring == "bmt"


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


def test_validate_wif_provider_format_invalid_raises() -> None:
    desired = {
        "GCP_WIF_PROVIDER": "projects/not-a-number/locations/global/workloadIdentityPools/pool/providers/provider",
        "GCP_PROJECT": "proj-a",
    }
    with pytest.raises(RuntimeError, match="Invalid GCP_WIF_PROVIDER format"):
        repo_vars._validate_wif_provider_consistency(desired)


def test_validate_wif_provider_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    desired = {
        "GCP_WIF_PROVIDER": "projects/123/locations/global/workloadIdentityPools/pool/providers/provider",
        "GCP_PROJECT": "proj-a",
    }

    monkeypatch.setattr(repo_vars.shutil, "which", lambda _name: "/usr/bin/gcloud")
    monkeypatch.setattr(
        repo_vars,
        "_run",
        lambda cmd: _cp(stdout="999\n") if cmd[:3] == ["gcloud", "projects", "describe"] else _cp(rc=1),
    )
    with pytest.raises(RuntimeError, match="project number mismatch"):
        repo_vars._validate_wif_provider_consistency(desired)


def test_validate_wif_provider_skips_when_gcloud_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    desired = {
        "GCP_WIF_PROVIDER": "projects/123/locations/global/workloadIdentityPools/pool/providers/provider",
        "GCP_PROJECT": "proj-a",
    }
    monkeypatch.setattr(repo_vars.shutil, "which", lambda _name: None)
    warnings = repo_vars._validate_wif_provider_consistency(desired)
    assert any("gcloud not found" in item for item in warnings)
