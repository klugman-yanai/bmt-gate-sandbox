"""Guard: SK project native runner artifacts must exist in the repo working tree.

They are large binaries and may be easy to drop during layout refactors; layout policy
and this test catch absence before CI or deploy. Paths mirror BMT ``runner.uri`` /
deps (see ``plugins/projects/sk/*.json``).
"""

from __future__ import annotations

import pytest

from tests.sk_runner_repo_paths import SK_KARDOME_RUNNER, SK_LIBKARDOME_SO

# Non-trivial size avoids an empty placeholder committed by mistake (real ELF >> this).
_MIN_BYTES = 512


@pytest.mark.unit
def test_sk_kardome_runner_and_lib_present_and_nonempty() -> None:
    assert SK_KARDOME_RUNNER.is_file(), f"Missing SK runner binary: {SK_KARDOME_RUNNER}"
    assert SK_LIBKARDOME_SO.is_file(), f"Missing libKardome.so: {SK_LIBKARDOME_SO}"
    assert SK_KARDOME_RUNNER.stat().st_size >= _MIN_BYTES, f"Suspiciously small kardome_runner: {SK_KARDOME_RUNNER}"
    assert SK_LIBKARDOME_SO.stat().st_size >= _MIN_BYTES, f"Suspiciously small libKardome.so: {SK_LIBKARDOME_SO}"
