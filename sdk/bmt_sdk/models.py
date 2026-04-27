"""Read-only manifest slices (runtime builds these; plugins only read)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ExecutionConfigView:
    policy: str = "adaptive_batch_then_legacy"
    profile: str = "standard"


@dataclass(frozen=True, slots=True)
class RunnerConfigView:
    uri: str = ""
    deps_prefix: str = ""
    template_path: str = "runtime/assets/kardome_input_template.json"


@dataclass(frozen=True, slots=True)
class ProjectManifestView:
    project: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class BmtManifestView:
    project: str
    bmt_slug: str
    bmt_id: str
    enabled: bool
    plugin_config: dict[str, Any]
    inputs_prefix: str = ""
    results_prefix: str = ""
    outputs_prefix: str = ""
    execution: ExecutionConfigView = field(default_factory=ExecutionConfigView)
    runner: RunnerConfigView = field(default_factory=RunnerConfigView)
