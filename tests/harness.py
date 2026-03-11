from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FakeGcsStore:
    """Deterministic in-memory GCS-like object store used by contract tests."""

    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)

    def exists(self, uri: str) -> bool:
        return uri in self.objects

    def download_json(self, uri: str) -> tuple[dict[str, Any] | None, str | None]:
        payload = self.objects.get(uri)
        if payload is None:
            return None, f"404 {uri}"
        return payload, None

    def upload_json(self, uri: str, payload: dict[str, Any]) -> None:
        self.objects[uri] = payload

    def delete(self, uri: str) -> None:
        self.deleted.append(uri)
        self.objects.pop(uri, None)

    def list_prefix(self, prefix: str) -> list[str]:
        return sorted(uri for uri in self.objects if uri.startswith(prefix))


@dataclass
class FakeVmBackend:
    """Deterministic VM backend with explicit status progression."""

    statuses: list[dict[str, Any]] = field(default_factory=list)
    start_calls: int = 0
    metadata_calls: list[dict[str, Any]] = field(default_factory=list)

    def vm_start(self, *_args: object, **_kwargs: object) -> None:
        self.start_calls += 1

    def vm_describe(self, *_args: object, **_kwargs: object) -> dict[str, Any]:
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
        self.metadata_calls.append(
            {
                "metadata": metadata,
                "metadata_files": metadata_files or {},
            }
        )


@dataclass
class FakeGithubBackend:
    """Minimal deterministic GitHub status/check/comment backend for contract tests."""

    statuses: list[dict[str, str]] = field(default_factory=list)
    comments: list[dict[str, str | int]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    def post_status(self, repository: str, sha: str, state: str, context: str) -> None:
        self.statuses.append(
            {"repository": repository, "sha": sha, "state": state, "context": context}
        )
