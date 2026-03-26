"""Dataset manifest model and registry for BMT input datasets.

Provides:
  DatasetEntry      — one file entry (path, size, sha256, updated).
  DatasetManifest   — full manifest for one dataset.
  InputFileRegistry — manifest-aware WAV enumeration; replaces rglob("*.wav").

Manifest lives at:
  gcp/stage/projects/<project>/inputs/<dataset>/dataset_manifest.json

It is tracked in git so any git clone gives the full directory tree shape
without the actual audio files. Real WAVs are fetched on demand via
``just fetch-inputs <project> <dataset>`` or mounted read-only via
``just mount-data <project>``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def _str_from_json_value(v: object, default: str = "") -> str:
    """String form for JSON object values (manifest file entries are untyped JSON)."""
    if v is None:
        return default
    return str(v)


def _entry_from_json_object(raw: dict[str, object]) -> DatasetEntry:
    """Parse one ``files[]`` object from ``dataset_manifest.json``."""
    return DatasetEntry(
        name=_str_from_json_value(raw.get("name")),
        size_bytes=int(_str_from_json_value(raw.get("size_bytes"), "0")),
        sha256=_str_from_json_value(raw.get("sha256")),
        updated=_str_from_json_value(raw.get("updated")),
    )


@dataclass(frozen=True)
class DatasetEntry:
    """One file within a dataset."""

    name: str  # relative path from dataset root, e.g. "ambient/cafe_001.wav"
    size_bytes: int
    sha256: str
    updated: str  # ISO-8601 timestamp from GCS object metadata


@dataclass(frozen=True)
class DatasetManifest:
    """Manifest for one dataset prefix in GCS."""

    schema_version: int
    project: str
    dataset: str
    bucket: str
    prefix: str  # GCS prefix, e.g. "projects/sk/inputs/false_rejects"
    generated_at: str  # ISO-8601 timestamp
    files: tuple[DatasetEntry, ...]

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> DatasetManifest:
        """Deserialise from a parsed JSON dict."""
        raw_files = data.get("files", [])
        if not isinstance(raw_files, list):
            raise ValueError("manifest 'files' must be a list")
        entries_list: list[DatasetEntry] = []
        for raw in raw_files:
            if not isinstance(raw, dict):
                continue
            file_obj: dict[str, object] = {str(k): v for k, v in raw.items()}
            entries_list.append(_entry_from_json_object(file_obj))
        entries = tuple(entries_list)
        return cls(
            schema_version=int(str(data.get("schema_version", 1))),
            project=str(data.get("project", "")),
            dataset=str(data.get("dataset", "")),
            bucket=str(data.get("bucket", "")),
            prefix=str(data.get("prefix", "")),
            generated_at=str(data.get("generated_at", "")),
            files=entries,
        )

    @classmethod
    def load(cls, path: Path) -> DatasetManifest:
        """Load and parse manifest from a local file path."""
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"dataset_manifest.json at {path} is not a JSON object")
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "dataset": self.dataset,
            "bucket": self.bucket,
            "prefix": self.prefix,
            "generated_at": self.generated_at,
            "files": [
                {"name": e.name, "size_bytes": e.size_bytes, "sha256": e.sha256, "updated": e.updated}
                for e in self.files
            ],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")


_MANIFEST_FILENAME = "dataset_manifest.json"


class InputFileRegistry:
    """Manifest-aware WAV file enumerator for a dataset root.

    No tool should call ``rglob("*.wav")`` directly on a dataset root;
    they must go through ``InputFileRegistry`` so that manifest-only
    (no local WAVs) workflows and FUSE-mounted datasets are handled uniformly.

    Usage::

        registry = InputFileRegistry(dataset_root)
        wavs = registry.list_wavs(require_materialized=True)  # raises if not present
        names = registry.list_wav_names()  # manifest-only; offline
    """

    def __init__(self, dataset_root: Path) -> None:
        self._root = dataset_root

    @property
    def manifest_path(self) -> Path:
        return self._root / _MANIFEST_FILENAME

    def manifest(self) -> DatasetManifest | None:
        """Load manifest if present; return None if absent."""
        if not self.manifest_path.is_file():
            return None
        try:
            return DatasetManifest.load(self.manifest_path)
        except Exception:
            return None

    def list_wavs(self, require_materialized: bool = False) -> list[Path]:
        """Return local WAV Paths.

        If local ``*.wav`` files exist under the dataset root, return them.
        Otherwise, read the manifest and return virtual Path objects (correct
        names, may not exist on disk).

        Args:
            require_materialized: If True and no local WAV files exist,
                raise FileNotFoundError pointing at ``just fetch-inputs``.
        """
        local_wavs = sorted(self._root.rglob("*.wav"))
        if local_wavs:
            return local_wavs

        m = self.manifest()
        if m is not None:
            if require_materialized:
                raise FileNotFoundError(
                    f"No WAV files found under {self._root}. "
                    f"Run 'just fetch-inputs {m.project} {m.dataset}' to materialise the dataset locally."
                )
            return [self._root / entry.name for entry in m.files]

        if require_materialized:
            raise FileNotFoundError(
                f"No WAV files and no {_MANIFEST_FILENAME} found under {self._root}. "
                "Run 'just fetch-inputs <project> <dataset>' to materialise the dataset."
            )
        return []

    def list_wav_names(self) -> list[str]:
        """Return WAV file names from manifest (offline; does not check disk).

        Useful for tooling that only needs the file list, not materialized files.
        Falls back to scanning local files if no manifest is present.
        """
        m = self.manifest()
        if m is not None:
            return [e.name for e in m.files]
        return [str(p.relative_to(self._root)) for p in sorted(self._root.rglob("*.wav"))]
