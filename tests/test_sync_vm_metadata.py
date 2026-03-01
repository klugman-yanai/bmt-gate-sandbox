"""Tests for sync-vm-metadata command behavior."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from ci.commands import sync_vm_metadata


def test_sync_vm_metadata_sets_startup_script(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "train-kws-202311")
    monkeypatch.setenv("GCP_ZONE", "europe-west4-a")
    monkeypatch.setenv("BMT_VM_NAME", "bmt-performance-gate")
    monkeypatch.setenv("GCS_BUCKET", "train-kws-202311-bmt-gate")
    monkeypatch.setenv("BMT_REPO_ROOT", "/opt/bmt")

    captured: dict[str, object] = {}

    def _fake_add_metadata(
        project: str,
        zone: str,
        instance_name: str,
        metadata: dict[str, str],
        *,
        metadata_files: dict[str, Path] | None = None,
    ) -> None:
        captured["project"] = project
        captured["zone"] = zone
        captured["instance_name"] = instance_name
        captured["metadata"] = metadata
        captured["metadata_files"] = metadata_files

    def _fake_exists(_uri: str) -> bool:
        return True

    def _fake_describe(_project: str, _zone: str, _instance_name: str) -> dict[str, object]:
        return {
            "metadata": {
                "items": [
                    {"key": "GCS_BUCKET", "value": "train-kws-202311-bmt-gate"},
                    {"key": "BMT_REPO_ROOT", "value": "/opt/bmt"},
                    {"key": "startup-script", "value": "#!/bin/bash\necho hi\n"},
                    {"key": "startup-script-url", "value": ""},
                ]
            }
        }

    monkeypatch.setattr(sync_vm_metadata.gcloud_cli, "gcs_exists", _fake_exists)
    monkeypatch.setattr(sync_vm_metadata.gcloud_cli, "vm_add_metadata", _fake_add_metadata)
    monkeypatch.setattr(sync_vm_metadata.gcloud_cli, "vm_describe", _fake_describe)

    result = runner.invoke(sync_vm_metadata.command, [])
    assert result.exit_code == 0

    assert captured["project"] == "train-kws-202311"
    assert captured["zone"] == "europe-west4-a"
    assert captured["instance_name"] == "bmt-performance-gate"

    metadata = captured["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["GCS_BUCKET"] == "train-kws-202311-bmt-gate"
    assert metadata["BMT_REPO_ROOT"] == "/opt/bmt"
    assert metadata["startup-script-url"] == ""

    metadata_files = captured["metadata_files"]
    assert isinstance(metadata_files, dict)
    assert "startup-script" in metadata_files
    script_path = metadata_files["startup-script"]
    assert isinstance(script_path, Path)
    assert script_path.name == "startup_wrapper.sh"
    assert script_path.is_file()


def test_sync_vm_metadata_fails_when_required_code_object_missing(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "train-kws-202311")
    monkeypatch.setenv("GCP_ZONE", "europe-west4-a")
    monkeypatch.setenv("BMT_VM_NAME", "bmt-performance-gate")
    monkeypatch.setenv("GCS_BUCKET", "train-kws-202311-bmt-gate")

    def _fake_exists(uri: str) -> bool:
        return not uri.endswith("/bootstrap/startup_example.sh")

    monkeypatch.setattr(sync_vm_metadata.gcloud_cli, "gcs_exists", _fake_exists)

    result = runner.invoke(sync_vm_metadata.command, [])
    assert result.exit_code != 0
    assert "Missing required code objects in bucket namespace" in result.output


def test_sync_vm_metadata_fails_when_uv_artifact_missing(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "train-kws-202311")
    monkeypatch.setenv("GCP_ZONE", "europe-west4-a")
    monkeypatch.setenv("BMT_VM_NAME", "bmt-performance-gate")
    monkeypatch.setenv("GCS_BUCKET", "train-kws-202311-bmt-gate")

    def _fake_exists(uri: str) -> bool:
        return not uri.endswith("/_tools/uv/linux-x86_64/uv")

    monkeypatch.setattr(sync_vm_metadata.gcloud_cli, "gcs_exists", _fake_exists)

    result = runner.invoke(sync_vm_metadata.command, [])
    assert result.exit_code != 0
    assert "Missing required code objects in bucket namespace" in result.output
    assert "_tools/uv/linux-x86_64/uv" in result.output


def test_sync_vm_metadata_fails_when_runtime_pyproject_missing(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "train-kws-202311")
    monkeypatch.setenv("GCP_ZONE", "europe-west4-a")
    monkeypatch.setenv("BMT_VM_NAME", "bmt-performance-gate")
    monkeypatch.setenv("GCS_BUCKET", "train-kws-202311-bmt-gate")

    def _fake_exists(uri: str) -> bool:
        return not uri.endswith("/pyproject.toml")

    monkeypatch.setattr(sync_vm_metadata.gcloud_cli, "gcs_exists", _fake_exists)

    result = runner.invoke(sync_vm_metadata.command, [])
    assert result.exit_code != 0
    assert "Missing required code objects in bucket namespace" in result.output
    assert "/pyproject.toml" in result.output


def test_sync_vm_metadata_fails_when_legacy_prefix_exists(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("GCP_PROJECT", "train-kws-202311")
    monkeypatch.setenv("GCP_ZONE", "europe-west4-a")
    monkeypatch.setenv("BMT_VM_NAME", "bmt-performance-gate")
    monkeypatch.setenv("GCS_BUCKET", "train-kws-202311-bmt-gate")

    def _fake_exists(_uri: str) -> bool:
        return True

    def _fake_describe(_project: str, _zone: str, _instance_name: str) -> dict[str, object]:
        return {
            "metadata": {
                "items": [
                    {"key": "GCS_BUCKET", "value": "train-kws-202311-bmt-gate"},
                    {"key": "BMT_BUCKET_PREFIX", "value": "team/env"},
                    {"key": "BMT_REPO_ROOT", "value": "/opt/bmt"},
                    {"key": "startup-script", "value": "#!/bin/bash\necho hi\n"},
                    {"key": "startup-script-url", "value": ""},
                ]
            }
        }

    monkeypatch.setattr(sync_vm_metadata.gcloud_cli, "gcs_exists", _fake_exists)
    monkeypatch.setattr(sync_vm_metadata.gcloud_cli, "vm_describe", _fake_describe)

    result = runner.invoke(sync_vm_metadata.command, [])
    assert result.exit_code != 0
    assert "Legacy BMT_BUCKET_PREFIX" in result.output
