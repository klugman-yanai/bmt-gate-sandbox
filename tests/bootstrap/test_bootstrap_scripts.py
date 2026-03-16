"""Deterministic validation for bootstrap shell scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from tools.repo.paths import GITHUB_BMT_ROOT, IMAGE_SCRIPTS, repo_root


def _vm_path(rel: str) -> Path:
    """Scripts and deps live under gcp/image/scripts/ (single source of truth)."""
    return repo_root() / IMAGE_SCRIPTS / rel


def _bootstrap_path(rel: str) -> Path:
    """Alias for _vm_path; bootstrap name kept for test readability."""
    return _vm_path(rel)


def _metadata_entrypoint_path() -> Path:
    """Packaged entrypoint used by sync-vm-metadata (ci.resources)."""
    return repo_root() / GITHUB_BMT_ROOT / "ci" / "resources" / "startup_entrypoint.sh"


def _packer_template_path() -> Path:
    return repo_root() / "infra" / "packer" / "bmt-runtime.pkr.hcl"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_bootstrap_scripts_parse_with_bash_n() -> None:
    # Only shell scripts under gcp/image/scripts and metadata entrypoint; Python scripts are not bash-checked.
    scripts = (
        _bootstrap_path("startup_entrypoint.sh"),
        _metadata_entrypoint_path(),
        repo_root() / "tools" / "scripts" / "hooks" / "pre-commit-sync-gcp.sh",
        repo_root() / "tools" / "scripts" / "hooks" / "pre-commit-image-build-warning.sh",
    )
    for script in scripts:
        if script.exists():
            subprocess.run(["bash", "-n", str(script)], check=True)


def test_install_deps_pip(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools>=61"]\nbuild-backend = "setuptools.build_meta"\n\n'
        "[project]\nname='bootstrap-test'\nversion='0.0.1'\n\n"
        '[project.optional-dependencies]\nvm = ["httpx>=0.27"]\n\n'
        '[tool.setuptools.packages.find]\nwhere = ["."]\ninclude = ["config*"]\n',
        encoding="utf-8",
    )
    (work_dir / "config").mkdir(parents=True, exist_ok=True)
    (work_dir / "config" / "__init__.py").write_text("", encoding="utf-8")
    (work_dir / "config" / "bmt_config.py").write_text("", encoding="utf-8")
    bootstrap_dir = work_dir / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    pip_calls = tmp_path / "pip.calls"
    venv_bin = work_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    _write_executable(
        venv_bin / "pip",
        (f"#!/usr/bin/env bash\nset -euo pipefail\necho \"$*\" >> '{pip_calls}'\nexit 0\n"),
    )
    # Fake python: when run as "python -m pip ...", forward to pip so both pip calls are recorded.
    _write_executable(
        venv_bin / "python",
        '#!/usr/bin/env bash\nset -euo pipefail\n[[ "$1" == "-m" && "$2" == "pip" ]] && exec "$(dirname "$0")/pip" "${@:3}"\nexit 0\n',
    )

    subprocess.run(
        [sys.executable, str(_bootstrap_path("install_deps.py")), str(work_dir)],
        check=True,
        cwd=work_dir,
    )

    assert pip_calls.exists(), "Expected pip installer to run"
    calls = pip_calls.read_text(encoding="utf-8")
    assert "--upgrade pip" in calls
    assert "-e" in calls and "[vm]" in calls
    assert (work_dir / ".venv" / ".bmt_dep_fingerprint").is_file()


def test_install_deps_fails_without_pyproject(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        [sys.executable, str(_bootstrap_path("install_deps.py")), str(work_dir)],
        check=False,
        cwd=work_dir,
    )
    assert proc.returncode != 0


def test_install_deps_fails_without_vm_deps(tmp_path: Path) -> None:
    """install_deps.py fails when pyproject has no [vm] optional-dependencies."""
    work_dir = tmp_path / "repo"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "pyproject.toml").write_text(
        "[project]\nname='bootstrap-test'\nversion='0.0.1'\n\n"
        '[tool.setuptools.packages.find]\nwhere = ["."]\ninclude = ["config*"]\n',
        encoding="utf-8",
    )
    (work_dir / "config").mkdir(parents=True, exist_ok=True)
    (work_dir / "config" / "__init__.py").write_text("", encoding="utf-8")
    (work_dir / "config" / "bmt_config.py").write_text("", encoding="utf-8")
    # No [project.optional-dependencies] vm extra

    proc = subprocess.run(
        [sys.executable, str(_bootstrap_path("install_deps.py")), str(work_dir)],
        check=False,
        cwd=work_dir,
    )
    assert proc.returncode != 0


def test_install_deps_fails_when_import_check_fails(tmp_path: Path) -> None:
    """install_deps.py must exit non-zero when the post-install import check fails (fail-fast)."""
    work_dir = tmp_path / "repo"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "pyproject.toml").write_text(
        "[project]\nname='bootstrap-test'\nversion='0.0.1'\n\n"
        '[project.optional-dependencies]\nvm = ["httpx>=0.27"]\n\n'
        '[tool.setuptools.packages.find]\nwhere = ["."]\ninclude = ["config*"]\n',
        encoding="utf-8",
    )
    (work_dir / "config").mkdir(parents=True, exist_ok=True)
    (work_dir / "config" / "__init__.py").write_text("", encoding="utf-8")
    (work_dir / "config" / "bmt_config.py").write_text("", encoding="utf-8")

    venv_bin = work_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    _write_executable(venv_bin / "pip", "#!/usr/bin/env bash\nexit 0\n")
    # Python that fails the import check (when -c is passed).
    _write_executable(
        venv_bin / "python",
        '#!/usr/bin/env bash\nset -euo pipefail\n[[ "${1:-}" == "-c" ]] && exit 1\nexit 0\n',
    )

    proc = subprocess.run(
        [sys.executable, str(_bootstrap_path("install_deps.py")), str(work_dir)],
        check=False,
        cwd=work_dir,
    )
    assert proc.returncode != 0


def test_packer_and_install_deps_use_same_vm_deps_source() -> None:
    """Packer template uses gcp/image/scripts/vm_deps.txt; install_deps uses pyproject [vm]."""
    packer_content = _packer_template_path().read_text(encoding="utf-8")
    assert "vm_deps.txt" in packer_content, "Packer should reference vm_deps.txt"
    deps_file = _vm_path("vm_deps.txt")
    assert deps_file.exists(), "Single source of truth vm_deps.txt must exist under gcp/image/scripts/"
    lines = [
        s.strip()
        for s in deps_file.read_text(encoding="utf-8").splitlines()
        if s.strip() and not s.strip().startswith("#")
    ]
    assert len(lines) >= 1, "vm_deps.txt should list at least one package"


def test_run_watcher_handles_home_unset(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    (work_dir / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(_bootstrap_path("run_watcher.py"), work_dir / "scripts" / "run_watcher.py")
    shutil.copy2(repo_root() / "gcp" / "image" / "path_utils.py", work_dir / "path_utils.py")
    (work_dir / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")

    venv_python = work_dir / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    _write_executable(venv_python, "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.pop("HOME", None)
    env["BMT_REPO_ROOT"] = str(work_dir)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_SELF_STOP"] = "0"

    subprocess.run(
        [sys.executable, str(work_dir / "scripts" / "run_watcher.py")],
        check=True,
        cwd=work_dir,
        env=env,
    )


def test_run_watcher_self_stop_falls_back_to_compute_api_when_gcloud_fails(tmp_path: Path) -> None:
    """Run run_watcher.py with BMT_SELF_STOP=1; self-stop uses gcloud then Compute API fallback (skipped in unit test)."""
    import pytest

    pytest.skip("run_watcher.py self-stop fallback is integration behavior; shell test was removed with migration")


def test_run_watcher_fails_fast_when_prebaked_python_missing(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    (work_dir / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(_bootstrap_path("run_watcher.py"), work_dir / "scripts" / "run_watcher.py")
    shutil.copy2(repo_root() / "gcp" / "image" / "path_utils.py", work_dir / "path_utils.py")
    (work_dir / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")
    # No .venv/bin/python

    env = os.environ.copy()
    env["BMT_REPO_ROOT"] = str(work_dir)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_SELF_STOP"] = "0"

    proc = subprocess.run(
        [sys.executable, str(work_dir / "scripts" / "run_watcher.py")],
        check=False,
        cwd=work_dir,
        env=env,
    )
    assert proc.returncode != 0


def test_run_watcher_fails_fast_when_prebaked_imports_missing(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    (work_dir / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(_bootstrap_path("run_watcher.py"), work_dir / "scripts" / "run_watcher.py")
    shutil.copy2(repo_root() / "gcp" / "image" / "path_utils.py", work_dir / "path_utils.py")
    (work_dir / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")

    venv_python = work_dir / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    # Python that fails the venv import check (subprocess -c "import jwt; ...")
    _write_executable(
        venv_python,
        '#!/usr/bin/env bash\nset -euo pipefail\n[[ "${1:-}" == "-c" ]] && exit 1\nexit 0\n',
    )

    env = os.environ.copy()
    env["BMT_REPO_ROOT"] = str(work_dir)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_SELF_STOP"] = "0"

    proc = subprocess.run(
        [sys.executable, str(work_dir / "scripts" / "run_watcher.py")],
        check=False,
        cwd=work_dir,
        env=env,
    )
    assert proc.returncode != 0


def test_startup_entrypoint_keeps_runtime_venv() -> None:
    entrypoint_sources = (_bootstrap_path("startup_entrypoint.sh"), _metadata_entrypoint_path())
    for path in entrypoint_sources:
        content = path.read_text(encoding="utf-8")
        assert "-name '.venv'" not in content, f"{path} should not delete persistent .venv"


def test_run_watcher_no_runtime_install_path() -> None:
    content = _bootstrap_path("run_watcher.py").read_text(encoding="utf-8")
    assert "install_deps" not in content
    assert "ensure_uv" not in content


def test_startup_entrypoint_uses_baked_runtime_only() -> None:
    # Metadata entrypoint (workflow inline) must not sync from GCS; baked runtime only.
    content = _metadata_entrypoint_path().read_text(encoding="utf-8")
    assert "gcloud storage rsync" not in content
    assert "run_watcher.py" in content
    # Bootstrap entrypoint in gcp/image/scripts/ may do eager code sync; ensure it runs the watcher.
    bootstrap_content = _bootstrap_path("startup_entrypoint.sh").read_text(encoding="utf-8")
    assert "run_watcher.py" in bootstrap_content


def test_packer_template_has_manifest_fields() -> None:
    packer_template = _packer_template_path().read_text(encoding="utf-8")
    assert "GLIBC_VERSION" in packer_template
    assert "'glibc_version'" in packer_template
    assert "cloud-init clean --logs --machine-id" in packer_template
