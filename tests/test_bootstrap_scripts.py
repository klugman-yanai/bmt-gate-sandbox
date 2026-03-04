"""Deterministic validation for bootstrap shell scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bootstrap_path(rel: str) -> Path:
    return _repo_root() / "remote" / "code" / "bootstrap" / rel


def _metadata_wrapper_path() -> Path:
    return _repo_root() / ".github" / "bmt" / "cli" / "resources" / "startup_wrapper.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_bootstrap_scripts_parse_with_bash_n() -> None:
    scripts = (
        _bootstrap_path("ensure_uv.sh"),
        _bootstrap_path("startup_example.sh"),
        _bootstrap_path("install_deps.sh"),
        _bootstrap_path("startup_wrapper.sh"),
        _metadata_wrapper_path(),
    )
    for script in scripts:
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_ensure_uv_uses_bmt_uv_bin_override(tmp_path: Path) -> None:
    fake_uv = tmp_path / "uv"
    _write_executable(fake_uv, "#!/usr/bin/env bash\nexit 0\n")

    cmd = [
        "bash",
        "-lc",
        (
            "set -euo pipefail; "
            f"BMT_UV_BIN='{fake_uv}' source '{_bootstrap_path('ensure_uv.sh')}'; "
            f"test \"$UV_BIN\" = '{fake_uv}'"
        ),
    ]
    subprocess.run(cmd, check=True, cwd=_repo_root())


def test_install_deps_uses_uv_bin_override(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text("[project]\nname='bootstrap-test'\nversion='0.0.1'\n", encoding="utf-8")
    (repo_root / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    fake_uv = tmp_path / "uv"
    _write_executable(
        fake_uv,
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'if [[ "${1:-}" == "sync" ]]; then\n'
            "  mkdir -p .venv/bin\n"
            "  cat > .venv/bin/python <<'PY'\n"
            "#!/usr/bin/env bash\n"
            "exit 0\n"
            "PY\n"
            "  chmod +x .venv/bin/python\n"
            "fi\n"
            "exit 0\n"
        ),
    )

    env = os.environ.copy()
    env["UV_BIN"] = str(fake_uv)
    subprocess.run(
        ["bash", str(_bootstrap_path("install_deps.sh")), str(repo_root)],
        check=True,
        cwd=_repo_root(),
        env=env,
    )
    assert (repo_root / ".venv" / "bin" / "python").is_file()


def test_install_deps_non_frozen_when_lock_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text(
        "[project]\nname='bootstrap-test'\nversion='0.0.1'\n[tool.uv]\npackage = false\n",
        encoding="utf-8",
    )

    fake_uv = tmp_path / "uv"
    _write_executable(
        fake_uv,
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'if [[ "${1:-}" == "sync" ]]; then\n'
            "  mkdir -p .venv/bin\n"
            "  cat > .venv/bin/python <<'PY'\n"
            "#!/usr/bin/env bash\n"
            "exit 0\n"
            "PY\n"
            "  chmod +x .venv/bin/python\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n"
        ),
    )

    env = os.environ.copy()
    env["UV_BIN"] = str(fake_uv)
    subprocess.run(
        ["bash", str(_bootstrap_path("install_deps.sh")), str(repo_root)],
        check=True,
        cwd=_repo_root(),
        env=env,
    )
    assert (repo_root / ".venv" / "bin" / "python").is_file()


def test_install_deps_fails_without_pyproject(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    fake_uv = tmp_path / "uv"
    _write_executable(fake_uv, "#!/usr/bin/env bash\nexit 0\n")
    env = os.environ.copy()
    env["UV_BIN"] = str(fake_uv)

    proc = subprocess.run(
        ["bash", str(_bootstrap_path("install_deps.sh")), str(repo_root)],
        check=False,
        cwd=_repo_root(),
        env=env,
    )
    assert proc.returncode != 0


def test_startup_example_handles_home_unset(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bootstrap_dir = repo_root / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(_bootstrap_path("startup_example.sh"), bootstrap_dir / "startup_example.sh")
    shutil.copy2(_bootstrap_path("install_deps.sh"), bootstrap_dir / "install_deps.sh")
    shutil.copy2(_bootstrap_path("ensure_uv.sh"), bootstrap_dir / "ensure_uv.sh")
    (repo_root / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")

    venv_python = repo_root / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    _write_executable(venv_python, "#!/usr/bin/env bash\nexit 0\n")

    fake_uv = tmp_path / "uv"
    _write_executable(fake_uv, "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.pop("HOME", None)
    env["BMT_REPO_ROOT"] = str(repo_root)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_UV_BIN"] = str(fake_uv)
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
    shutil.copy2(_bootstrap_path("install_deps.sh"), bootstrap_dir / "install_deps.sh")
    shutil.copy2(_bootstrap_path("ensure_uv.sh"), bootstrap_dir / "ensure_uv.sh")
    (repo_root / "vm_watcher.py").write_text("print('ok')\n", encoding="utf-8")

    venv_python = repo_root / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    _write_executable(venv_python, "#!/usr/bin/env bash\nexit 0\n")

    fake_uv = tmp_path / "uv"
    _write_executable(fake_uv, "#!/usr/bin/env bash\nexit 0\n")

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
    env["BMT_UV_BIN"] = str(fake_uv)
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


def test_ensure_uv_downloads_pinned_artifact_when_uv_missing(tmp_path: Path) -> None:
    fake_bucket = tmp_path / "bucket" / "code" / "_tools" / "uv" / "linux-x86_64"
    fake_bucket.mkdir(parents=True, exist_ok=True)
    pinned_uv = fake_bucket / "uv"
    _write_executable(pinned_uv, "#!/usr/bin/env bash\necho uv-test\n")
    pinned_sha = subprocess.check_output(["sha256sum", str(pinned_uv)], text=True).split()[0]
    (fake_bucket / "uv.sha256").write_text(f"{pinned_sha}  uv\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    for tool in ("bash", "awk", "sha256sum", "mktemp", "install", "cp", "mkdir", "rm"):
        src = shutil.which(tool)
        assert src, f"Missing required host tool for test: {tool}"
        (fake_bin / tool).symlink_to(src)

    fake_gcloud = fake_bin / "gcloud"
    _write_executable(
        fake_gcloud,
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'if [[ "$1" == "storage" && "$2" == "cp" ]]; then\n'
            '  src="$3"\n'
            '  dst="$4"\n'
            f"  root='{(tmp_path / 'bucket').as_posix()}'\n"
            '  if [[ "$src" == gs://test-bucket/* ]]; then\n'
            '    rel="${src#gs://test-bucket/}"\n'
            '    cp "$root/$rel" "$dst"\n'
            "    exit 0\n"
            "  fi\n"
            "fi\n"
            'echo "unsupported gcloud call: $*" >&2\n'
            "exit 1\n"
        ),
    )

    install_root = tmp_path / "repo"
    install_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    env["GCS_BUCKET"] = "test-bucket"
    env["BMT_REPO_ROOT"] = str(install_root)
    env.pop("BMT_UV_BIN", None)

    cmd = (
        "set -euo pipefail; "
        f"source '{_bootstrap_path('ensure_uv.sh')}'; "
        'test -x "$UV_BIN"; '
        'test "$UV_BIN" = "$BMT_REPO_ROOT/.tools/uv/linux-x86_64/uv"'
    )
    subprocess.run(["/bin/bash", "-c", cmd], check=True, cwd=_repo_root(), env=env)


def test_startup_wrapper_keeps_runtime_venv() -> None:
    wrapper_sources = (_bootstrap_path("startup_wrapper.sh"), _metadata_wrapper_path())
    for path in wrapper_sources:
        content = path.read_text(encoding="utf-8")
        assert "-name '.venv'" not in content, f"{path} should not delete persistent .venv"
