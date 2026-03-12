"""Deterministic validation for bootstrap shell scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    # Tests can move around; resolve repo root by walking upward.
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "gcp").is_dir() and (parent / "infra").is_dir():
            return parent
    raise RuntimeError(f"Unable to resolve repo root from {here}")


def _vm_path(rel: str) -> Path:
    """Scripts and deps live under gcp/code/vm/ (single source of truth)."""
    return _repo_root() / "gcp" / "code" / "vm" / rel


def _bootstrap_path(rel: str) -> Path:
    """Alias for _vm_path; bootstrap name kept for test readability."""
    return _vm_path(rel)


def _metadata_entrypoint_path() -> Path:
    return _repo_root() / ".github" / "bmt" / "cli" / "resources" / "startup_entrypoint.sh"


def _packer_template_path() -> Path:
    return _repo_root() / "infra" / "packer" / "bmt-runtime.pkr.hcl"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_bootstrap_scripts_parse_with_bash_n() -> None:
    scripts = (
        _bootstrap_path("run_watcher.sh"),
        _bootstrap_path("install_deps.sh"),
        _bootstrap_path("startup_entrypoint.sh"),
        _bootstrap_path("set_startup_script_url.sh"),
        _bootstrap_path("rollback_startup_to_inline.sh"),
        _bootstrap_path("shared.sh"),
        _metadata_entrypoint_path(),
        _repo_root() / "tools" / "scripts" / "hooks" / "pre-commit-sync-gcp.sh",
        _repo_root() / "tools" / "scripts" / "hooks" / "pre-commit-image-build-warning.sh",
    )
    for script in scripts:
        if script.exists():
            subprocess.run(["bash", "-n", str(script)], check=True)


def test_install_deps_pip(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools>=61"]\nbuild-backend = "setuptools.build_meta"\n\n'
        "[project]\nname='bootstrap-test'\nversion='0.0.1'\n\n"
        '[project.optional-dependencies]\nvm = ["httpx>=0.27"]\n\n'
        '[tool.setuptools.packages.find]\nwhere = ["."]\ninclude = ["lib*"]\n',
        encoding="utf-8",
    )
    (repo_root / "lib").mkdir(parents=True, exist_ok=True)
    (repo_root / "lib" / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "lib" / "bmt_config.py").write_text("", encoding="utf-8")
    bootstrap_dir = repo_root / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    pip_calls = tmp_path / "pip.calls"
    venv_bin = repo_root / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    _write_executable(
        venv_bin / "pip",
        (f"#!/usr/bin/env bash\nset -euo pipefail\necho \"$*\" >> '{pip_calls}'\nexit 0\n"),
    )
    _write_executable(venv_bin / "python", "#!/usr/bin/env bash\nexit 0\n")

    subprocess.run(
        ["bash", str(_bootstrap_path("install_deps.sh")), str(repo_root)],
        check=True,
        cwd=_repo_root(),
    )

    assert pip_calls.exists(), "Expected pip installer to run"
    calls = pip_calls.read_text(encoding="utf-8")
    assert "--upgrade pip" in calls
    assert "-e" in calls and "[vm]" in calls
    assert (repo_root / ".venv" / ".bmt_dep_fingerprint").is_file()


def test_install_deps_fails_without_pyproject(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        ["bash", str(_bootstrap_path("install_deps.sh")), str(repo_root)],
        check=False,
        cwd=_repo_root(),
    )
    assert proc.returncode != 0


def test_install_deps_fails_without_vm_deps(tmp_path: Path) -> None:
    """install_deps.sh fails when pyproject has no [vm] optional-dependencies."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text(
        "[project]\nname='bootstrap-test'\nversion='0.0.1'\n\n"
        "[tool.setuptools.packages.find]\nwhere = [\".\"]\ninclude = [\"lib*\"]\n",
        encoding="utf-8",
    )
    (repo_root / "lib").mkdir(parents=True, exist_ok=True)
    (repo_root / "lib" / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "lib" / "bmt_config.py").write_text("", encoding="utf-8")
    # No [project.optional-dependencies] vm extra

    proc = subprocess.run(
        ["bash", str(_bootstrap_path("install_deps.sh")), str(repo_root)],
        check=False,
        cwd=_repo_root(),
    )
    assert proc.returncode != 0


def test_install_deps_fails_when_import_check_fails(tmp_path: Path) -> None:
    """install_deps.sh must exit non-zero when the post-install import check fails (fail-fast)."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text(
        "[project]\nname='bootstrap-test'\nversion='0.0.1'\n\n"
        "[project.optional-dependencies]\nvm = [\"httpx>=0.27\"]\n\n"
        "[tool.setuptools.packages.find]\nwhere = [\".\"]\ninclude = [\"lib*\"]\n",
        encoding="utf-8",
    )
    (repo_root / "lib").mkdir(parents=True, exist_ok=True)
    (repo_root / "lib" / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "lib" / "bmt_config.py").write_text("", encoding="utf-8")

    venv_bin = repo_root / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    _write_executable(venv_bin / "pip", "#!/usr/bin/env bash\nexit 0\n")
    # Python that passes -c with the import check would run "import jwt; ..." — we make it fail.
    _write_executable(
        venv_bin / "python",
        '#!/usr/bin/env bash\nset -euo pipefail\n[[ "${1:-}" == "-c" ]] && exit 1\nexit 0\n',
    )

    proc = subprocess.run(
        ["bash", str(_bootstrap_path("install_deps.sh")), str(repo_root)],
        check=False,
        cwd=_repo_root(),
    )
    assert proc.returncode != 0


def test_packer_and_install_deps_use_same_vm_deps_source() -> None:
    """Packer template uses gcp/code/vm/vm_deps.txt; install_deps uses pyproject [vm]."""
    packer_content = _packer_template_path().read_text(encoding="utf-8")
    assert "vm_deps.txt" in packer_content, "Packer should reference vm_deps.txt"
    deps_file = _vm_path("vm_deps.txt")
    assert deps_file.exists(), "Single source of truth vm_deps.txt must exist under gcp/code/vm/"
    lines = [
        s.strip()
        for s in deps_file.read_text(encoding="utf-8").splitlines()
        if s.strip() and not s.strip().startswith("#")
    ]
    assert len(lines) >= 1, "vm_deps.txt should list at least one package"


def test_run_watcher_handles_home_unset(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bootstrap_dir = repo_root / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(_bootstrap_path("run_watcher.sh"), bootstrap_dir / "run_watcher.sh")
    shutil.copy2(_bootstrap_path("shared.sh"), bootstrap_dir / "shared.sh")
    (repo_root / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")

    venv_python = repo_root / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    _write_executable(venv_python, "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.pop("HOME", None)
    env["BMT_REPO_ROOT"] = str(repo_root)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_SELF_STOP"] = "0"

    subprocess.run(
        ["bash", str(bootstrap_dir / "run_watcher.sh")],
        check=True,
        cwd=repo_root,
        env=env,
    )


def test_run_watcher_self_stop_falls_back_to_compute_api_when_gcloud_fails(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bootstrap_dir = repo_root / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(_bootstrap_path("run_watcher.sh"), bootstrap_dir / "run_watcher.sh")
    shutil.copy2(_bootstrap_path("shared.sh"), bootstrap_dir / "shared.sh")
    (repo_root / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")

    venv_python = repo_root / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    _write_executable(venv_python, "#!/usr/bin/env bash\nexit 0\n")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    stop_log = tmp_path / "stop-url.log"

    fake_gcloud = fake_bin / "gcloud"
    _write_executable(
        fake_gcloud,
        "#!/usr/bin/env bash\nexit 1\n",
    )

    fake_curl = fake_bin / "curl"
    _write_executable(
        fake_curl,
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'url="${@: -1}"\n'
            'case "$url" in\n'
            "  *'/instance/name') echo 'vm-test' ;;\n"
            "  *'/instance/zone') echo 'projects/1/zones/europe-west4-a' ;;\n"
            "  *'/project/project-id') echo 'proj-test' ;;\n"
            "  *'/service-accounts/default/token') echo '{\"access_token\":\"token-test\"}' ;;\n"
            "  *'compute.googleapis.com/compute/v1/projects/proj-test/zones/europe-west4-a/instances/vm-test/stop')\n"
            '    printf \'%s\\n\' "$url" >> "${STOP_LOG:?}"\n'
            "    echo '200'\n"
            "    ;;\n"
            "  *)\n"
            "    exit 1\n"
            "    ;;\n"
            "esac\n"
        ),
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env["STOP_LOG"] = str(stop_log)
    env["BMT_REPO_ROOT"] = str(repo_root)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_SELF_STOP"] = "1"

    proc = subprocess.run(
        ["bash", str(bootstrap_dir / "run_watcher.sh")],
        check=False,
        cwd=repo_root,
        env=env,
    )
    assert proc.returncode != 0
    assert stop_log.exists(), "Expected Compute API fallback stop call to be recorded"
    assert "compute.googleapis.com/compute/v1/projects/proj-test/zones/europe-west4-a/instances/vm-test/stop" in (
        stop_log.read_text(encoding="utf-8")
    )


def test_run_watcher_fails_fast_when_prebaked_python_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bootstrap_dir = repo_root / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_bootstrap_path("run_watcher.sh"), bootstrap_dir / "run_watcher.sh")
    shutil.copy2(_bootstrap_path("shared.sh"), bootstrap_dir / "shared.sh")
    (repo_root / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")

    env = os.environ.copy()
    env["BMT_REPO_ROOT"] = str(repo_root)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_SELF_STOP"] = "0"

    proc = subprocess.run(
        ["bash", str(bootstrap_dir / "run_watcher.sh")],
        check=False,
        cwd=repo_root,
        env=env,
    )
    assert proc.returncode != 0


def test_run_watcher_fails_fast_when_prebaked_imports_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bootstrap_dir = repo_root / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_bootstrap_path("run_watcher.sh"), bootstrap_dir / "run_watcher.sh")
    shutil.copy2(_bootstrap_path("shared.sh"), bootstrap_dir / "shared.sh")
    (repo_root / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")

    venv_python = repo_root / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    _write_executable(
        venv_python,
        ('#!/usr/bin/env bash\nset -euo pipefail\nif [[ "${1:-}" == "-" ]]; then\n  exit 1\nfi\nexit 0\n'),
    )

    env = os.environ.copy()
    env["BMT_REPO_ROOT"] = str(repo_root)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_SELF_STOP"] = "0"

    proc = subprocess.run(
        ["bash", str(bootstrap_dir / "run_watcher.sh")],
        check=False,
        cwd=repo_root,
        env=env,
    )
    assert proc.returncode != 0


def test_startup_entrypoint_keeps_runtime_venv() -> None:
    entrypoint_sources = (_bootstrap_path("startup_entrypoint.sh"), _metadata_entrypoint_path())
    for path in entrypoint_sources:
        content = path.read_text(encoding="utf-8")
        assert "-name '.venv'" not in content, f"{path} should not delete persistent .venv"


def test_run_watcher_no_runtime_install_path() -> None:
    content = _bootstrap_path("run_watcher.sh").read_text(encoding="utf-8")
    assert "install_deps.sh" not in content
    assert "ensure_uv.sh" not in content


def test_startup_entrypoint_uses_baked_runtime_only() -> None:
    entrypoint_sources = (_bootstrap_path("startup_entrypoint.sh"), _metadata_entrypoint_path())
    for path in entrypoint_sources:
        content = path.read_text(encoding="utf-8")
        assert "gcloud storage rsync" not in content
        assert "run_watcher.sh" in content


def test_build_image_scripts_have_manifest_fields() -> None:
    build_script = _bootstrap_path("build_bmt_image.sh").read_text(encoding="utf-8")
    assert "GLIBC_VERSION" in build_script
    assert "'glibc_version'" in build_script
    assert "cloud-init clean --logs --machine-id" in build_script

    packer_template = _packer_template_path().read_text(encoding="utf-8")
    assert "GLIBC_VERSION" in packer_template
    assert "'glibc_version'" in packer_template
    assert "cloud-init clean --logs --machine-id" in packer_template
