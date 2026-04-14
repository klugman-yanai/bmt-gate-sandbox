"""Bucket preflight: list GCS state via google-cloud-storage and diff vs gcp/image.

Live runs persist a JSON snapshot under ``.local/``; replay uses the same JSON only.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson
from google.cloud import storage

from gcp.image.config.constants import ENV_GCS_BUCKET
from tools.repo.core_main_workflows import run_drift_check
from tools.repo.paths import DEFAULT_CONFIG_ROOT, repo_root
from tools.shared.bucket_env import get_bucket_from_env
from tools.shared.bucket_sync import matches
from tools.shared.gcs_sync import prefix_stats
from tools.shared.layout_patterns import DEFAULT_CODE_EXCLUDES

PREFLIGHT_SNAPSHOT_SCHEMA_VERSION = 1


def _utc_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _utc_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def gcp_image_files(root: Path) -> set[str]:
    """Return relative paths under gcp/image that are not excluded by code sync."""
    image_root = root / DEFAULT_CONFIG_ROOT
    if not image_root.is_dir():
        return set()
    out: set[str] = set()
    for p in image_root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(image_root).as_posix()
        if matches(DEFAULT_CODE_EXCLUDES, rel):
            continue
        out.add(rel)
    return out


def fetch_code_rel_paths(client: storage.Client, bucket_name: str) -> set[str]:
    """List all object paths under code/ as paths relative to the code/ prefix."""
    prefix = "code/"
    out: set[str] = set()
    for blob in client.list_blobs(bucket_name, prefix=prefix):
        if blob.name.endswith("/"):
            continue
        rel = blob.name.removeprefix(prefix).strip("/")
        if rel:
            out.add(rel)
    return out


def _gs_uri(bucket_name: str, object_path: str) -> str:
    path = object_path.removeprefix("/")
    return f"gs://{bucket_name}/{path}"


def _top_level_listing_lines(client: storage.Client, bucket_name: str) -> list[str]:
    """Immediate children of bucket root (blobs + prefix folders), as gs:// lines."""
    lines: list[str] = []
    iterator = client.list_blobs(bucket_name, delimiter="/")
    for blob in iterator:
        name = blob.name
        if name and not name.endswith("/"):
            lines.append(_gs_uri(bucket_name, name))
    prefs = getattr(iterator, "prefixes", None) or ()
    for prefix in sorted(prefs):
        lines.append(_gs_uri(bucket_name, prefix))
    return sorted(lines)


@dataclass(frozen=True, slots=True)
class PreflightSnapshot:
    """Structured result of a bucket listing (persisted as JSON)."""

    schema_version: int
    bucket: str
    generated_at: str
    code_rel_paths: frozenset[str]
    stats_code: dict[str, int]
    stats_runtime: dict[str, int]
    top_level_uris: tuple[str, ...]

    def to_json_bytes(self) -> bytes:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "bucket": self.bucket,
            "generated_at": self.generated_at,
            "code_rel_paths": sorted(self.code_rel_paths),
            "stats": {
                "code": self.stats_code,
                "runtime": self.stats_runtime,
            },
            "top_level_uris": list(self.top_level_uris),
        }
        return orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)

    @staticmethod
    def from_json_bytes(data: bytes) -> PreflightSnapshot:
        raw = orjson.loads(data)
        if not isinstance(raw, dict):
            raise ValueError("snapshot must be a JSON object")
        ver = raw.get("schema_version")
        if ver != PREFLIGHT_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {ver!r} (expected {PREFLIGHT_SNAPSHOT_SCHEMA_VERSION})")
        bucket = raw.get("bucket")
        if not isinstance(bucket, str) or not bucket:
            raise ValueError("snapshot missing string bucket")
        generated_at = raw.get("generated_at")
        if not isinstance(generated_at, str):
            raise ValueError("snapshot missing generated_at")
        paths = raw.get("code_rel_paths")
        if not isinstance(paths, list):
            raise ValueError("snapshot code_rel_paths must be a list of strings")
        str_paths: list[str] = []
        for p in paths:
            if not isinstance(p, str):
                raise ValueError("snapshot code_rel_paths must be a list of strings")
            str_paths.append(p)
        stats_raw = raw.get("stats")
        stats: dict[str, Any] = stats_raw if isinstance(stats_raw, dict) else {}
        code_s_raw = stats.get("code")
        code_s: dict[str, Any] = code_s_raw if isinstance(code_s_raw, dict) else {}
        rt_s_raw = stats.get("runtime")
        rt_s: dict[str, Any] = rt_s_raw if isinstance(rt_s_raw, dict) else {}
        top = raw.get("top_level_uris")
        if top is not None and not isinstance(top, list):
            raise ValueError("top_level_uris must be a list or null")
        top_t = tuple(top) if isinstance(top, list) else ()
        return PreflightSnapshot(
            schema_version=int(ver),
            bucket=bucket,
            generated_at=generated_at,
            code_rel_paths=frozenset(str_paths),
            stats_code=dict(code_s),
            stats_runtime=dict(rt_s),
            top_level_uris=tuple(top_t) if all(isinstance(x, str) for x in top_t) else (),
        )


def build_snapshot(client: storage.Client, bucket_name: str) -> PreflightSnapshot:
    """Collect full listing metadata for persistence and diff."""
    code_paths = fetch_code_rel_paths(client, bucket_name)
    code_stats = prefix_stats(client=client, bucket_name=bucket_name, prefix="code")
    runtime_stats = prefix_stats(client=client, bucket_name=bucket_name, prefix="runtime")
    top = tuple(_top_level_listing_lines(client, bucket_name))
    return PreflightSnapshot(
        schema_version=PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
        bucket=bucket_name,
        generated_at=_utc_iso(),
        code_rel_paths=frozenset(code_paths),
        stats_code={"file_count": code_stats.file_count, "total_bytes": code_stats.total_bytes},
        stats_runtime={"file_count": runtime_stats.file_count, "total_bytes": runtime_stats.total_bytes},
        top_level_uris=top,
    )


def write_preflight_snapshot(client: storage.Client, bucket_name: str, root: Path) -> Path:
    """Write ``.local/preflight-bucket-<stamp>.json`` and return the path."""
    local_dir = root / ".local"
    local_dir.mkdir(parents=True, exist_ok=True)
    out = local_dir / f"preflight-bucket-{_utc_compact()}.json"
    snap = build_snapshot(client, bucket_name)
    out.write_bytes(snap.to_json_bytes())
    print(f"Snapshot saved to {out}")
    print(
        f"bucket={snap.bucket} code_objects={snap.stats_code.get('file_count', 0)} "
        f"code_bytes={snap.stats_code.get('total_bytes', 0)} "
        f"runtime_objects={snap.stats_runtime.get('file_count', 0)}"
    )
    return out


def load_code_paths_from_snapshot(path: Path) -> set[str]:
    """Load ``code_rel_paths`` from a JSON snapshot file."""
    snap = PreflightSnapshot.from_json_bytes(path.read_bytes())
    return set(snap.code_rel_paths)


def print_diff(
    *,
    bucket_label: str,
    image_paths: set[str],
    bucket_paths: set[str],
) -> None:
    """Print bucket vs gcp/image diff (Rich when available)."""
    print(f"gcp/image files (excludes sync-excluded): {len(image_paths)}")
    print(f"Bucket gs://{bucket_label}/code/ objects: {len(bucket_paths)}")
    in_bucket_not_image = sorted(bucket_paths - image_paths)
    in_image_not_bucket = sorted(image_paths - bucket_paths)

    if sys.stdout.isatty():
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table

            console = Console()
            if in_bucket_not_image:
                t = Table(
                    title="In bucket code/ but NOT in gcp/image (would be dropped)",
                    show_header=True,
                    header_style="yellow",
                )
                t.add_column("Path", style="dim")
                for p in in_bucket_not_image[:100]:
                    t.add_row(p)
                if len(in_bucket_not_image) > 100:
                    t.add_row(f"... and {len(in_bucket_not_image) - 100} more", style="dim")
                console.print(t)
            else:
                console.print(
                    Panel(
                        "All bucket code/ paths have a counterpart in gcp/image.",
                        title="Bucket vs image",
                        border_style="green",
                    )
                )
            if in_image_not_bucket:
                t2 = Table(
                    title="In gcp/image but NOT in bucket (ok if never synced)",
                    show_header=True,
                    header_style="blue",
                )
                t2.add_column("Path", style="dim")
                for p in in_image_not_bucket[:100]:
                    t2.add_row(p)
                if len(in_image_not_bucket) > 100:
                    t2.add_row(f"... and {len(in_image_not_bucket) - 100} more", style="dim")
                console.print(t2)
        except ImportError:
            _print_diff_plain(in_bucket_not_image, in_image_not_bucket)
    else:
        _print_diff_plain(in_bucket_not_image, in_image_not_bucket)


def _print_diff_plain(in_bucket_not_image: list[str], in_image_not_bucket: list[str]) -> None:
    if in_bucket_not_image:
        print("\nIn bucket code/ but NOT in gcp/image (would be dropped when code leaves bucket):")
        for p in in_bucket_not_image[:50]:
            print(f"  {p}")
        if len(in_bucket_not_image) > 50:
            print(f"  ... and {len(in_bucket_not_image) - 50} more")
    else:
        print("\nAll bucket code/ paths have a counterpart in gcp/image.")
    if in_image_not_bucket:
        print("\nIn gcp/image but NOT in bucket (ok if never synced or excluded):")
        for p in in_image_not_bucket[:50]:
            print(f"  {p}")
        if len(in_image_not_bucket) > 50:
            print(f"  ... and {len(in_image_not_bucket) - 50} more")


def run_preflight(
    *,
    snapshot: Path | None,
    local_only: bool,
    storage_client: storage.Client | None = None,
) -> int:
    """Run preflight diff; live runs write JSON under ``.local/``."""
    root = repo_root()
    image_paths = gcp_image_files(root)
    if local_only:
        print(f"gcp/image files (excludes sync-excluded): {len(image_paths)}")
        for p in sorted(image_paths):
            print(p)
        return 0

    if snapshot is not None:
        if not snapshot.is_file():
            print(f"::error::Snapshot not found: {snapshot}", file=sys.stderr)
            return 1
        if snapshot.suffix.lower() != ".json":
            print(
                "::error::Replay path must be a .json snapshot (from a live preflight run).",
                file=sys.stderr,
            )
            return 1
        try:
            bucket_paths = load_code_paths_from_snapshot(snapshot)
        except (OSError, ValueError) as exc:
            print(f"::error::Invalid snapshot {snapshot}: {exc}", file=sys.stderr)
            return 1
        label = "snapshot"
        print_diff(bucket_label=label, image_paths=image_paths, bucket_paths=bucket_paths)
        return 0

    bucket = (os.environ.get(ENV_GCS_BUCKET) or "").strip() or get_bucket_from_env()
    if not bucket:
        print(f"::error::Set {ENV_GCS_BUCKET} (e.g. export {ENV_GCS_BUCKET}=…)", file=sys.stderr)
        return 1

    client = storage_client or storage.Client()
    write_preflight_snapshot(client, bucket, root)
    bucket_paths = fetch_code_rel_paths(client, bucket)
    print_diff(bucket_label=bucket, image_paths=image_paths, bucket_paths=bucket_paths)
    rc = run_drift_check(root / ".github" / "workflows", mode="preflight")
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-flight: diff bucket code/ vs gcp/image")
    parser.add_argument(
        "-s",
        "--snapshot",
        "--report",
        type=Path,
        dest="snapshot",
        metavar="PATH",
        help="Replay diff from a saved JSON snapshot (.local/preflight-bucket-*.json).",
    )
    parser.add_argument("--local-only", action="store_true", help="Only list gcp/image, no GCS")
    args = parser.parse_args(argv)
    return run_preflight(snapshot=args.snapshot, local_only=args.local_only)


if __name__ == "__main__":
    raise SystemExit(main())
