"""Preset: stage release runner for BMT, compute preset info for GITHUB_OUTPUT."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from ci.actions import gh_notice


def _get_configure() -> str:
    cfg = (os.environ.get("MATRIX_CONFIGURE") or "").strip()
    if not cfg:
        raise RuntimeError("MATRIX_CONFIGURE is required")
    return cfg


def _load_presets(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise RuntimeError(f"Missing presets file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("CMakePresets.json must be a JSON object")
    presets = data.get("configurePresets")
    if not isinstance(presets, list):
        raise TypeError("CMakePresets.json must have configurePresets array")
    return [p for p in presets if isinstance(p, dict)]


def _binary_dir_for_configure(presets: list[dict[str, object]], configure: str) -> str:
    for p in presets:
        if str(p.get("name", "")) == configure:
            return str(p.get("binaryDir", "")).replace("${sourceDir}", ".").strip()
    raise RuntimeError(f"Configure preset not found: {configure}")


class PresetManager:
    @classmethod
    def from_env(cls) -> PresetManager:
        return cls()

    def stage_release_runner(self) -> None:
        cfg = _get_configure()
        if "_gcc_Release" not in cfg or "xtensa" in cfg.lower() or "hexagon" in cfg.lower():
            return
        presets_path = Path("CMakePresets.json")
        presets = _load_presets(presets_path)
        binary_dir = _binary_dir_for_configure(presets, cfg)
        project = cfg.replace("_gcc_Release", "").lower()
        runners_dir = Path(binary_dir) / "Runners"
        kardome_dir = Path(binary_dir) / "Kardome"
        runners_dir.mkdir(parents=True, exist_ok=True)
        kardome_dir.mkdir(parents=True, exist_ok=True)
        runner_bin = runners_dir / "kardome_runner"
        if runner_bin.is_file():
            print(f"Using existing runner from {runners_dir} (build/ layout)")
            return
        sk_runner = Path("gcp/remote/sk/runners/sk_gcc_release/kardome_runner")
        sk_lib = Path("gcp/remote/sk/runners/lib/libKardome.so")
        if sk_runner.is_file() and project == "sk":
            shutil.copy2(sk_runner, runner_bin)
            if sk_lib.is_file():
                shutil.copy2(sk_lib, kardome_dir / "libKardome.so")
            runner_bin.chmod(0o755)
            print("Using real runner from gcp/remote/sk/runners/ (production-like artifact)")
            return
        runner_bin.touch()
        (kardome_dir / "libKardome.so").touch()
        runner_bin.chmod(0o755)
        gh_notice(f"No real runner for {project}; creating placeholder for path-only test")

    def compute_preset_info(self) -> None:
        cfg = _get_configure()
        out = os.environ.get("GITHUB_OUTPUT")
        if not out:
            raise RuntimeError("GITHUB_OUTPUT is not set")
        presets = _load_presets(Path("CMakePresets.json"))
        binary_dir = _binary_dir_for_configure(presets, cfg)
        preset = cfg.lower()
        project = cfg.replace("_gcc_Release", "").lower()
        runners_dir = f"{binary_dir}/Runners"
        lib_dir = f"{binary_dir}/Kardome"
        with Path(out).open("a", encoding="utf-8") as f:
            f.write(
                f"preset={preset}\nproject={project}\nrunners_dir={runners_dir}\nlib_dir={lib_dir}\n"
            )
