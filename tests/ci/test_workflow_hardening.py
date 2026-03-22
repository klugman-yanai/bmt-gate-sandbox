"""Workflow hardening and simplification guardrails for .github/**."""

from __future__ import annotations

from tools.repo.paths import repo_root


def test_reusable_workflow_calls_do_not_inherit_secrets() -> None:
    build_workflow = (repo_root() / ".github" / "workflows" / "build-and-test.yml").read_text(encoding="utf-8")
    trigger_ci = (repo_root() / ".github" / "workflows" / "ops" / "trigger-ci.yml").read_text(encoding="utf-8")

    assert "secrets: inherit" not in build_workflow
    assert "secrets: inherit" not in trigger_ci


def test_workflow_permissions_are_minimal_for_current_steps() -> None:
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")
    trigger_ci = (repo_root() / ".github" / "workflows" / "ops" / "trigger-ci.yml").read_text(encoding="utf-8")

    assert "confirm_cloud_job_start:" in handoff
    assert "statuses: write" in handoff
    assert "      contents: read" in handoff
    assert "      actions: write" not in handoff

    assert "permissions:" in trigger_ci
    assert "  actions: write" in trigger_ci
    assert "  id-token: write" not in trigger_ci
    assert "  statuses: write" not in trigger_ci
    assert "GH_TOKEN: ${{ github.token }}" in trigger_ci
    assert 'gh workflow run "$workflow_file"' in trigger_ci


def test_handoff_uses_direct_workflow_dispatch_not_gcs_eventarc() -> None:
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")

    assert "invoke-workflow" in handoff
    assert "write-run-trigger" not in handoff
    assert "gcloud workflows executions list" not in handoff
    assert "gcloud storage cat" not in handoff


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
    clang_format = (repo_root() / ".github" / "workflows" / "clang-format-auto-fix.yml").read_text(encoding="utf-8")
    image_build = (repo_root() / ".github" / "workflows" / "ops" / "bmt-image-build.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v4" not in clang_format
    assert "uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in clang_format
    assert "uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in image_build
    assert "hashicorp/setup-packer@54678572a9eae3130016b4548482317e9f83f9f3" in image_build


def test_unused_bmt_runner_env_action_is_removed() -> None:
    assert not (repo_root() / ".github" / "actions" / "bmt-runner-env").exists()
