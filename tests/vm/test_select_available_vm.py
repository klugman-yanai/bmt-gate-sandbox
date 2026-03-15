"""Tests for select-available-vm: reuse RUNNING VMs without stopping."""

from __future__ import annotations

from pathlib import Path

import pytest
from ci.vm import VmManager


@pytest.fixture(autouse=True)
def _required_bmt_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCS_BUCKET", "bucket-a")
    monkeypatch.setenv("GCP_WIF_PROVIDER", "projects/1/locations/global/workloadIdentityPools/p/providers/p")
    monkeypatch.setenv("GCP_SA_EMAIL", "bmt@example.iam.gserviceaccount.com")


def test_select_available_vm_reuses_running_without_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When only RUNNING VMs exist, select one and set vm_reused_running=true."""
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("BMT_LIVE_VM", "bmt-gate")  # base name: expands to bmt-gate-blue, bmt-gate-green
    monkeypatch.setenv("GITHUB_RUN_ID", "0")

    monkeypatch.setattr("ci.vm._vm_status", lambda _p, _z, _name: "RUNNING")

    VmManager.from_env().select()
    content = github_output.read_text(encoding="utf-8")
    # run_id 0 % 2 = 0 → first VM (bmt-gate-blue)
    assert "selected_vm=bmt-gate-blue" in content
    assert "vm_reused_running=true" in content


def test_select_available_vm_prefers_terminated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When a TERMINATED VM exists alongside RUNNING, select the terminated one."""
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("BMT_LIVE_VM", "bmt-gate")  # base name: expands to bmt-gate-blue, bmt-gate-green
    monkeypatch.setenv("GITHUB_RUN_ID", "456")

    def _status(_p: str, _z: str, name: str) -> str:
        return "TERMINATED" if name == "bmt-gate-blue" else "RUNNING"

    monkeypatch.setattr("ci.vm._vm_status", _status)

    VmManager.from_env().select()

    content = github_output.read_text(encoding="utf-8")
    assert "selected_vm=bmt-gate-blue" in content
    assert "vm_reused_running=false" in content


def test_select_available_vm_blue_green_sibling_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When BMT_LIVE_VM is a base name but only the -blue VM exists (single-VM Pulumi setup),
    the pool shrinks to just bmt-gate-blue and selection proceeds normally."""
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("BMT_LIVE_VM", "bmt-gate")  # base name: expands to bmt-gate-blue, bmt-gate-green
    monkeypatch.setenv("GITHUB_RUN_ID", "99")

    monkeypatch.setattr(
        "ci.vm._vm_status",
        lambda _p, _z, name: "TERMINATED" if name == "bmt-gate-blue" else "unknown",
    )

    VmManager.from_env().select()

    content = github_output.read_text(encoding="utf-8")
    assert "selected_vm=bmt-gate-blue" in content
    assert "vm_reused_running=false" in content


def test_select_available_vm_run_id_assigns_among_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When only RUNNING VMs exist, assignment uses run_id % len(running)."""
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("BMT_LIVE_VM", "bmt-gate")  # base name: expands to bmt-gate-blue, bmt-gate-green
    monkeypatch.setenv("GITHUB_RUN_ID", "1")

    monkeypatch.setattr("ci.vm._vm_status", lambda _p, _z, _name: "RUNNING")

    VmManager.from_env().select()

    content = github_output.read_text(encoding="utf-8")
    assert "vm_reused_running=true" in content
    # run_id 1 % 2 = 1 → second VM (bmt-gate-green)
    assert "selected_vm=bmt-gate-green" in content
