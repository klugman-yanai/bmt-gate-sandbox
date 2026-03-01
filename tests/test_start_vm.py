"""Tests for .github/scripts/ci/commands/start_vm.py env resolution."""

import pytest
from click.testing import CliRunner

from ci.commands import start_vm
from ci.commands.start_vm import _is_truthy, _required_env


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
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_VM_NAME", "vm")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("BMT_ALLOW_MANUAL_VM_START", raising=False)

    result = runner.invoke(start_vm.command, ["--timeout-sec", "1", "--poll-interval-sec", "1"])
    assert result.exit_code != 0
    assert "Manual VM start is blocked by policy" in result.output


def test_start_vm_waits_for_running_and_advanced_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_VM_NAME", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    describe_calls = iter(
        [
            {"status": "TERMINATED", "lastStartTimestamp": "old-ts"},
            {"status": "STAGING", "lastStartTimestamp": "old-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
        ]
    )
    started: list[bool] = []

    def _fake_start(project: str, zone: str, instance_name: str) -> None:
        assert project == "proj"
        assert zone == "zone"
        assert instance_name == "vm"
        started.append(True)

    monkeypatch.setattr(start_vm.gcloud_cli, "vm_start", _fake_start)
    monkeypatch.setattr(start_vm.gcloud_cli, "vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(start_vm.time, "sleep", lambda *_args, **_kwargs: None)

    result = runner.invoke(
        start_vm.command, ["--timeout-sec", "30", "--poll-interval-sec", "1", "--stabilization-sec", "0"]
    )
    assert result.exit_code == 0
    assert started == [True]
    assert "VM ready: status=RUNNING" in result.output


def test_start_vm_times_out_when_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_VM_NAME", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    monkeypatch.setattr(start_vm.gcloud_cli, "vm_start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        start_vm.gcloud_cli,
        "vm_describe",
        lambda *_args, **_kwargs: {"status": "STAGING", "lastStartTimestamp": "old-ts"},
    )
    monkeypatch.setattr(start_vm.time, "sleep", lambda *_args, **_kwargs: None)

    monotonic_values = iter([0.0, 0.5, 1.0, 1.6])
    monkeypatch.setattr(start_vm.time, "monotonic", lambda: next(monotonic_values))

    result = runner.invoke(
        start_vm.command, ["--timeout-sec", "1", "--poll-interval-sec", "1", "--stabilization-sec", "0"]
    )
    assert result.exit_code != 0
    assert "did not reach ready state" in result.output


def test_start_vm_continues_when_already_running_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_VM_NAME", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    def _raise_already_running(*_args, **_kwargs) -> None:
        raise start_vm.gcloud_cli.GcloudError("Failed to start VM vm: Instance is already running")

    describe_calls = iter(
        [
            {"status": "RUNNING", "lastStartTimestamp": "same-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "same-ts"},
        ]
    )
    monkeypatch.setattr(start_vm.gcloud_cli, "vm_start", _raise_already_running)
    monkeypatch.setattr(start_vm.gcloud_cli, "vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(start_vm.time, "sleep", lambda *_args, **_kwargs: None)

    result = runner.invoke(
        start_vm.command, ["--timeout-sec", "5", "--poll-interval-sec", "1", "--stabilization-sec", "0"]
    )
    assert result.exit_code == 0
    assert "already running" in result.output.lower()
    assert "VM ready: status=RUNNING" in result.output


def test_start_vm_allows_manual_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_VM_NAME", "vm")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("BMT_ALLOW_MANUAL_VM_START", raising=False)

    describe_calls = iter(
        [
            {"status": "TERMINATED", "lastStartTimestamp": "old-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
        ]
    )
    monkeypatch.setattr(start_vm.gcloud_cli, "vm_start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(start_vm.gcloud_cli, "vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(start_vm.time, "sleep", lambda *_args, **_kwargs: None)

    result = runner.invoke(
        start_vm.command,
        ["--allow-manual-start", "--timeout-sec", "5", "--poll-interval-sec", "1", "--stabilization-sec", "0"],
    )
    assert result.exit_code == 0
    assert "VM ready: status=RUNNING" in result.output


def test_start_vm_fails_when_status_drops_during_stabilization(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_VM_NAME", "vm")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    describe_calls = iter(
        [
            {"status": "TERMINATED", "lastStartTimestamp": "old-ts"},
            {"status": "RUNNING", "lastStartTimestamp": "new-ts"},
            {"status": "STOPPING", "lastStartTimestamp": "new-ts"},
        ]
    )
    monkeypatch.setattr(start_vm.gcloud_cli, "vm_start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(start_vm.gcloud_cli, "vm_describe", lambda *_args, **_kwargs: next(describe_calls))
    monkeypatch.setattr(start_vm.time, "sleep", lambda *_args, **_kwargs: None)

    monotonic_values = iter([0.0, 0.1, 0.2, 0.3, 0.4])
    monkeypatch.setattr(start_vm.time, "monotonic", lambda: next(monotonic_values))

    result = runner.invoke(
        start_vm.command, ["--timeout-sec", "10", "--poll-interval-sec", "1", "--stabilization-sec", "2"]
    )
    assert result.exit_code != 0
    assert "became unstable during stabilization window" in result.output
