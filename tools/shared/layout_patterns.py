"""Centralized exclude/forbidden/bloat pattern constants for bucket sync, verify, clean, and layout policy.

Used by sync_gcp, sync_runtime_seed, verify_gcp_sync,
verify_runtime_seed_sync, clean_bloat, and gcp_layout_policy.
"""

from __future__ import annotations

# Layout policy: allowed top-level entries under backend/ (formerly gcp/)
ALLOWED_TOP_LEVEL = {"README.md", "config", "github", "projects", "scripts", "schemas", "__init__.py",
                     "path_utils.py", "root_orchestrator.py", "utils.py", "vm_watcher.py", "pyproject.toml", "uv.lock"}

# Code namespace: exclude from sync/verify and forbid in layout (backend/).
DEFAULT_CODE_EXCLUDES = (
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
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/inputs(/|$)",
    r"(^|/)sk/outputs(/|$)",
    r"(^|/)sk/results(/|$)",
)

# Runtime seed: exclude from sync/verify when allow_generated_artifacts=False.
# Same list for sync and verify so digest matches.
FORBIDDEN_RUNTIME_SEED = (
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
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/results(/|$)",
    r"(^|/)sk/outputs(/|$)",
)

# Bloat-only (clean_bloat runtime); do not include triggers/sk paths under runtime.
BLOAT_PATTERNS = (
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

# Code namespace clean = bloat + errant triggers/sk paths.
CODE_CLEAN_PATTERNS = (
    *BLOAT_PATTERNS,
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/inputs(/|$)",
    r"(^|/)sk/outputs(/|$)",
    r"(^|/)sk/results(/|$)",
)

# Layout policy: forbid these in backend/ (same as code excludes).
FORBIDDEN_CODE_PATTERNS = DEFAULT_CODE_EXCLUDES

# Layout policy: forbid these in benchmarks/ (includes .wav under inputs).
FORBIDDEN_RUNTIME_PATTERNS = (
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/results(/|$)",
    r"(^|/)sk/outputs(/|$)",
    r"(^|/)inputs(/|$).*\.wav$",
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
