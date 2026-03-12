"""Tests for select-available-vm: reuse RUNNING VMs without stopping."""

from __future__ import annotations

from pathlib import Path

import pytest
from cli.commands import vm as vm_cmd


@pytest.fixture(autouse=True)
def _required_bmt_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCS_BUCKET", "bucket-a")
    monkeypatch.setenv("GCP_WIF_PROVIDER", "projects/1/locations/global/workloadIdentityPools/p/providers/p")
    monkeypatch.setenv("GCP_SA_EMAIL", "bmt@example.iam.gserviceaccount.com")


def test_select_available_vm_reuses_running_without_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When only RUNNING VMs exist, select one and set vm_reused_running=true; do not call _stop_and_wait."""
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_VM_NAME", "vm-only")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")

    stop_calls: list[tuple[str, str, str]] = []

    def _record_stop(project: str, zone: str, instance_name: str) -> None:
        stop_calls.append((project, zone, instance_name))

    monkeypatch.setattr(vm_cmd, "_stop_and_wait", _record_stop)
    monkeypatch.setattr(
        vm_cmd,
        "_vm_status",
        lambda _p, _z, name: "RUNNING" if name == "vm-only" else "unknown",
    )

    vm_cmd.run_select_available_vm()

    assert not stop_calls, "Should not stop the VM when reusing RUNNING"
    content = github_output.read_text(encoding="utf-8")
    assert "selected_vm=vm-only" in content
    assert "vm_reused_running=true" in content


def test_select_available_vm_prefers_terminated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When a TERMINATED VM exists, select it and set vm_reused_running=false."""
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_VM_NAME", "fallback-vm")  # required by require_gcp(); pool used for selection
    monkeypatch.setenv("BMT_VM_POOL", "vm-a,vm-b")
    monkeypatch.setenv("GITHUB_RUN_ID", "456")

    def _status(_p: str, _z: str, name: str) -> str:
        return "TERMINATED" if name == "vm-a" else "RUNNING"

    monkeypatch.setattr(vm_cmd, "_vm_status", _status)

    vm_cmd.run_select_available_vm()

    content = github_output.read_text(encoding="utf-8")
    assert "selected_vm=vm-a" in content
    assert "vm_reused_running=false" in content


def test_select_available_vm_run_id_assigns_among_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When only RUNNING VMs exist, assignment uses run_id % len(running)."""
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_VM_NAME", "fallback-vm")  # required by require_gcp(); pool used for selection
    monkeypatch.setenv("BMT_VM_POOL", "vm-1,vm-2")
    monkeypatch.setenv("GITHUB_RUN_ID", "1")

    monkeypatch.setattr(
        vm_cmd,
        "_vm_status",
        lambda _p, _z, _name: "RUNNING",
    )

    vm_cmd.run_select_available_vm()

    content = github_output.read_text(encoding="utf-8")
    assert "vm_reused_running=true" in content
    # run_id 1 % 2 = 1 -> second VM
    assert "selected_vm=vm-2" in content
