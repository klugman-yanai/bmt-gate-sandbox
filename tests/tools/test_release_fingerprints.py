"""Tests for ``tools.shared.release_fingerprints``.

These helpers emit per-surface fingerprints into the CI release workflow.
They intentionally swallow tool failures and return ``None`` — tests verify
both the success and failure paths stay faithful to that contract (so the
release marker never fails a deploy over an unreachable fingerprint).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.shared.release_fingerprints import (
    emit_github_output,
    plugins_tree_sha,
    pulumi_stack_sha,
)

pytestmark = pytest.mark.unit


def _init_git(root: Path) -> None:
    """Create an isolated git repo with a deterministic committer identity.

    We go through plumbing commands rather than ``git init -q && git add``
    so the tests never depend on the developer's global git config.
    """
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)


def test_plugins_tree_sha_returns_40char_hex(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "plugins" / "projects" / "demo").mkdir(parents=True)
    (tmp_path / "plugins" / "projects" / "demo" / "manifest.json").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=tmp_path, check=True)

    sha = plugins_tree_sha(tmp_path)
    assert sha is not None
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_plugins_tree_sha_is_stable_across_calls(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "plugins" / "projects" / "demo").mkdir(parents=True)
    (tmp_path / "plugins" / "projects" / "demo" / "x").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=tmp_path, check=True)

    first = plugins_tree_sha(tmp_path)
    second = plugins_tree_sha(tmp_path)
    assert first is not None
    assert first == second


def test_plugins_tree_sha_changes_when_content_changes(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "plugins" / "projects" / "demo").mkdir(parents=True)
    target = tmp_path / "plugins" / "projects" / "demo" / "x"
    target.write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "one"], cwd=tmp_path, check=True)
    sha1 = plugins_tree_sha(tmp_path)

    target.write_text("b", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "two"], cwd=tmp_path, check=True)
    sha2 = plugins_tree_sha(tmp_path)

    assert sha1 is not None and sha2 is not None
    assert sha1 != sha2


def test_plugins_tree_sha_returns_none_when_subdir_missing(tmp_path: Path) -> None:
    _init_git(tmp_path)
    assert plugins_tree_sha(tmp_path) is None


def test_plugins_tree_sha_returns_none_when_not_a_git_repo(tmp_path: Path) -> None:
    (tmp_path / "plugins" / "projects").mkdir(parents=True)
    assert plugins_tree_sha(tmp_path) is None


def test_pulumi_stack_sha_returns_none_when_dir_missing(tmp_path: Path) -> None:
    assert pulumi_stack_sha(tmp_path / "does-not-exist") is None


def test_pulumi_stack_sha_returns_hash_of_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.mkdir(exist_ok=True)
    export_body = '{"version": 3, "resources": []}\n'

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert cmd[0] == "pulumi"
        assert "export" in cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=export_body, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sha = pulumi_stack_sha(tmp_path)
    assert sha is not None
    assert len(sha) == 64

    import hashlib

    assert sha == hashlib.sha256(export_body.encode("utf-8")).hexdigest()


def test_pulumi_stack_sha_returns_none_on_pulumi_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="no stack")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert pulumi_stack_sha(tmp_path) is None


def test_emit_github_output_appends_kv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out.txt"
    out.write_text("existing=value\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    emit_github_output("plugins_sha", "abc123")

    content = out.read_text(encoding="utf-8")
    assert "existing=value" in content
    assert "plugins_sha=abc123" in content


def test_emit_github_output_noop_when_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    emit_github_output("plugins_sha", "abc123")


def test_emit_github_output_rejects_newline() -> None:
    with pytest.raises(ValueError, match="newline"):
        emit_github_output("image_digest", "sha256:abc\nmalicious")
