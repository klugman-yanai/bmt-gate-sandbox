"""Tests for .github/bmt/ci/vm.py VmManager.start() and env resolution."""

import time

import pytest
import bmt_gate
from bmt_gate.core import require_env as _required_env
from bmt_gate.vm import VmManager
from bmt_gate.vm import _is_truthy
from bmt_gate import core as core_module


@pytest.fixture(autouse=True)
def _required_bmt_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCS_BUCKET", "bucket-a")
    monkeypatch.setenv("GCP_WIF_PROVIDER", "projects/1/locations/global/workloadIdentityPools/p/providers/p")
    monkeypatch.setenv("GCP_SA_EMAIL", "bmt@example.iam.gserviceaccount.com")


def test_required_env_returns_trimmed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BMT_LIVE_VM", "  bmt-performance-gate  ")
    assert _required_env("BMT_LIVE_VM") == "bmt-performance-gate"


def test_required_env_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    with pytest.raises(RuntimeError, match="GCP_PROJECT"):
        _required_env("GCP_PROJECT")


def test_required_env_raises_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_ZONE", "   ")
    with pytest.raises(RuntimeError, match="GCP_ZONE"):
        _required_env("GCP_ZONE")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
        (None, False),
    ],
)
def test_is_truthy(raw: str | None, expected: bool) -> None:
    assert _is_truthy(raw) is expected


def test_start_vm_blocks_manual_without_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("BMT_ALLOW_MANUAL_VM_START", raising=False)

    with pytest.raises(RuntimeError, match="Manual VM start is blocked"):
        VmManager.from_env().start()


def test_start_vm_waits_for_running_and_advanced_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("BMT_VM_START_TIMEOUT_SEC", "30")

    describe_calls = iter(
        [
            {"status": "TERMINATED", "lastStartTimestamp": "old-ts"},
            {"status": "STAGING", "lastStartTimestamp": "old-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
            # stabilization poll(s)
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
        ]
    )
    started: list[bool] = []

    def _fake_start(project: str, zone: str, instance_name: str) -> None:
        assert project == "proj"
        assert zone == "europe-west4-a"  # fixed in config; not overridable via env
        assert instance_name == "vm"
        started.append(True)

    # monotonic: main-loop polls, then stabilization enters and immediately expires
    monotonic_values = iter([0.0, 1.0, 2.0, 3.0, 100.0, 200.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("bmt_gate.vm.vm_start", _fake_start)
    monkeypatch.setattr("bmt_gate.vm.vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)

    VmManager.from_env().start()
    assert started == [True]


def test_start_vm_times_out_when_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr("bmt_gate.vm.VM_START_TIMEOUT_SEC", 1)

    monkeypatch.setattr("bmt_gate.vm.vm_start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "bmt_gate.vm.vm_describe",
        lambda *_args, **_kwargs: {"status": "STAGING", "lastStartTimestamp": "old-ts"},
    )
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)

    monotonic_values = iter([0.0] + [2.0] * 200)
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(RuntimeError, match="did not reach ready"):
        VmManager.from_env().start()


def test_start_vm_continues_when_already_running_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("BMT_VM_START_TIMEOUT_SEC", "5")

    def _raise_already_running(*_args, **_kwargs) -> None:
        raise core_module.GcloudError("Failed to start VM vm: Instance is already running")

    describe_calls = iter(
        [
            {"status": "RUNNING", "lastStartTimestamp": "same-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "same-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "same-ts"},
        ]
    )
    monotonic_values = iter([0.0, 1.0, 100.0, 200.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("bmt_gate.vm.vm_start", _raise_already_running)
    monkeypatch.setattr("bmt_gate.vm.vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)

    VmManager.from_env().start()


def test_start_vm_allows_manual_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.setenv("BMT_VM_START_TIMEOUT_SEC", "5")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("BMT_ALLOW_MANUAL_VM_START", "1")

    describe_calls = iter(
        [
            {"status": "TERMINATED", "lastStartTimestamp": "old-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
            # stabilization poll
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
        ]
    )
    monotonic_values = iter([0.0, 1.0, 100.0, 200.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(bmt_gate.vm, "vm_start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bmt_gate.vm, "vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)

    VmManager.from_env().start()


def test_start_vm_recovers_when_status_drops_during_stabilization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("BMT_VM_START_TIMEOUT_SEC", "10")

    describe_calls = iter(
        [
            {"status": "TERMINATED", "lastStartTimestamp": "old-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts-1"},
            {"status": "STOPPING", "lastStartTimestamp": "new-ts-1"},
            {"status": "STAGING", "lastStartTimestamp": "new-ts-1"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts-2"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts-2"},
        ]
    )
    started: list[bool] = []

    def _fake_start(*_args, **_kwargs) -> None:
        started.append(True)

    monkeypatch.setattr(bmt_gate.vm, "vm_start", _fake_start)
    monkeypatch.setattr(bmt_gate.vm, "vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)

    monotonic_values = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 100.0, 101.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))

    VmManager.from_env().start()
    assert len(started) == 2


def test_start_vm_fails_when_recovery_attempts_are_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("BMT_VM_START_TIMEOUT_SEC", "10")
    monkeypatch.setattr(bmt_gate.vm, "VM_START_RECOVERY_ATTEMPTS", 1)

    describe_calls = iter(
        [
            {"status": "TERMINATED", "lastStartTimestamp": "old-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts-1"},
            {"status": "STOPPING", "lastStartTimestamp": "new-ts-1"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts-2"},
            {"status": "STOPPING", "lastStartTimestamp": "new-ts-2"},
        ]
    )
    monkeypatch.setattr(bmt_gate.vm, "vm_start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bmt_gate.vm, "vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)

    monotonic_values = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(RuntimeError, match="recovery exhausted"):
        VmManager.from_env().start()


def test_start_vm_treats_fingerprint_race_as_idempotent_recovery_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("BMT_VM_START_TIMEOUT_SEC", "10")

    describe_calls = iter(
        [
            {"status": "TERMINATED", "lastStartTimestamp": "old-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts-1"},
            {"status": "STOPPING", "lastStartTimestamp": "new-ts-1"},
            {"status": "STAGING", "lastStartTimestamp": "new-ts-1"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts-2"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts-2"},
        ]
    )
    call_count = {"value": 0}

    def _fake_start(*_args, **_kwargs) -> None:
        call_count["value"] += 1
        if call_count["value"] == 2:
            raise core_module.GcloudError(
                "Failed to start VM vm: The resource is not ready. "
                "'The resource fingerprint changed during the start operation.'"
            )

    monkeypatch.setattr(bmt_gate.vm, "vm_start", _fake_start)
    monkeypatch.setattr(bmt_gate.vm, "vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)

    monotonic_values = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 100.0, 101.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))

    VmManager.from_env().start()
    assert call_count["value"] == 2


def test_start_vm_recovers_from_terminal_state_after_fingerprint_race(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("BMT_VM_START_TIMEOUT_SEC", "10")

    describe_calls = iter(
        [
            {"status": "RUNNING", "lastStartTimestamp": "same-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "same-ts"},
            {"status": "STOPPING", "lastStartTimestamp": "same-ts"},
            {"status": "TERMINATED", "lastStartTimestamp": "same-ts"},
            {"status": "STAGING", "lastStartTimestamp": "same-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
        ]
    )
    call_count = {"value": 0}

    def _fake_start(*_args, **_kwargs) -> None:
        call_count["value"] += 1
        if call_count["value"] == 2:
            raise core_module.GcloudError(
                "Failed to start VM vm: The resource is not ready. "
                "'The resource fingerprint changed during the start operation.'"
            )

    monkeypatch.setattr(bmt_gate.vm, "vm_start", _fake_start)
    monkeypatch.setattr(bmt_gate.vm, "vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)

    monotonic_values = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 100.0, 101.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))

    VmManager.from_env().start()
    assert call_count["value"] == 3


def test_start_vm_recovers_after_initial_idempotent_start_when_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("BMT_VM_START_TIMEOUT_SEC", "10")

    describe_calls = iter(
        [
            {"status": "STOPPING", "lastStartTimestamp": "old-ts"},
            {"status": "STOPPING", "lastStartTimestamp": "old-ts"},
            {"status": "TERMINATED", "lastStartTimestamp": "old-ts"},
            {"status": "STAGING", "lastStartTimestamp": "old-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
        ]
    )
    call_count = {"value": 0}

    def _fake_start(*_args, **_kwargs) -> None:
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise core_module.GcloudError(
                "Failed to start VM vm: The resource is currently stopping. Please try again."
            )

    monkeypatch.setattr(bmt_gate.vm, "vm_start", _fake_start)
    monkeypatch.setattr(bmt_gate.vm, "vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)

    monotonic_values = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 100.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))

    VmManager.from_env().start()
    assert call_count["value"] == 2
