from __future__ import annotations

from dataclasses import dataclass, field

type JSONValue = str | int | float | bool | None | dict[str, "JSONValue"] | list["JSONValue"]
type JSONDict = dict[str, JSONValue]


@dataclass
class FakeGcsStore:
    """Deterministic in-memory GCS-like object store used by contract tests."""

    objects: dict[str, JSONDict] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)

    def exists(self, uri: str) -> bool:
        return uri in self.objects

    def download_json(self, uri: str) -> tuple[JSONDict | None, str | None]:
        payload = self.objects.get(uri)
        if payload is None:
            return None, f"404 {uri}"
        return payload, None

    def upload_json(self, uri: str, payload: JSONDict) -> None:
        self.objects[uri] = payload

    def delete(self, uri: str) -> None:
        self.deleted.append(uri)
        self.objects.pop(uri, None)

    def list_prefix(self, prefix: str) -> list[str]:
        return sorted(uri for uri in self.objects if uri.startswith(prefix))
