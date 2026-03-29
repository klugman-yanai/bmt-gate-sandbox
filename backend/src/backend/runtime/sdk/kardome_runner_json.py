"""Future adapter: structured JSON from ``kardome_runner`` (see docs/contributors.md § Python plugin protocol).

Today the runtime uses :mod:`backend.runtime.legacy_kardome` and log regex parsing
(:mod:`backend.runtime.stdout_counter_parse`). When the native binary emits a
versioned JSON payload, implement the functions below and wire them from the plugin
or executor policy — do not parse free-form stdout for scores.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.runtime.sdk.results import ExecutionResult


def parse_kardome_runner_json_payload(payload: dict[str, Any]) -> ExecutionResult:
    """Map a single-runner JSON document to :class:`ExecutionResult`.

    Raises:
        NotImplementedError: until schema + runtime integration are shipped.
    """
    raise NotImplementedError(
        "Native kardome_runner JSON result parsing is not implemented yet; "
        "see docs/contributors.md (Python plugin protocol)."
    )


def parse_kardome_runner_json_file(path: Path) -> ExecutionResult:
    """Read JSON from ``path`` and map it to :class:`ExecutionResult` (not yet implemented)."""
    raise NotImplementedError(
        "Native kardome_runner JSON result parsing is not implemented yet; "
        "see docs/contributors.md (Python plugin protocol)."
    )
