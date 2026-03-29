"""Workflow hardening and simplification guardrails for .github/**."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.repo.paths import repo_root

# `uses: ./.github/actions/my-action` or `uses: ./.github/actions/org/nested`
_LOCAL_COMPOSITE_USES = re.compile(
    r"^\s*uses:\s+\./\.github/actions/([^@\s#]+)",
    re.MULTILINE,
)

pytestmark = pytest.mark.unit


def test_reusable_workflow_calls_do_not_inherit_secrets() -> None:
    build_workflow = (repo_root() / ".github" / "workflows" / "build-and-test.yml").read_text(encoding="utf-8")
    build_dev = (repo_root() / ".github" / "workflows" / "build-and-test-dev.yml").read_text(encoding="utf-8")
    dispatch = (repo_root() / ".github" / "workflows" / "internal" / "trigger-ci-dispatch.yml").read_text(
        encoding="utf-8"
    )

    assert "secrets: inherit" not in build_workflow
    assert "secrets: inherit" not in build_dev
    assert "secrets: inherit" not in dispatch
    # Thin root `trigger-ci.yml` matches the release template: caller uses `secrets: inherit`.


def test_workflow_permissions_are_minimal_for_current_steps() -> None:
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")
    trigger_ci = (repo_root() / ".github" / "workflows" / "trigger-ci.yml").read_text(encoding="utf-8")
    dispatch = (repo_root() / ".github" / "workflows" / "internal" / "trigger-ci-dispatch.yml").read_text(
        encoding="utf-8"
    )

    assert "  dispatch:" in handoff
    assert "statuses: write" in handoff
    assert "      contents: read" in handoff
    assert "      actions: write" not in handoff

    # Push trigger: build-only, minimal permissions
    assert "uses: ./.github/workflows/build-and-test-dev.yml" in trigger_ci
    assert "permissions:" in trigger_ci
    assert "  contents: read" in trigger_ci
    assert "  actions: write" in trigger_ci
    assert "  id-token: write" not in trigger_ci
    assert "  statuses: write" not in trigger_ci

    # PR trigger: full pipeline with handoff permissions (inline build matrices + shared checkout action)
    trigger_ci_pr = (repo_root() / ".github" / "workflows" / "trigger-ci-pr.yml").read_text(encoding="utf-8")
    assert "uses: ./.github/actions/dev/checkout-presets" in trigger_ci_pr
    assert "uses: ./.github/workflows/bmt-handoff.yml" in trigger_ci_pr
    assert "  id-token: write" in trigger_ci_pr
    assert "  statuses: write" in trigger_ci_pr
    assert "  pull-requests: read" in trigger_ci_pr

    assert "permissions:" in dispatch
    assert "  actions: write" in dispatch
    assert "GH_TOKEN: ${{ github.token }}" in dispatch
    assert 'gh workflow run "$workflow_file"' in dispatch
    assert "build-and-test-dev.yml" in dispatch


def test_handoff_uses_direct_workflow_dispatch_not_gcs_eventarc() -> None:
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")

    assert "invoke-workflow" in handoff
    assert "write-run-trigger" not in handoff
    assert "gcloud workflows executions list" not in handoff
    assert "gcloud storage cat" not in handoff


def test_handoff_dispatch_keeps_publish_omitted_notice_only_and_sparse_checkout_avoids_stale_gcp_root() -> None:
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")

    assert "needs: [plan, publish]" in handoff
    assert "publish_omitted is intentionally notice-only" in handoff
    assert "dispatch excludes it from gating" in handoff
    assert "needs['publish_omitted'].result == 'success'" not in handoff
    assert "needs['publish_omitted'].result == 'skipped'" not in handoff
    assert "bmt_recovery_used" in handoff
    assert "bmt_dispatch_fallback_used" in handoff
    assert "\n            gcp\n" not in handoff


def test_handoff_does_not_use_ci_side_github_reporting() -> None:
    """CI does not post pending status or Check Runs — Cloud Run runtime handles all reporting.

    GitHub App credentials live in GCP Secrets Manager; they must not be injected as
    GitHub repo secrets into the handoff workflow.
    """
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")

    assert "bmt-start-runtime-reporting" not in handoff
    assert "secrets.BMT_GITHUB_APP_ID" not in handoff
    assert "secrets.BMT_GITHUB_APP_DEV_ID" not in handoff
    assert not (repo_root() / ".github" / "actions" / "bmt-start-runtime-reporting").exists()


def test_external_actions_are_sha_pinned_in_hardened_workflows() -> None:
    build_test = (repo_root() / ".github" / "workflows" / "build-and-test.yml").read_text(encoding="utf-8")
    build_dev = (repo_root() / ".github" / "workflows" / "build-and-test-dev.yml").read_text(encoding="utf-8")
    clang_format = (repo_root() / ".github" / "workflows" / "clang-format-auto-fix.yml").read_text(encoding="utf-8")
    image_build = (repo_root() / ".github" / "workflows" / "internal" / "bmt-image-build.yml").read_text(
        encoding="utf-8"
    )
    setup_uv_repo = (repo_root() / ".github" / "actions" / "setup" / "uv-repo" / "action.yml").read_text(
        encoding="utf-8"
    )
    upload_artifact_repo = (repo_root() / ".github" / "actions" / "artifacts" / "upload-repo" / "action.yml").read_text(
        encoding="utf-8"
    )
    download_artifact_repo = (
        repo_root() / ".github" / "actions" / "artifacts" / "download-repo" / "action.yml"
    ).read_text(encoding="utf-8")
    cache_repo = (repo_root() / ".github" / "actions" / "setup" / "cache-repo" / "action.yml").read_text(
        encoding="utf-8"
    )
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v4" not in build_test
    assert "actions/checkout@v4" not in clang_format
    assert "actions/cache@" not in build_test
    assert "actions/cache@" not in handoff
    assert "hashicorp/setup-packer@1aa358be5cf73883762b302a3a03abd66e75b232" in image_build
    assert "astral-sh/setup-uv@" not in build_test
    assert "uses: astral-sh/setup-uv@65ef90775fa85bf7130e46f3f22dc79a206581c8" in setup_uv_repo
    assert "actions/upload-artifact@" not in build_test
    assert "actions/upload-artifact@" not in image_build
    assert "uses: actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f" in upload_artifact_repo
    assert "uses: actions/download-artifact@634f93cb2916e3fdff6788551b99b062d0335ce0" in download_artifact_repo
    pin = "uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
    assert pin in build_test
    assert pin in build_dev
    assert pin in handoff
    assert pin in clang_format
    assert pin in image_build
    assert "uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830" in cache_repo
    assert "actions/cache@" not in handoff


def test_unused_bmt_runner_env_action_is_removed() -> None:
    assert not (repo_root() / ".github" / "actions" / "bmt-runner-env").exists()
    assert not (repo_root() / ".github" / "actions" / "checkout-repo-head").exists()


def test_local_composite_action_paths_resolve() -> None:
    """Every `uses: ./.github/actions/...` reference must have a matching action.yml on disk."""
    github = repo_root() / ".github"
    missing: list[str] = []
    for path in sorted(_github_yaml_files(github)):
        text = path.read_text(encoding="utf-8")
        for rel_raw in _LOCAL_COMPOSITE_USES.findall(text):
            rel = rel_raw.strip().rstrip("/")
            action_yml = github / "actions" / rel / "action.yml"
            if not action_yml.is_file():
                missing.append(
                    f"{path.relative_to(repo_root())}: uses …/{rel} → missing {action_yml.relative_to(repo_root())}"
                )
    assert not missing, "Broken local action references:\n" + "\n".join(missing)


def _github_yaml_files(github_dir: Path) -> list[Path]:
    out: list[Path] = []
    for pattern in ("*.yml", "*.yaml"):
        out.extend(github_dir.rglob(pattern))
    return out
