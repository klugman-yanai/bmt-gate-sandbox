"""Shared pytest path/bootstrap config and canonical path fixtures."""

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return _ROOT


@pytest.fixture(scope="session")
def gcp_code_root(repo_root: Path) -> Path:
    path = repo_root / "gcp" / "code"
    assert path.exists(), f"Expected gcp code root to exist: {path}"
    return path


@pytest.fixture(scope="session")
def github_bmt_root(repo_root: Path) -> Path:
    path = repo_root / ".github" / "bmt"
    assert path.exists(), f"Expected .github/bmt root to exist: {path}"
    return path


@pytest.fixture(autouse=True)
def _stable_repo_cwd(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    # Keep relative-path behavior deterministic regardless of where pytest is invoked.
    monkeypatch.chdir(repo_root)


@pytest.fixture(autouse=True)
def _reset_bmt_config_cache() -> None:
    # ci package does not cache config; no-op for cross-test isolation.
    yield


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-assign baseline test-layer markers to keep suite taxonomy consistent."""
    for item in items:
        name = item.nodeid
        if "live_smoke" in name:
            item.add_marker("live_smoke")
            continue
        if any(
            key in name for key in ("test_ci_commands.py", "test_bootstrap_scripts.py", "test_devtools_exit_codes.py")
        ):
            item.add_marker("integration")
            continue
        if any(
            key in name
            for key in (
                "test_run_trigger_guard.py",
                "test_wait_handshake.py",
                "test_start_vm.py",
                "test_sync_vm_metadata.py",
                "test_upload_runner_dedup.py",
                "test_vm_watcher_",
            )
        ):
            item.add_marker("contract")
            continue
        item.add_marker("unit")
