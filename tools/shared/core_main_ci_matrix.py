"""Re-exports for layout tests and tooling; canonical logic is ``kardome_bmt.matrix_core_main``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kardome_bmt.matrix_core_main import classify_build_presets, iter_all_matrix_entries, load_presets_file

__all__ = ("classify_build_presets", "iter_all_matrix_entries", "load_presets")


def load_presets(core_main_root: Path) -> dict[str, Any]:
    return load_presets_file(Path(core_main_root) / "CMakePresets.json")
