"""When to skip ``tools build orchestrator-image`` (git + Artifact Registry), shared by ship and workspace preflight."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.repo.paths import repo_root
from tools.shared.artifact_registry_uri import (
    artifact_registry_tag_status,
    resolve_bmt_orchestrator_image_base,
)

# Paths that invalidate the Cloud Run image (see gcp/image/Dockerfile COPY lines).
IMAGE_GIT_PATHSPECS: tuple[str, ...] = ("gcp/image", "gcp/__init__.py")


def _git_nonempty_lines(cmd: list[str], *, cwd: str) -> list[str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        return []
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def _git_merge_base_with_remote_head(root: str) -> str | None:
    for ref in ("origin/dev", "origin/main", "@{upstream}"):
        p = subprocess.run(
            ["git", "merge-base", "HEAD", ref],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if p.returncode == 0 and (sha := p.stdout.strip()):
            return sha
    return None


def _git_head_sha(root: str) -> str | None:
    p = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if p.returncode != 0:
        return None
    s = p.stdout.strip()
    return s if len(s) >= 7 else None


def image_context_git_dirty(root: str | None = None) -> bool:
    """True if git suggests the Docker context may have changed (rebuild may be needed)."""
    r = root or str(repo_root())
    specs = list(IMAGE_GIT_PATHSPECS)
    mb = _git_merge_base_with_remote_head(r)
    if mb is None:
        return True
    if _git_nonempty_lines(["git", "diff", "--name-only", f"{mb}...HEAD", "--", *specs], cwd=r):
        return True
    return bool(_git_nonempty_lines(["git", "diff", "--name-only", "HEAD", "--", *specs], cwd=r))


def evaluate_image_skip(
    *,
    root: str | None = None,
    skip_image: bool = False,
    force_image: bool = False,
    dry_run: bool = False,
) -> tuple[bool, str | None]:
    """Return (skip_image, optional Rich markup notice). Mirrors ``tools ship`` image auto-skip."""
    if force_image:
        return False, None
    if skip_image:
        return True, None

    root_s = root or str(repo_root())
    if image_context_git_dirty(root_s):
        return False, None

    if dry_run:
        head_preview = (_git_head_sha(root_s) or "?")[:7]
        return True, (
            "[dim]image auto-skipped (dry-run):[/] no git changes under [cyan]gcp/image[/] or [cyan]gcp/__init__.py[/].\n"
            "[dim]Artifact Registry is not queried in dry-run;[/] run without [cyan]--dry-run[/] to check "
            f"[cyan]bmt-orchestrator:{head_preview}[/] [dim]before skipping the image step.[/]"
        )

    head_sha = _git_head_sha(root_s)
    if not head_sha:
        return False, None

    image_base = resolve_bmt_orchestrator_image_base(Path(root_s))
    ar_status = artifact_registry_tag_status(image_base=image_base, tag=head_sha)
    if ar_status == "present":
        short = head_sha[:7]
        return True, (
            "[dim]image auto-skipped:[/] no git changes under [cyan]gcp/image[/] or [cyan]gcp/__init__.py[/]; "
            f"Artifact Registry has [cyan]bmt-orchestrator:{short}[/].\n"
            "[dim]Still wrong bits?[/] base-image-only updates or policy rebuilds — "
            "[dim]run[/] [cyan]tools ship --force-image[/] [dim]or[/] [cyan]just workspace preflight --with-image --force-image[/][dim].[/]"
        )
    if ar_status == "absent":
        return False, None
    if ar_status == "permission_denied":
        return False, (
            "[red]Artifact Registry:[/] permission denied reading tags (check IAM: "
            "[cyan]roles/artifactregistry.reader[/] on the project or repo). "
            "[dim]Running[/] [cyan]tools build orchestrator-image[/] [dim]anyway — not auto-skipping based on git alone.[/]"
        )
    return False, (
        "[yellow]Artifact Registry tag check unavailable[/] (invalid URI/HEAD, missing ADC, or transient API error). "
        "[dim]Running[/] [cyan]tools build orchestrator-image[/] [dim]so the pipeline is not silently skipped. "
        "Configure Application Default Credentials ([cyan]gcloud auth application-default login[/] "
        "or [cyan]GOOGLE_APPLICATION_CREDENTIALS[/]) for a definitive skip when the image already exists.[/]"
    )


def run_just_image() -> int:
    """Build and push the Cloud Run orchestrator image (``tools build orchestrator-image``); return exit code."""
    import shutil

    uv = shutil.which("uv")
    if not uv:
        return 127
    return subprocess.run(
        [uv, "run", "python", "-m", "tools", "build", "orchestrator-image"],
        cwd=repo_root(),
        check=False,
    ).returncode
