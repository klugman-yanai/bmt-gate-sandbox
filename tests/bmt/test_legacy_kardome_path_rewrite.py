"""Unit tests for ``_rewrite_json_paths_for_wav`` and its opt-out knob.

These tests pin down the contract the SK manifests now rely on:
``plugin_config.forced_wav_path_keys_exclude = ["REF_PATH"]`` must keep the template's
placeholder ``REF_PATH`` intact so the C-side ``tinywav_open_read`` fails with
``is_ref == -1`` and the refs channel guard short-circuits instead of refusing to run
every 8-channel WAV against a ``num_of_refs == 2`` buffer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from runtime.legacy_kardome import _rewrite_json_paths_for_wav

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SK_TEMPLATE_PATH = _REPO_ROOT / "runtime/assets/sk_kardome_input_template.json"
_SK_PLUGIN_SRC = str(_REPO_ROOT / "plugins/projects/sk")


def _import_sk_plugin():
    if _SK_PLUGIN_SRC not in sys.path:
        sys.path.insert(0, _SK_PLUGIN_SRC)
    import plugin as sk_plugin_mod

    return sk_plugin_mod


def _base_template() -> dict[str, object]:
    return {
        "MICS_PATH": "/tmp/dummy/mics.wav",
        "KARDOME_OUTPUT_PATH": "/tmp/dummy/kardome_output.wav",
        "USER_OUTPUT_PATH": "/tmp/dummy/user_output.wav",
        "REF_PATH": "/tmp/dummy/ref.wav",
        "QUIET_PATH": "/tmp/dummy/quiet.wav",
        "CALIB_BIN_PATH": "/tmp/dummy/calib.bin",
        "KWS_CONFIG": {
            "KWS_ENABLE": True,
            "CALIB_KWS_PATH": "/tmp/dummy/kws_calib/",
        },
    }


def test_default_rewrite_forces_ref_path_to_wav(tmp_path: Path) -> None:
    """Historical behavior: REF_PATH is forced to the current WAV path."""
    wav = tmp_path / "case.wav"
    wav.write_bytes(b"RIFF")
    cfg = _base_template()

    _rewrite_json_paths_for_wav(cfg, wav, tmp_path / "out.wav")

    assert cfg["MICS_PATH"] == str(wav.resolve())
    assert cfg["REF_PATH"] == str(wav.resolve())
    assert cfg["QUIET_PATH"] == str(wav.resolve())
    assert cfg["CALIB_BIN_PATH"] == str(wav.resolve())


def test_excluded_ref_path_keeps_template_placeholder(tmp_path: Path) -> None:
    """SK opt-out: REF_PATH stays at the template placeholder instead of being forced.

    This is exactly what makes ``tinywav_open_read`` on the placeholder fail, which in
    turn lets the C-side ``is_ref == -1`` branch skip the refs channel guard.
    """
    wav = tmp_path / "case.wav"
    wav.write_bytes(b"RIFF")
    cfg = _base_template()
    original_ref_path = cfg["REF_PATH"]

    _rewrite_json_paths_for_wav(
        cfg,
        wav,
        tmp_path / "out.wav",
        forced_key_excludes=frozenset({"REF_PATH"}),
    )

    assert cfg["MICS_PATH"] == str(wav.resolve()), "MICS_PATH must still be rewritten"
    assert cfg["REF_PATH"] == original_ref_path, (
        "REF_PATH must remain at the placeholder so is_ref == -1 short-circuits the refs guard"
    )
    assert cfg["QUIET_PATH"] == str(wav.resolve()), "Other forced keys are untouched by the exclusion"


def test_exclude_blocks_placeholder_walk_rewrite_too(tmp_path: Path) -> None:
    """The walk-based rewrite is gated on the same exclusion set, not just the forced loop."""
    wav = tmp_path / "case.wav"
    wav.write_bytes(b"RIFF")
    cfg = _base_template()
    cfg.pop("REF_PATH")
    cfg["NESTED"] = {"REF_PATH": "/tmp/dummy/placeholder_refs.wav"}

    _rewrite_json_paths_for_wav(
        cfg,
        wav,
        tmp_path / "out.wav",
        forced_key_excludes=frozenset({"REF_PATH"}),
    )

    nested = cfg["NESTED"]
    assert isinstance(nested, dict)
    assert nested["REF_PATH"] == "/tmp/dummy/placeholder_refs.wav", "Placeholder walk must also honor the excluded key"


def test_sk_template_ships_ref_path_placeholder() -> None:
    """The SK minimal template declares REF_PATH with a placeholder the runtime can detect.

    If this regresses (empty string, absent key, real path), the opt-out contract breaks and
    SK reverts to SIGABRT / refs-guard-refuse behavior depending on ``is_ref``'s outcome.
    """
    data = json.loads(_SK_TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert data.get("REF_PATH", "").startswith("/tmp/dummy/"), (
        "SK template must carry a /tmp/dummy/ placeholder REF_PATH; exclusion is meaningless otherwise"
    )


def test_sk_manifests_exclude_ref_path_from_forced_rewrite() -> None:
    """Both SK leg manifests must carry ``forced_wav_path_keys_exclude: ["REF_PATH"]``.

    This is the knob that pairs with the runner's refs-guard short-circuit — the only
    reason the runner reaches per-case kardome output instead of refusing to run on every
    8-channel mics WAV.
    """
    for leg in ("false_alarms", "false_rejects"):
        data = json.loads((_REPO_ROOT / "plugins/projects/sk" / f"{leg}.json").read_text(encoding="utf-8"))
        exclude = data["plugin_config"].get("forced_wav_path_keys_exclude")
        assert isinstance(exclude, list) and "REF_PATH" in exclude, (
            f"plugins/projects/sk/{leg}.json must list REF_PATH in forced_wav_path_keys_exclude"
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, frozenset()),
        ([], frozenset()),
        (["REF_PATH"], frozenset({"REF_PATH"})),
        (["ref_path", "QUIET_PATH"], frozenset({"REF_PATH", "QUIET_PATH"})),
        (("REF_PATH", "REF_PATH"), frozenset({"REF_PATH"})),
        # Non-sequence and non-string entries must be rejected defensively.
        ("REF_PATH", frozenset()),
        ([None, 42, "", "  ", "REF_PATH"], frozenset({"REF_PATH"})),
        (12345, frozenset()),
    ],
)
def test_coerce_forced_wav_path_keys_exclude(raw: object, expected: frozenset[str]) -> None:
    sk_plugin_mod = _import_sk_plugin()
    assert sk_plugin_mod._coerce_forced_wav_path_keys_exclude(raw) == expected
