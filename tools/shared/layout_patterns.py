"""Centralized exclude/forbidden/bloat pattern constants for bucket sync, verify, clean, and layout policy.

Used by sync_gcp, sync_runtime_seed, verify_gcp_sync,
verify_runtime_seed_sync, clean_bloat, and gcp_layout_policy.
"""

from __future__ import annotations

# Layout policy: allowed top-level entries under gcp/
ALLOWED_TOP_LEVEL = {"README.md", "image", "stage", "local", "__init__.py"}

# Shared: bytecode, virtualenvs, tool caches, packaging metadata (used by multiple policy tuples).
_ARTIFACT_EXCLUDES: tuple[str, ...] = (
    r"(^|/)__pycache__(/|$)",
    r"__pycache__",
    r"\.pyc$",
    r"\.pyo$",
    r"(^|/)\.venv(/|$)",
    r"(^|/)venv(/|$)",
    r"(^|/)\.uv(/|$)",
    r"(^|/)\.mypy_cache(/|$)",
    r"(^|/)\.pytest_cache(/|$)",
    r"(^|/)\.ruff_cache(/|$)",
    r"(^|/)\.tox(/|$)",
    r"(^|/)\.eggs(/|$)",
    r"(^|/)[^/]+\.egg-info(/|$)",
    r"\.egg$",
)

# Code namespace: exclude from sync/verify and forbid in layout (gcp/image).
DEFAULT_CODE_EXCLUDES: tuple[str, ...] = (
    *_ARTIFACT_EXCLUDES,
    r"(^|/)triggers(/|$)",
    r"(^|/)projects/[^/]+/inputs(/|$)",
    r"(^|/)projects/[^/]+/outputs(/|$)",
    r"(^|/)projects/[^/]+/results(/|$)",
)

# Runtime seed: exclude from sync/verify when allow_generated_artifacts=False.
# Same list for sync and verify so digest matches.
# NOTE: inputs/ is NOT excluded here because .keep and dataset_manifest.json need to be
# synced to GCS. Data files (WAVs etc.) are excluded via _is_inputs_data_path() in bucket_sync.py.
FORBIDDEN_RUNTIME_SEED: tuple[str, ...] = (
    *_ARTIFACT_EXCLUDES,
    r"(^|/)triggers(/|$)",
    r"(^|/)projects/[^/]+/results(/|$)",
    r"(^|/)projects/[^/]+/outputs(/|$)",
)

# Bloat-only (clean_bloat runtime); do not include triggers/project paths under runtime.
BLOAT_PATTERNS: tuple[str, ...] = _ARTIFACT_EXCLUDES

# Code namespace clean = bloat + errant triggers/project paths.
CODE_CLEAN_PATTERNS = (
    *BLOAT_PATTERNS,
    r"(^|/)triggers(/|$)",
    r"(^|/)projects/[^/]+/inputs(/|$)",
    r"(^|/)projects/[^/]+/outputs(/|$)",
    r"(^|/)projects/[^/]+/results(/|$)",
)

# Layout policy: forbid these in gcp/image (same as code excludes).
FORBIDDEN_CODE_PATTERNS = DEFAULT_CODE_EXCLUDES

# Layout policy: forbid these in gcp/stage (includes .wav under inputs).
FORBIDDEN_RUNTIME_PATTERNS: tuple[str, ...] = (
    r"(^|/)triggers(/|$)",
    r"(^|/)projects/[^/]+/results(/|$)",
    r"(^|/)projects/[^/]+/outputs(/|$)",
    r"(^|/)projects/[^/]+/inputs/.*\.wav$",
    *_ARTIFACT_EXCLUDES,
)
