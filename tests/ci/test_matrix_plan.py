"""Unit tests for ``bmt matrix plan`` (CMake presets → 3-bucket plan)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ci.kardome_bmt.capability import (
    PLAN_API_VERSION,
    CapabilityManifest,
    Plan,
    build_capability_manifest,
    build_plan,
)
from ci.kardome_bmt.driver import app

runner = CliRunner()


def _write_project(root: Path, key: str, extras: dict | None = None) -> None:
    project_dir = root / key
    project_dir.mkdir(parents=True)
    data: dict = {"schema_version": 1, "project": key}
    if extras:
        data.update(extras)
    (project_dir / "project.json").write_text(json.dumps(data), encoding="utf-8")


def _write_presets(path: Path, configure: list[dict], build: list[dict] | None = None) -> None:
    payload: dict = {"version": 6, "configurePresets": configure}
    if build is not None:
        payload["buildPresets"] = build
    path.write_text(json.dumps(payload), encoding="utf-8")


def _capability_for(
    keys: list[str], tmp_path: Path, regex_overrides: dict[str, str] | None = None
) -> CapabilityManifest:
    root = tmp_path / "plugins" / "projects"
    for key in keys:
        extras = None
        if regex_overrides and key in regex_overrides:
            extras = {"host_preset_regex": regex_overrides[key]}
        _write_project(root, key, extras=extras)
    return build_capability_manifest(root, platform_release="bmt-v0.3.2")


def test_publish_bucket_when_plugin_exists(tmp_path: Path) -> None:
    capability = _capability_for(["sk"], tmp_path)
    presets = tmp_path / "CMakePresets.json"
    _write_presets(
        presets,
        configure=[{"name": "SK_gcc_Release", "binaryDir": "${sourceDir}/build/SK_gcc_Release"}],
        build=[{"name": "SK_gcc_Release-build", "configurePreset": "SK_gcc_Release"}],
    )

    plan = build_plan(presets, capability, commit="abc123")

    assert plan.api_version == PLAN_API_VERSION
    assert plan.platform_release == "bmt-v0.3.2"
    assert plan.commit == "abc123"
    assert [e.preset for e in plan.publish] == ["SK_gcc_Release"]
    assert plan.publish[0].project == "sk"
    assert plan.publish[0].binary_dir == "build/SK_gcc_Release"
    assert plan.acknowledged == []


def test_release_without_plugin_goes_to_acknowledged(tmp_path: Path) -> None:
    capability = _capability_for(["sk"], tmp_path, regex_overrides={"sk": r"^SK_gcc_Release$"})
    presets = tmp_path / "CMakePresets.json"
    _write_presets(
        presets,
        configure=[
            {"name": "SK_gcc_Release"},
            {"name": "LGVS_W_gcc_Release"},
            {"name": "HMTC_gcc_Release"},
        ],
        build=[
            {"name": "SK_gcc_Release-build", "configurePreset": "SK_gcc_Release"},
            {"name": "LGVS_W_gcc_Release-build", "configurePreset": "LGVS_W_gcc_Release"},
            {"name": "HMTC_gcc_Release-build", "configurePreset": "HMTC_gcc_Release"},
        ],
    )

    plan = build_plan(presets, capability)

    assert [e.preset for e in plan.publish] == ["SK_gcc_Release"]
    assert [e.preset for e in plan.acknowledged] == ["HMTC_gcc_Release", "LGVS_W_gcc_Release"]
    assert all(e.reason == "no_plugin_registered" for e in plan.acknowledged)


def test_nonrelease_split(tmp_path: Path) -> None:
    capability = _capability_for(["sk"], tmp_path, regex_overrides={"sk": r"^SK_gcc_Release$"})
    presets = tmp_path / "CMakePresets.json"
    _write_presets(
        presets,
        configure=[
            {"name": "SK_gcc_Release"},
            {"name": "SK_gcc_Debug"},
            {"name": "SK_android_Release"},
            {"name": "LGVS_W_xtensa_Release"},
        ],
        build=[
            {"name": "SK_gcc_Release-build", "configurePreset": "SK_gcc_Release"},
            {"name": "SK_gcc_Debug-build", "configurePreset": "SK_gcc_Debug"},
            {"name": "SK_android_Release-build", "configurePreset": "SK_android_Release"},
            {"name": "LGVS_W_xtensa_Release-build", "configurePreset": "LGVS_W_xtensa_Release"},
        ],
    )

    plan = build_plan(presets, capability)

    assert [e.preset for e in plan.publish] == ["SK_gcc_Release"]
    nonrelease_by_preset = {e.preset: e.reason for e in plan.nonrelease}
    assert nonrelease_by_preset["SK_gcc_Debug"] == "host_debug"
    assert nonrelease_by_preset["SK_android_Release"] == "cross_compile"
    assert nonrelease_by_preset["LGVS_W_xtensa_Release"] == "cross_compile"


def test_plan_without_build_presets_synthesizes_from_configure(tmp_path: Path) -> None:
    capability = _capability_for(["sk"], tmp_path, regex_overrides={"sk": r"^SK_gcc_Release$"})
    presets = tmp_path / "CMakePresets.json"
    _write_presets(presets, configure=[{"name": "SK_gcc_Release"}])

    plan = build_plan(presets, capability)

    assert [e.preset for e in plan.publish] == ["SK_gcc_Release"]


def test_artifacts_required_carries_from_capability(tmp_path: Path) -> None:
    root = tmp_path / "plugins" / "projects"
    _write_project(
        root,
        "sk",
        extras={
            "host_preset_regex": r"^SK_gcc_Release$",
            "artifacts_required": ["kardome_runner"],
        },
    )
    capability = build_capability_manifest(root, platform_release="dev")
    presets = tmp_path / "CMakePresets.json"
    _write_presets(presets, configure=[{"name": "SK_gcc_Release"}])

    plan = build_plan(presets, capability)

    assert plan.publish[0].artifacts_required == ["kardome_runner"]


def test_cli_plan_reads_capability_file(tmp_path: Path) -> None:
    capability = _capability_for(["sk"], tmp_path, regex_overrides={"sk": r"^SK_gcc_Release$"})
    capability_path = tmp_path / "capability.json"
    capability_path.write_text(capability.model_dump_json(), encoding="utf-8")
    presets = tmp_path / "CMakePresets.json"
    _write_presets(presets, configure=[{"name": "SK_gcc_Release"}])

    result = runner.invoke(
        app,
        [
            "matrix",
            "plan",
            "--presets",
            str(presets),
            "--capability",
            str(capability_path),
            "--commit",
            "deadbeef",
        ],
    )

    assert result.exit_code == 0, result.stdout
    plan = Plan.model_validate_json(result.stdout.strip())
    assert plan.commit == "deadbeef"
    assert plan.publish[0].project == "sk"


def test_cli_plan_scans_plugins_root_when_capability_omitted(tmp_path: Path) -> None:
    root = tmp_path / "plugins" / "projects"
    _write_project(root, "sk", extras={"host_preset_regex": r"^SK_gcc_Release$"})
    presets = tmp_path / "CMakePresets.json"
    _write_presets(presets, configure=[{"name": "SK_gcc_Release"}])

    result = runner.invoke(
        app,
        [
            "matrix",
            "plan",
            "--presets",
            str(presets),
            "--plugins-root",
            str(root),
            "--platform-release",
            "bmt-v0.3.2",
        ],
    )
    assert result.exit_code == 0, result.stdout
    plan = Plan.model_validate_json(result.stdout.strip())
    assert plan.platform_release == "bmt-v0.3.2"


def test_cli_plan_writes_github_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability_for(["sk"], tmp_path, regex_overrides={"sk": r"^SK_gcc_Release$"})
    capability_path = tmp_path / "capability.json"
    capability_path.write_text(capability.model_dump_json(), encoding="utf-8")
    presets = tmp_path / "CMakePresets.json"
    _write_presets(presets, configure=[{"name": "SK_gcc_Release"}])
    gh_out = tmp_path / "gh_output"
    gh_out.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))

    result = runner.invoke(
        app,
        [
            "matrix",
            "plan",
            "--presets",
            str(presets),
            "--capability",
            str(capability_path),
            "--github-output-key",
            "plan",
        ],
    )

    assert result.exit_code == 0, result.stdout
    content = gh_out.read_text(encoding="utf-8")
    assert content.startswith("plan=")
    Plan.model_validate_json(content.split("=", 1)[1].strip())
