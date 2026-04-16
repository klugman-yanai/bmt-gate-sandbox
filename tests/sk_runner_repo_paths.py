"""Canonical on-disk paths for the SK kardome benchmark (plugins mirror).

CI and ``repo validate-layout`` require these files; tests must exercise the real ELF
artifacts—not shell stubs or placeholder bytes—when validating runner staging, uploads,
and legacy execution wiring.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SK_KARDOME_RUNNER = REPO_ROOT / "plugins/projects/sk/kardome_runner"
SK_LIBKARDOME_SO = REPO_ROOT / "plugins/projects/sk/libKardome.so"
KARDOME_INPUT_TEMPLATE = REPO_ROOT / "runtime/assets/kardome_input_template.json"
