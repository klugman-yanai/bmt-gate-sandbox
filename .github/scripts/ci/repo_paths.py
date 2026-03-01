"""Re-export repo path constants from devtools for CI commands.

Adds repo root to sys.path so devtools.repo_paths is importable when running
from .github/scripts.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root: this file is .github/scripts/ci/repo_paths.py
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from devtools.repo_paths import (  # noqa: E402
    DEFAULT_CONFIG_ROOT,
    DEFAULT_ENV_CONTRACT_PATH,
    DEFAULT_REPO_VARS_PATH,
    DEFAULT_RUNTIME_ROOT,
)

__all__ = [
    "DEFAULT_CONFIG_ROOT",
    "DEFAULT_ENV_CONTRACT_PATH",
    "DEFAULT_REPO_VARS_PATH",
    "DEFAULT_RUNTIME_ROOT",
]
