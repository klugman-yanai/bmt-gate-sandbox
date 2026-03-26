"""Tests for sync-vm-metadata command behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from bmt_gate.vm import VmManager


@pytest.fixture(autouse=True)
def _required_bmt_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_WIF_PROVIDER", "projects/1/locations/global/workloadIdentityPools/p/providers/p")
    monkeypatch.setenv("GCP_SA_EMAIL", "bmt@example.iam.gserviceaccount.com")


def test_sync_vm_metadata_sets_startup_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "train-kws-202311")
    monkeypatch.setenv("GCP_ZONE", "europe-west4-a")
    monkeypatch.setenv("BMT_LIVE_VM", "bmt-performance-gate")
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
        if metadata_files is not None and "startup-script" in metadata_files:
            script_path = metadata_files["startup-script"]
            captured["startup_script_path"] = script_path
            captured["startup_script_content"] = script_path.read_text(encoding="utf-8")

    describe_calls = {"count": 0}

    def _fake_describe(_project: str, _zone: str, _instance_name: str) -> dict[str, object]:
        describe_calls["count"] += 1
        if describe_calls["count"] == 1:
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
        return {
            "metadata": {
                "items": [
                    {"key": "GCS_BUCKET", "value": "train-kws-202311-bmt-gate"},
                    {"key": "BMT_REPO_ROOT", "value": "/opt/bmt"},
                    {"key": "startup-script", "value": captured.get("startup_script_content", "")},
                    {"key": "startup-script-url", "value": ""},
                ]
            }
        }

    monkeypatch.setattr("bmt_gate.vm.vm_add_metadata", _fake_add_metadata)
    monkeypatch.setattr("bmt_gate.vm.vm_describe", _fake_describe)

    VmManager.from_env().sync_metadata()

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
    script_path = captured["startup_script_path"]
    assert isinstance(script_path, Path)
    assert script_path.name == "startup_entrypoint.sh"
    script_content = captured["startup_script_content"]
    assert isinstance(script_content, str)
    assert script_content.startswith("#!/usr/bin/env bash")
    assert "BMT_REPO_ROOT" in script_content


def test_load_startup_entrypoint_script_from_packaged_resource() -> None:
    from importlib import resources as importlib_resources

    entrypoint = importlib_resources.files("bmt_gate.resources").joinpath("startup_entrypoint.sh")
    script_content = entrypoint.read_text(encoding="utf-8")
    assert script_content.startswith("#!/usr/bin/env bash")
    assert "_read_meta" in script_content


def test_sync_vm_metadata_does_not_require_bucket_code_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "train-kws-202311")
    monkeypatch.setenv("GCP_ZONE", "europe-west4-a")
    monkeypatch.setenv("BMT_LIVE_VM", "bmt-performance-gate")
    monkeypatch.setenv("GCS_BUCKET", "train-kws-202311-bmt-gate")

    def _forbid_gcs_exists(_uri: str) -> bool:
        raise AssertionError("sync-vm-metadata should not query code bucket objects")

    def _fake_describe(_project: str, _zone: str, _instance_name: str) -> dict[str, object]:
        return {
            "metadata": {
                "items": [
                    {"key": "GCS_BUCKET", "value": "train-kws-202311-bmt-gate"},
                    {"key": "BMT_REPO_ROOT", "value": "/opt/bmt"},
                    {"key": "startup-script", "value": "#!/bin/bash\necho stale\n"},
                    {"key": "startup-script-url", "value": ""},
                ]
            }
        }

    monkeypatch.setattr("bmt_gate.vm.vm_describe", _fake_describe)
    monkeypatch.setattr("bmt_gate.vm.vm_add_metadata", lambda *_args, **_kwargs: None)

    VmManager.from_env().sync_metadata()


def test_sync_vm_metadata_fails_when_legacy_prefix_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "train-kws-202311")
    monkeypatch.setenv("GCP_ZONE", "europe-west4-a")
    monkeypatch.setenv("BMT_LIVE_VM", "bmt-performance-gate")
    monkeypatch.setenv("GCS_BUCKET", "train-kws-202311-bmt-gate")

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

    monkeypatch.setattr("bmt_gate.vm.vm_describe", _fake_describe)

    with pytest.raises(RuntimeError, match="Legacy BMT_BUCKET_PREFIX"):
        VmManager.from_env().sync_metadata()
