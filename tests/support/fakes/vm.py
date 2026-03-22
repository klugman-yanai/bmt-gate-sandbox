from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict


class VmDescribeStatus(TypedDict, total=False):
    """Subset of fields returned by ``gcloud compute instances describe``-style backends."""

    status: str


@dataclass(frozen=True, slots=True)
class VmMetadataCallRecord:
    metadata: dict[str, str]
    metadata_files: dict[str, Path]


@dataclass
class FakeVmBackend:
    """Deterministic VM backend with explicit status progression."""

    statuses: list[VmDescribeStatus] = field(default_factory=list)
    start_calls: int = 0
    metadata_calls: list[VmMetadataCallRecord] = field(default_factory=list)

    def vm_start(self, *_args: object, **_kwargs: object) -> None:
        self.start_calls += 1

    def vm_describe(self, *_args: object, **_kwargs: object) -> VmDescribeStatus:
        if self.statuses:
            return self.statuses.pop(0)
        return {"status": "RUNNING"}

    def vm_add_metadata(
        self,
        _project: str,
        _zone: str,
        _instance_name: str,
        metadata: dict[str, str],
        *,
        metadata_files: dict[str, Path] | None = None,
    ) -> None:
        self.metadata_calls.append(VmMetadataCallRecord(metadata=metadata, metadata_files=metadata_files or {}))
