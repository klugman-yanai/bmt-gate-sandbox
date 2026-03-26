"""Single entry for ``tools add``: scaffold project, optional BMT, optional dataset upload."""

from __future__ import annotations

import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, cast

from tools.bmt.scaffold import add_bmt as add_bmt_impl, add_project as add_project_impl
from tools.remote.bucket_upload_dataset import BucketUploadDataset
from tools.repo.paths import DEFAULT_STAGE_ROOT, repo_root
from tools.shared.bucket_env import bucket_from_env


def _project_tree_nonempty(project_root: Path) -> bool:
    return project_root.is_dir() and any(project_root.iterdir())


@contextmanager
def prepared_dataset_source(path: Path) -> Iterator[Path]:
    """Yield a path to a directory or .zip file suitable for ``BucketUploadDataset``.

    Supports directories, ``.zip`` (passed through), and tar formats (``tar``, ``.tar.gz``, ``.tgz``).
    Other archives (e.g. ``.7z``) are rejected with a clear message.
    """
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_dir():
        yield path
        return

    lower = path.name.lower()
    if lower.endswith(".7z"):
        raise ValueError(
            "7z archives are not supported here; extract to a folder or zip, then pass that path to --data."
        )

    if path.suffix.lower() == ".zip" or lower.endswith(".zip"):
        if not zipfile.is_zipfile(path):
            raise ValueError(f"Not a valid zip file: {path}")
        yield path
        return

    tar_modes: dict[str, str] = {
        ".tar.gz": "r:gz",
        ".tgz": "r:gz",
        ".tar.bz2": "r:bz2",
        ".tbz2": "r:bz2",
        ".tar": "r:",
    }
    mode: str | None = None
    for suf, m in tar_modes.items():
        if lower.endswith(suf):
            mode = m
            break
    if mode is None:
        raise ValueError(f"Unsupported archive type: {path.name}. Use a directory, .zip, .tar, .tar.gz, or .tgz.")

    tar_mode = cast(Literal["r:", "r:gz", "r:bz2"], mode)
    with tempfile.TemporaryDirectory(prefix="bmt-add-data-") as tmpdir:
        with tarfile.open(path, tar_mode) as tf:
            tf.extractall(tmpdir, filter="data")
        yield Path(tmpdir)


def run_contributor_add(
    *,
    project: str,
    bmt: str | None,
    data: Path | None,
    dataset: str | None,
    upload_local_mirror: bool,
    upload_force: bool,
    dry_run: bool,
) -> int:
    """Run scaffold and/or upload. Returns process exit code."""
    stage_root = repo_root() / DEFAULT_STAGE_ROOT
    project_root = stage_root / "projects" / project

    if dry_run and (bmt is not None or data is not None):
        if not _project_tree_nonempty(project_root):
            print(f"Would create project {project!r}", file=sys.stderr)
        if bmt is not None:
            print(f"Would add BMT {bmt!r} under {project!r}", file=sys.stderr)
        if data is not None:
            print(f"Would upload dataset from {data}", file=sys.stderr)
        return 0

    if bmt is None and data is None:
        if _project_tree_nonempty(project_root):
            print(
                f"Project {project!r} already exists. Use --bmt and/or --data to add more.",
                file=sys.stderr,
            )
            return 1
        try:
            return add_project_impl(project, dry_run=dry_run)
        except FileExistsError as e:
            print(str(e), file=sys.stderr)
            return 1

    if not _project_tree_nonempty(project_root):
        try:
            rc = add_project_impl(project, dry_run=False)
            if rc != 0:
                return rc
        except FileExistsError:
            pass

    if bmt is not None:
        try:
            add_bmt_impl(project, bmt)
        except FileExistsError:
            print(f"BMT {bmt!r} already exists under {project!r}, skipping scaffold.", file=sys.stderr)

    if data is not None:
        bucket = bucket_from_env()
        dataset_name = dataset if dataset is not None else bmt
        local_mirror = repo_root() / "gcp" / "stage" if upload_local_mirror else None
        try:
            with prepared_dataset_source(data) as source:
                return BucketUploadDataset().run(
                    bucket=bucket,
                    project=project,
                    source=source,
                    dataset_name=dataset_name,
                    force=upload_force,
                    local_mirror=local_mirror,
                )
        except (OSError, ValueError) as e:
            print(str(e), file=sys.stderr)
            return 1

    return 0
