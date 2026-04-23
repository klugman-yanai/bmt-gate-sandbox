"""Canonical on-disk paths for the SK kardome benchmark (plugins mirror).

CI and ``repo validate-layout`` require these files; tests must exercise the real ELF
artifacts—not shell stubs or placeholder bytes—when validating runner staging, uploads,
and legacy execution wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

SK_KARDOME_RUNNER = REPO_ROOT / "plugins/projects/sk/kardome_runner"
SK_LIBKARDOME_SO = REPO_ROOT / "plugins/projects/sk/libKardome.so"
# Must match ``plugins/projects/sk/*.json`` ``runner.template_path`` (SK false_alarms / rejects).
KARDOME_INPUT_TEMPLATE = REPO_ROOT / "runtime/assets/sk_kardome_input_template.json"


# libKardome.so is gitignored globally (**/*.so) so a fresh CI checkout lacks
# it; the runner binary is also optional in minimal environments. Tests that
# exercise real ELF staging must skip when either artifact is missing rather
# than fail with FileNotFoundError — local `just test` still enforces presence
# (developer working trees have the files), and CI gates in release.yml now
# run pytest over a clean checkout where these are not available.
requires_sk_binaries = pytest.mark.skipif(
    not (SK_KARDOME_RUNNER.is_file() and SK_LIBKARDOME_SO.is_file()),
    reason="SK runner binaries absent (produced by core-main's SK_gcc_Release build; "
    "plugins/projects/sk/libKardome.so is gitignored).",
)
