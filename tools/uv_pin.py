#!/usr/bin/env python3
"""Shared helpers for pinned uv artifact validation and download."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

SHA_LINE_RE = re.compile(r"^\s*([0-9a-fA-F]{64})\s+(?:\*?([^\s]+))?\s*$")
GLIBC_RE = re.compile(r"GLIBC_(\d+)\.(\d+)")
DEFAULT_UBUNTU_2204_GLIBC_MAX = (2, 35)


@dataclass(frozen=True)
class UvReleaseSpec:
    """Pinned uv release artifact metadata."""

    version: str
    artifact_url: str
    artifact_sha256: str
    binary_sha256: str
    binary_name: str = "uv"
    glibc_max: tuple[int, int] = DEFAULT_UBUNTU_2204_GLIBC_MAX


def parse_sha256_line(raw: str, *, require_filename: str | None = None) -> str:
    """Parse strict checksum line and return digest."""
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = SHA_LINE_RE.match(line)
        if not match:
            raise ValueError(f"Invalid SHA-256 line format: {line!r}")
        digest = match.group(1).lower()
        filename = (match.group(2) or "").strip()
        if require_filename and filename and filename != require_filename:
            raise ValueError(
                f"Checksum filename mismatch: expected {require_filename!r}, got {filename!r}"
            )
        return digest
    raise ValueError("No checksum line found")


def read_pinned_binary_sha(sha_file: Path, *, filename: str = "uv") -> str:
    """Read expected pinned binary digest from sha256 file."""
    if not sha_file.is_file():
        raise RuntimeError(f"Missing checksum file: {sha_file}")
    try:
        return parse_sha256_line(sha_file.read_text(encoding="utf-8"), require_filename=filename)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Invalid checksum file {sha_file}: {exc}") from exc


def _read_release_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"Missing uv release metadata file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid uv release metadata file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"uv release metadata must be a JSON object: {path}")
    return payload


def _parse_glibc_max(raw: object) -> tuple[int, int]:
    if raw is None:
        return DEFAULT_UBUNTU_2204_GLIBC_MAX
    text = str(raw).strip()
    match = re.fullmatch(r"(\d+)\.(\d+)", text)
    if not match:
        raise RuntimeError(f"Invalid glibc_max in uv release metadata: {raw!r}")
    return int(match.group(1)), int(match.group(2))


def read_release_spec(path: Path) -> UvReleaseSpec:
    """Load and validate uv release metadata."""
    payload = _read_release_json(path)
    version = str(payload.get("version", "")).strip()
    artifact_url = str(payload.get("artifact_url", "")).strip()
    artifact_sha256 = str(payload.get("artifact_sha256", "")).strip().lower()
    binary_sha256 = str(payload.get("binary_sha256", "")).strip().lower()
    binary_name = str(payload.get("binary_name", "uv")).strip() or "uv"
    glibc_max = _parse_glibc_max(payload.get("glibc_max"))

    if not version:
        raise RuntimeError(f"uv release metadata missing version: {path}")
    if not artifact_url.startswith("https://github.com/astral-sh/uv/releases/download/"):
        raise RuntimeError(
            f"uv artifact_url must point to astral-sh/uv releases: {artifact_url!r}"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256):
        raise RuntimeError(f"Invalid artifact_sha256 in {path}: {artifact_sha256!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", binary_sha256):
        raise RuntimeError(f"Invalid binary_sha256 in {path}: {binary_sha256!r}")
    return UvReleaseSpec(
        version=version,
        artifact_url=artifact_url,
        artifact_sha256=artifact_sha256,
        binary_sha256=binary_sha256,
        binary_name=binary_name,
        glibc_max=glibc_max,
    )


def sha256_file(path: Path) -> str:
    proc = subprocess.run(
        ["sha256sum", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sha256sum failed for {path}: {(proc.stderr or proc.stdout).strip()}")
    digest = (proc.stdout or "").split()[0].strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError(f"Unexpected sha256sum output for {path}: {proc.stdout!r}")
    return digest


def _extract_uv_from_tarball(tar_path: Path, output_dir: Path, binary_name: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, mode="r:gz") as archive:
        members = [m for m in archive.getmembers() if m.isfile() and Path(m.name).name == binary_name]
        if not members:
            raise RuntimeError(f"uv binary {binary_name!r} not found in archive {tar_path}")
        # Prefer shallowest path if tar contains multiple candidate files.
        members.sort(key=lambda m: len(Path(m.name).parts))
        member = members[0]
        out_path = output_dir / binary_name
        with archive.extractfile(member) as src, out_path.open("wb") as dst:  # type: ignore[arg-type]
            if src is None:
                raise RuntimeError(f"Could not read {member.name} from {tar_path}")
            shutil.copyfileobj(src, dst)
        out_path.chmod(0o755)
        return out_path


def _required_glibc_versions(binary_path: Path) -> list[tuple[int, int]]:
    versions: set[tuple[int, int]] = set()
    # Prefer readelf (less false positives), fallback to strings if unavailable.
    if shutil.which("readelf"):
        proc = subprocess.run(
            ["readelf", "-V", str(binary_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            for match in GLIBC_RE.finditer(proc.stdout or ""):
                versions.add((int(match.group(1)), int(match.group(2))))
    if not versions:
        proc = subprocess.run(
            ["strings", "-a", str(binary_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            for match in GLIBC_RE.finditer(proc.stdout or ""):
                versions.add((int(match.group(1)), int(match.group(2))))
    return sorted(versions)


def assert_ubuntu_2204_compatible(binary_path: Path, *, glibc_max: tuple[int, int]) -> None:
    """Fail when binary requires glibc newer than Ubuntu 22.04 baseline."""
    versions = _required_glibc_versions(binary_path)
    if not versions:
        raise RuntimeError(
            f"Unable to determine GLIBC requirements for {binary_path} (readelf/strings produced no matches)"
        )
    max_required = max(versions)
    if max_required > glibc_max:
        raise RuntimeError(
            "Pinned uv binary is not Ubuntu 22.04 compatible: "
            f"required GLIBC_{max_required[0]}.{max_required[1]} > "
            f"allowed GLIBC_{glibc_max[0]}.{glibc_max[1]}"
        )


def _download_file(url: str, destination: Path) -> None:
    proc = subprocess.run(
        ["curl", "-fsSL", url, "-o", str(destination)],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to download {url}: {(proc.stderr or proc.stdout).strip() or 'curl error'}"
        )


def fetch_pinned_uv_binary(spec: UvReleaseSpec, work_dir: Path) -> Path:
    """Download, verify, and extract the pinned uv binary into work_dir."""
    work_dir.mkdir(parents=True, exist_ok=True)
    tar_name = Path(spec.artifact_url).name
    tar_path = work_dir / tar_name
    _download_file(spec.artifact_url, tar_path)
    artifact_sha = sha256_file(tar_path)
    if artifact_sha != spec.artifact_sha256:
        raise RuntimeError(
            f"uv artifact sha mismatch: expected {spec.artifact_sha256}, got {artifact_sha}"
        )
    uv_bin = _extract_uv_from_tarball(tar_path, work_dir, spec.binary_name)
    binary_sha = sha256_file(uv_bin)
    if binary_sha != spec.binary_sha256:
        raise RuntimeError(
            f"uv binary sha mismatch: expected {spec.binary_sha256}, got {binary_sha}"
        )
    assert_ubuntu_2204_compatible(uv_bin, glibc_max=spec.glibc_max)
    proc = subprocess.run(
        [str(uv_bin), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"uv --version failed for pinned binary: {(proc.stderr or proc.stdout).strip()}")
    if spec.version not in (proc.stdout or ""):
        raise RuntimeError(
            f"Pinned uv version mismatch: expected {spec.version}, got {(proc.stdout or '').strip()!r}"
        )
    return uv_bin

