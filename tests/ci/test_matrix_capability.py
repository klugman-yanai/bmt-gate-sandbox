"""Unit tests for ``bmt matrix capability`` and the underlying builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ci.kardome_bmt.capability import (
    CAPABILITY_API_VERSION,
    DEFAULT_ARTIFACTS_REQUIRED,
    CapabilityManifest,
    build_capability_manifest,
)
from ci.kardome_bmt.driver import app

runner = CliRunner()


def _write_project(root: Path, key: str, extras: dict | None = None) -> Path:
    project_dir = root / key
    project_dir.mkdir(parents=True)
    data: dict = {"schema_version": 1, "project": key, "description": f"{key} project"}
    if extras:
        data.update(extras)
    (project_dir / "project.json").write_text(json.dumps(data), encoding="utf-8")
    return project_dir


def test_capability_manifest_shape(tmp_path: Path) -> None:
    root = tmp_path / "plugins" / "projects"
    _write_project(root, "sk")
    _write_project(root, "e2e-test")

    manifest = build_capability_manifest(root, platform_release="bmt-v0.3.2")

    assert manifest.api_version == CAPABILITY_API_VERSION
    assert manifest.platform_release == "bmt-v0.3.2"
    assert [p.key for p in manifest.projects] == ["e2e-test", "sk"]
    for project in manifest.projects:
        assert list(project.artifacts_required) == list(DEFAULT_ARTIFACTS_REQUIRED)
        assert project.runner_contract_sha256 is None


def test_default_host_preset_regex_uses_key_case_insensitive(tmp_path: Path) -> None:
    """Keys are canonical-lowercase but presets are CamelCase; default matches both."""
    import re as _re

    root = tmp_path / "plugins" / "projects"
    _write_project(root, "sk")

    manifest = build_capability_manifest(root, platform_release="dev")

    regex = manifest.projects[0].host_preset_regex
    assert _re.match(regex, "SK_gcc_Release")
    assert _re.match(regex, "sk_gcc_Release")
    assert not _re.match(regex, "SK_gcc_Debug")
    assert not _re.match(regex, "LGVS_W_gcc_Release")


def test_project_json_overrides_regex_and_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "plugins" / "projects"
    _write_project(
        root,
        "sk",
        extras={
            "host_preset_regex": r"^SK_gcc_Release$",
            "artifacts_required": ["kardome_runner"],
        },
    )

    manifest = build_capability_manifest(root, platform_release="dev")

    assert manifest.projects[0].host_preset_regex == r"^SK_gcc_Release$"
    assert manifest.projects[0].artifacts_required == ["kardome_runner"]


def test_runner_contract_digest_when_present(tmp_path: Path) -> None:
    root = tmp_path / "plugins" / "projects"
    project = _write_project(root, "sk")
    contract = project / "runner_integration_contract.json"
    contract.write_text('{"schema_version": 1}\n', encoding="utf-8")

    manifest = build_capability_manifest(root, platform_release="dev")

    assert manifest.projects[0].runner_contract_sha256 is not None
    assert len(manifest.projects[0].runner_contract_sha256) == 64


def test_shared_and_hidden_dirs_excluded(tmp_path: Path) -> None:
    root = tmp_path / "plugins" / "projects"
    _write_project(root, "sk")
    (root / "shared").mkdir()
    (root / "shared" / "project.json").write_text('{"project": "shared"}', encoding="utf-8")
    (root / "_private").mkdir()
    (root / "_private" / "project.json").write_text('{"project": "_private"}', encoding="utf-8")

    manifest = build_capability_manifest(root, platform_release="dev")

    assert [p.key for p in manifest.projects] == ["sk"]


def test_missing_plugins_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_capability_manifest(tmp_path / "nope", platform_release="dev")


def test_cli_emits_valid_json_to_stdout(tmp_path: Path) -> None:
    root = tmp_path / "plugins" / "projects"
    _write_project(root, "sk")

    result = runner.invoke(
        app,
        ["matrix", "capability", "--plugins-root", str(root), "--platform-release", "bmt-v0.3.2"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    manifest = CapabilityManifest.model_validate(payload)
    assert manifest.platform_release == "bmt-v0.3.2"
    assert manifest.projects[0].key == "sk"


def test_cli_writes_out_file(tmp_path: Path) -> None:
    root = tmp_path / "plugins" / "projects"
    _write_project(root, "sk")
    out_path = tmp_path / "capability.json"

    result = runner.invoke(
        app,
        [
            "matrix",
            "capability",
            "--plugins-root",
            str(root),
            "--platform-release",
            "bmt-v0.3.2",
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert out_path.is_file()
    manifest = CapabilityManifest.model_validate_json(out_path.read_text(encoding="utf-8"))
    assert manifest.projects[0].key == "sk"


def test_cli_writes_github_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "plugins" / "projects"
    _write_project(root, "sk")
    gh_out = tmp_path / "gh_output"
    gh_out.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))

    result = runner.invoke(
        app,
        [
            "matrix",
            "capability",
            "--plugins-root",
            str(root),
            "--platform-release",
            "bmt-v0.3.2",
            "--github-output-key",
            "capability",
        ],
    )
    assert result.exit_code == 0, result.stdout
    content = gh_out.read_text(encoding="utf-8")
    assert content.startswith("capability=")
    CapabilityManifest.model_validate_json(content.split("=", 1)[1].strip())
