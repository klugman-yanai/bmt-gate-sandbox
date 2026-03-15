"""On-image and bucket path constants for gcp/image scripts and VM runtime.

Single source of truth for paths used by image code and scripts. tools/repo/paths.py
remains the source for repo layout (DEFAULT_CONFIG_ROOT = gcp/image); this module
describes what lives inside that mirror and on the VM. Repo root default comes from
gcp.image.config.bmt_config (single source of truth for BMT defaults).
"""

from __future__ import annotations

from pathlib import Path

from gcp.image.config.bmt_config import DEFAULT_REPO_ROOT

# ---------------------------------------------------------------------------
# On-image paths (VM filesystem)
# ---------------------------------------------------------------------------
# Re-export so callers can use DEFAULT_BMT_REPO_ROOT; canonical name is DEFAULT_REPO_ROOT in bmt_config.
DEFAULT_BMT_REPO_ROOT: str = DEFAULT_REPO_ROOT
IMAGE_SCRIPTS_SUBDIR: str = "scripts"
VM_WATCHER_SCRIPT: str = "vm_watcher.py"

# ---------------------------------------------------------------------------
# Bucket layout (GCS: bucket root only; no code/ or runtime/ prefix)
# ---------------------------------------------------------------------------
# Code is not in GCS; it is baked into the image via Packer (from gcp/image).
# All bucket paths are under bucket root (e.g. gs://bucket/triggers/, gs://bucket/sk/).
BUCKET_ROOT_PREFIX: str = ""

# Paths under image/repo (for local/VM layout only; not GCS paths).
SCRIPTS_STARTUP_ENTRYPOINT: str = "scripts/startup_entrypoint.sh"
SCRIPTS_RUN_WATCHER: str = "scripts/run_watcher.py"
SCRIPTS_VALIDATE_BUCKET_CONTRACT: str = "scripts/validate_bucket_contract.py"
SCRIPTS_INSTALL_DEPS: str = "scripts/install_deps.py"


def repo_scripts_path(repo_root: str | Path) -> Path:
    """Path to scripts directory under repo root."""
    return Path(repo_root) / IMAGE_SCRIPTS_SUBDIR


def repo_watcher_path(repo_root: str | Path) -> Path:
    """Path to vm_watcher.py under repo root."""
    return Path(repo_root) / VM_WATCHER_SCRIPT
