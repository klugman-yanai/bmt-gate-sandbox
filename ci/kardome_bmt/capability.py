"""Platform capability discovery and caller-plan projection.

Two schemas, both versioned and Pydantic-validated:

* ``bmt.capability/v1`` — produced by ``bmt matrix capability``.
  Describes which projects the platform can test, emitted from
  ``plugins/projects/<key>/`` which is the authoritative source.

* ``bmt.plan/v1`` — produced by ``bmt matrix plan``.
  Projects a caller's ``CMakePresets.json`` onto the capability
  manifest and splits build presets into three buckets: ``publish``
  (BMT-runnable), ``acknowledged`` (host-release but no plugin on
  the platform), and ``nonrelease`` (everything else).

These replace the caller-side ``bmt/<KEY>/run-bmt.sh`` marker heuristic
with a platform-owned, schema-validated, version-pinned interface.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from whenever import Instant

CAPABILITY_API_VERSION = "bmt.capability/v1"
PLAN_API_VERSION = "bmt.plan/v1"

DEFAULT_ARTIFACTS_REQUIRED: tuple[str, ...] = ("kardome_runner", "libKardome.so")
HOST_RELEASE_SUFFIX = "_gcc_Release"


class ProjectCapability(BaseModel):
    """One row of the platform's supported-project list."""

    model_config = ConfigDict(extra="forbid")

    key: str
    schema_version: int = 1
    description: str | None = None
    host_preset_regex: str
    artifacts_required: list[str] = Field(default_factory=lambda: list(DEFAULT_ARTIFACTS_REQUIRED))
    runner_contract_sha256: str | None = None


class CapabilityManifest(BaseModel):
    """Platform-advertised list of BMT-runnable projects."""

    model_config = ConfigDict(extra="forbid")

    api_version: Literal["bmt.capability/v1"] = CAPABILITY_API_VERSION
    platform_release: str
    generated_at: str
    projects: list[ProjectCapability]


class PublishEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str
    project: str
    binary_dir: str | None = None
    artifacts_required: list[str]


class AcknowledgedEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str
    reason: str


class NonreleaseEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str
    reason: str


class Plan(BaseModel):
    """Build-matrix decision handed back to the caller."""

    model_config = ConfigDict(extra="forbid")

    api_version: Literal["bmt.plan/v1"] = PLAN_API_VERSION
    platform_release: str
    commit: str | None = None
    publish: list[PublishEntry]
    acknowledged: list[AcknowledgedEntry]
    nonrelease: list[NonreleaseEntry]


def _default_host_preset_regex(key: str) -> str:
    """Default regex: match ``<key>_gcc_Release`` with case-insensitive key.

    Plugin keys are canonical-lowercase (``sk``, ``e2e-test``); CMake preset
    names are CamelCase / UPPER (``SK_gcc_Release``). Case-insensitive on the
    key segment bridges that without requiring callers to hand-write regex.
    Projects can override via ``project.json``'s ``host_preset_regex`` field.
    """
    return f"^(?i:{re.escape(key)}){HOST_RELEASE_SUFFIX}$"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_project_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path}: expected JSON object")
    return data


def _coerce_artifacts_required(raw: Any, source: Path) -> list[str]:
    """Return ``raw`` as ``list[str]`` or raise ``TypeError`` with a context-rich message.

    Narrowing via comprehension + explicit per-element type check keeps the
    type assertion honest (every element must be ``str`` at runtime).
    """
    if raw is None:
        return list(DEFAULT_ARTIFACTS_REQUIRED)
    if not isinstance(raw, list):
        raise TypeError(f"{source}: artifacts_required must be list[str]")
    out: list[str] = []
    for element in raw:
        if not isinstance(element, str):
            raise TypeError(f"{source}: artifacts_required must be list[str]")
        out.append(element)
    return out


def _iter_project_dirs(plugins_root: Path) -> Iterable[Path]:
    if not plugins_root.is_dir():
        raise FileNotFoundError(f"Plugins root not found: {plugins_root}")
    for child in sorted(plugins_root.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        if child.name == "shared":
            continue
        if (child / "project.json").is_file():
            yield child


def build_capability_manifest(
    plugins_root: Path,
    platform_release: str,
    *,
    now_iso: str | None = None,
) -> CapabilityManifest:
    """Scan ``plugins_root`` and build a ``CapabilityManifest`` object.

    ``project.json`` supplies the project key (canonical, lowercase).
    Optional fields the platform will honor if present:

    * ``host_preset_regex`` — custom pattern (defaults to
      ``^<KEY><_gcc_Release>$``).
    * ``artifacts_required`` — list of filenames a caller must upload.

    ``runner_integration_contract.json``, if present, contributes
    a digest fingerprint.
    """
    generated_at = now_iso if now_iso is not None else Instant.now().format_iso(unit="second")
    projects: list[ProjectCapability] = []
    for project_dir in _iter_project_dirs(plugins_root):
        data = _load_project_json(project_dir / "project.json")
        key = str(data.get("project") or project_dir.name).strip()
        if not key:
            raise ValueError(f"{project_dir / 'project.json'}: empty project key")
        regex = str(data.get("host_preset_regex") or _default_host_preset_regex(key))
        artifacts_list: list[str] = _coerce_artifacts_required(
            data.get("artifacts_required"),
            project_dir / "project.json",
        )
        contract_path = project_dir / "runner_integration_contract.json"
        digest = _sha256_file(contract_path) if contract_path.is_file() else None
        projects.append(
            ProjectCapability(
                key=key,
                schema_version=int(data.get("schema_version", 1)),
                description=(str(data["description"]) if "description" in data else None),
                host_preset_regex=regex,
                artifacts_required=artifacts_list,
                runner_contract_sha256=digest,
            )
        )
    projects.sort(key=lambda p: p.key)
    return CapabilityManifest(
        platform_release=platform_release,
        generated_at=generated_at,
        projects=projects,
    )


def load_capability_manifest(path: Path) -> CapabilityManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CapabilityManifest.model_validate(payload)


def _extract_build_presets(presets_file: Path) -> list[dict[str, Any]]:
    """Return buildPresets if present, else synthesize from configurePresets.

    Callers often define only ``configurePresets`` (matrix.py's historical
    path); core-main's extract-presets iterates ``buildPresets``. Accept both
    so this function is drop-in for either style.
    """
    if not presets_file.is_file():
        raise FileNotFoundError(f"Missing presets file: {presets_file}")
    payload = json.loads(presets_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{presets_file}: expected JSON object")
    build_presets = payload.get("buildPresets")
    configure_presets = payload.get("configurePresets")
    if isinstance(build_presets, list) and build_presets:
        return [p for p in build_presets if isinstance(p, dict)]
    if isinstance(configure_presets, list):
        return [
            {"name": f"{p['name']}-build", "configurePreset": p["name"]}
            for p in configure_presets
            if isinstance(p, dict) and isinstance(p.get("name"), str)
        ]
    raise TypeError(f"{presets_file}: neither buildPresets nor configurePresets present")


def _configure_preset_map(presets_file: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(presets_file.read_text(encoding="utf-8"))
    by_name: dict[str, dict[str, Any]] = {}
    if isinstance(payload, dict):
        for preset in payload.get("configurePresets", []) or []:
            if isinstance(preset, dict) and isinstance(preset.get("name"), str):
                by_name[preset["name"]] = preset
    return by_name


def _preset_binary_dir(preset: dict[str, Any], configure_by_name: dict[str, dict[str, Any]]) -> str | None:
    binary_dir = preset.get("binaryDir")
    if not binary_dir:
        ref = preset.get("configurePreset")
        if isinstance(ref, str):
            binary_dir = configure_by_name.get(ref, {}).get("binaryDir")
    if not isinstance(binary_dir, str) or not binary_dir:
        return None
    return binary_dir.replace("${sourceDir}/", "", 1)


def _configure_name(preset: dict[str, Any]) -> str:
    name = preset.get("configurePreset") or preset.get("name") or ""
    if isinstance(name, str) and name.endswith("-build"):
        name = name[: -len("-build")]
    return str(name)


def _classify(
    configure_name: str,
    capability: CapabilityManifest,
) -> tuple[str, str | None]:
    """Return ``(bucket, project_key_or_reason)``.

    Buckets: ``publish``, ``acknowledged``, ``nonrelease``.
    """
    is_host_release = configure_name.endswith(HOST_RELEASE_SUFFIX)
    if not is_host_release:
        if configure_name.endswith("_gcc_Debug"):
            return ("nonrelease", "host_debug")
        return ("nonrelease", "cross_compile")
    for project in capability.projects:
        if re.match(project.host_preset_regex, configure_name):
            return ("publish", project.key)
    return ("acknowledged", "no_plugin_registered")


def build_plan(
    presets_file: Path,
    capability: CapabilityManifest,
    *,
    commit: str | None = None,
) -> Plan:
    """Project ``presets_file`` onto ``capability`` → a 3-bucket ``Plan``."""
    build_presets = _extract_build_presets(presets_file)
    configure_map = _configure_preset_map(presets_file)
    artifacts_by_project = {p.key: p.artifacts_required for p in capability.projects}

    publish: list[PublishEntry] = []
    acknowledged: list[AcknowledgedEntry] = []
    nonrelease: list[NonreleaseEntry] = []
    seen: set[str] = set()

    for preset in build_presets:
        build_name = str(preset.get("name", "")).strip()
        if not build_name or build_name in seen:
            continue
        seen.add(build_name)
        configure_name = _configure_name(preset)
        bucket, tag = _classify(configure_name, capability)
        binary_dir = _preset_binary_dir(preset, configure_map)
        if bucket == "publish":
            assert tag is not None
            publish.append(
                PublishEntry(
                    preset=configure_name,
                    project=tag,
                    binary_dir=binary_dir,
                    artifacts_required=list(artifacts_by_project.get(tag, DEFAULT_ARTIFACTS_REQUIRED)),
                )
            )
        elif bucket == "acknowledged":
            acknowledged.append(AcknowledgedEntry(preset=configure_name, reason=tag or "no_plugin_registered"))
        else:
            nonrelease.append(NonreleaseEntry(preset=configure_name, reason=tag or "cross_compile"))

    publish.sort(key=lambda e: (e.project, e.preset))
    acknowledged.sort(key=lambda e: e.preset)
    nonrelease.sort(key=lambda e: e.preset)

    return Plan(
        platform_release=capability.platform_release,
        commit=commit,
        publish=publish,
        acknowledged=acknowledged,
        nonrelease=nonrelease,
    )
