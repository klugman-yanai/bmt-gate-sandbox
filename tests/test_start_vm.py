"""Tests for .github/scripts/ci/commands/start_vm.py env resolution."""

import pytest

from ci.commands.start_vm import _required_env


def test_required_env_returns_trimmed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BMT_VM_NAME", "  bmt-performance-gate  ")
    assert _required_env("BMT_VM_NAME") == "bmt-performance-gate"


def test_required_env_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    with pytest.raises(RuntimeError, match="Set GCP_PROJECT"):
        _required_env("GCP_PROJECT")


def test_required_env_raises_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_ZONE", "   ")
    with pytest.raises(RuntimeError, match="Set GCP_ZONE"):
        _required_env("GCP_ZONE")
