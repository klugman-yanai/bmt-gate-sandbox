"""Deterministic validation for bootstrap shell scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bootstrap_path(rel: str) -> Path:
    return _repo_root() / "gcp" / "code" / "bootstrap" / rel


def _metadata_wrapper_path() -> Path:
    return _repo_root() / ".github" / "bmt" / "cli" / "resources" / "startup_wrapper.sh"


def _packer_template_path() -> Path:
    return _repo_root() / "infra" / "packer" / "bmt-runtime.pkr.hcl"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_bootstrap_scripts_parse_with_bash_n() -> None:
    scripts = (
        _bootstrap_path("startup_example.sh"),
        _bootstrap_path("install_deps.sh"),
        _bootstrap_path("startup_wrapper.sh"),
        _metadata_wrapper_path(),
    )
    for script in scripts:
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_install_deps_pip(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text("[project]\nname='bootstrap-test'\nversion='0.0.1'\n", encoding="utf-8")

    pip_calls = tmp_path / "pip.calls"
    venv_bin = repo_root / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    _write_executable(
        venv_bin / "pip",
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"echo \"$*\" >> '{pip_calls}'\n"
            "exit 0\n"
        ),
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
    assert "google-cloud-storage>=2.16" in calls
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


def test_startup_example_handles_home_unset(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bootstrap_dir = repo_root / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(_bootstrap_path("startup_example.sh"), bootstrap_dir / "startup_example.sh")
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
        ["bash", str(bootstrap_dir / "startup_example.sh")],
        check=True,
        cwd=repo_root,
        env=env,
    )


def test_startup_example_self_stop_falls_back_to_compute_api_when_gcloud_fails(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bootstrap_dir = repo_root / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(_bootstrap_path("startup_example.sh"), bootstrap_dir / "startup_example.sh")
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
        "#!/usr/bin/env bash\n"
        "exit 1\n",
    )

    fake_curl = fake_bin / "curl"
    _write_executable(
        fake_curl,
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "url=\"${@: -1}\"\n"
            "case \"$url\" in\n"
            "  *'/instance/name') echo 'vm-test' ;;\n"
            "  *'/instance/zone') echo 'projects/1/zones/europe-west4-a' ;;\n"
            "  *'/project/project-id') echo 'proj-test' ;;\n"
            "  *'/service-accounts/default/token') echo '{\"access_token\":\"token-test\"}' ;;\n"
            "  *'compute.googleapis.com/compute/v1/projects/proj-test/zones/europe-west4-a/instances/vm-test/stop')\n"
            "    printf '%s\\n' \"$url\" >> \"${STOP_LOG:?}\"\n"
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
        ["bash", str(bootstrap_dir / "startup_example.sh")],
        check=False,
        cwd=repo_root,
        env=env,
    )
    assert proc.returncode != 0
    assert stop_log.exists(), "Expected Compute API fallback stop call to be recorded"
    assert "compute.googleapis.com/compute/v1/projects/proj-test/zones/europe-west4-a/instances/vm-test/stop" in (
        stop_log.read_text(encoding="utf-8")
    )


def test_startup_example_fails_fast_when_prebaked_python_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bootstrap_dir = repo_root / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_bootstrap_path("startup_example.sh"), bootstrap_dir / "startup_example.sh")
    (repo_root / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")

    env = os.environ.copy()
    env["BMT_REPO_ROOT"] = str(repo_root)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_SELF_STOP"] = "0"

    proc = subprocess.run(
        ["bash", str(bootstrap_dir / "startup_example.sh")],
        check=False,
        cwd=repo_root,
        env=env,
    )
    assert proc.returncode != 0


def test_startup_example_fails_fast_when_prebaked_imports_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bootstrap_dir = repo_root / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_bootstrap_path("startup_example.sh"), bootstrap_dir / "startup_example.sh")
    (repo_root / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")

    venv_python = repo_root / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    _write_executable(
        venv_python,
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'if [[ "${1:-}" == "-" ]]; then\n'
            "  exit 1\n"
            "fi\n"
            "exit 0\n"
        ),
    )

    env = os.environ.copy()
    env["BMT_REPO_ROOT"] = str(repo_root)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_SELF_STOP"] = "0"

    proc = subprocess.run(
        ["bash", str(bootstrap_dir / "startup_example.sh")],
        check=False,
        cwd=repo_root,
        env=env,
    )
    assert proc.returncode != 0


def test_startup_wrapper_keeps_runtime_venv() -> None:
    wrapper_sources = (_bootstrap_path("startup_wrapper.sh"), _metadata_wrapper_path())
    for path in wrapper_sources:
        content = path.read_text(encoding="utf-8")
        assert "-name '.venv'" not in content, f"{path} should not delete persistent .venv"


def test_startup_example_no_runtime_install_path() -> None:
    content = _bootstrap_path("startup_example.sh").read_text(encoding="utf-8")
    assert "install_deps.sh" not in content
    assert "ensure_uv.sh" not in content


def test_startup_wrapper_uses_baked_runtime_only() -> None:
    wrapper_sources = (_bootstrap_path("startup_wrapper.sh"), _metadata_wrapper_path())
    for path in wrapper_sources:
        content = path.read_text(encoding="utf-8")
        assert "gcloud storage rsync" not in content
        assert "startup_example.sh" in content


def test_build_image_scripts_have_manifest_fields() -> None:
    build_script = _bootstrap_path("build_bmt_image.sh").read_text(encoding="utf-8")
    assert "GLIBC_VERSION" in build_script
    assert "'glibc_version'" in build_script
    assert "cloud-init clean --logs --machine-id" in build_script

    packer_template = _packer_template_path().read_text(encoding="utf-8")
    assert "GLIBC_VERSION" in packer_template
    assert "'glibc_version'" in packer_template
    assert "cloud-init clean --logs --machine-id" in packer_template
