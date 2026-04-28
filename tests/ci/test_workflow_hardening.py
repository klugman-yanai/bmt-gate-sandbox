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
# `uses: ../sibling-action` from `.github/actions/<dir>/action.yml` → `.github/actions/sibling-action`
_ACTION_REL_SIBLING_USES = re.compile(
    r"^\s*uses:\s+\.\./([^@\s#]+)",
    re.MULTILINE,
)

pytestmark = pytest.mark.unit


def test_reusable_workflow_calls_do_not_inherit_secrets() -> None:
    build_workflow = (repo_root() / ".github" / "workflows" / "build-and-test.yml").read_text(encoding="utf-8")
    trigger_ci = (repo_root() / ".github" / "workflows" / "internal" / "trigger-ci.yml").read_text(encoding="utf-8")

    assert "secrets: inherit" not in build_workflow
    assert "secrets: inherit" not in trigger_ci


def test_workflow_permissions_are_minimal_for_current_steps() -> None:
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")
    trigger_ci = (repo_root() / ".github" / "workflows" / "internal" / "trigger-ci.yml").read_text(encoding="utf-8")

    assert "start_bmt_workflow:" in handoff
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


def test_dev_ci_workflow_does_not_publish_placeholder_runner_artifacts() -> None:
    """Self-CI (build-and-test-dev.yml) uses placeholder build legs and must not upload runner artifacts.

    This workflow now handles both push and pull_request events (trigger-ci-pr.yml was
    removed). Real runner artifacts come from core-main's build-and-test.yml.
    """
    dev_ci = (repo_root() / ".github" / "workflows" / "build-and-test-dev.yml").read_text(encoding="utf-8")

    assert "Release build placeholder (bmt-gcloud)" in dev_ci
    assert "preset stage-release-runner" not in dev_ci
    assert "preset compute-info" not in dev_ci
    assert "Upload runner artifact for handoff" not in dev_ci
    assert ".github/actions/artifacts/upload-repo" not in dev_ci


def test_external_actions_are_sha_pinned_in_hardened_workflows() -> None:
    build_test = (repo_root() / ".github" / "workflows" / "build-and-test.yml").read_text(encoding="utf-8")
    clang_format = (repo_root() / ".github" / "workflows" / "clang-format-auto-fix.yml").read_text(encoding="utf-8")
    image_build = (repo_root() / ".github" / "workflows" / "internal" / "bmt-image-build.yml").read_text(
        encoding="utf-8"
    )

    assert "actions/checkout@v4" not in build_test
    assert "actions/checkout@v4" not in clang_format
    assert "uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in clang_format
    assert "uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in image_build
    assert "hashicorp/setup-packer@1aa358be5cf73883762b302a3a03abd66e75b232" in image_build


def test_unused_bmt_runner_env_action_is_removed() -> None:
    assert not (repo_root() / ".github" / "actions" / "bmt-runner-env").exists()


def test_handoff_declares_opt_in_release_marker_verification() -> None:
    """Phase B.3 of the CI-driven release plan: Plan job must verify the release
    marker before dispatching cloud work, but only when the caller opts in via
    the ``release_git_sha`` input.

    Guards against three regressions at once:

    1. The input is declared on BOTH ``workflow_dispatch`` and ``workflow_call``
       (cross-repo callers invoke via ``workflow_call``; same-repo debug via
       ``workflow_dispatch``).
    2. The verify step is guarded by ``if: … != ''`` so cross-repo callers that
       don't pass the input keep today's behaviour (they rely on a pinned
       reusable-workflow ``@ref``, not our bucket marker).
    3. The step runs BEFORE ``steps.filter`` — a stale marker must short-circuit
       the matrix build, not race it.
    """
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")

    assert handoff.count("release_git_sha:") == 2, (
        "expected `release_git_sha:` declared in BOTH workflow_dispatch.inputs and workflow_call.inputs; "
        "found " + str(handoff.count("release_git_sha:"))
    )

    assert "Verify release marker" in handoff
    assert "release verify" in handoff
    assert "(inputs.release_git_sha || github.event.inputs.release_git_sha) != ''" in handoff

    verify_idx = handoff.index("Verify release marker")
    filter_idx = handoff.index("- id: filter")
    assert verify_idx < filter_idx, (
        "Verify step must precede the filter step so stale markers short-circuit the matrix."
    )


def test_handoff_uses_repo_qualified_composite_actions() -> None:
    """Cross-repo callers must resolve composites from klugman-yanai/bmt-gcloud@tag (literal ``uses:``)."""
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")
    assert "klugman-yanai/bmt-gcloud/.github/actions/setup-bmt-pex@" in handoff
    assert "uses: ./.github/actions/setup-bmt-pex" not in handoff


def test_handoff_resolves_caller_context_when_inputs_omitted() -> None:
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")
    assert "BMT_RESOLVED_CI_RUN_ID:" in handoff
    assert "github.run_id" in handoff
    assert "Require ci_run_id for direct workflow_dispatch" in handoff


def test_handoff_declares_force_pass_on_both_triggers() -> None:
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")
    n = handoff.count("force_pass:")
    assert n == 2, (
        f"expected `force_pass:` declared in BOTH workflow_dispatch.inputs and workflow_call.inputs; found {n}"
    )


def test_handoff_declares_bmt_pex_repo_on_both_triggers() -> None:
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")
    n = handoff.count("bmt_pex_repo:")
    assert n >= 2, (
        "expected `bmt_pex_repo` input in workflow_dispatch and workflow_call (plus optional step `with:`); "
        f"found {n} occurrences"
    )


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
        if "/actions/" in str(path) and path.name == "action.yml":
            for sibling in _ACTION_REL_SIBLING_USES.findall(text):
                name = sibling.strip().rstrip("/")
                action_yml = github / "actions" / name / "action.yml"
                if not action_yml.is_file():
                    missing.append(
                        f"{path.relative_to(repo_root())}: uses ../{name} → missing "
                        f"{action_yml.relative_to(repo_root())}"
                    )
    assert not missing, "Broken local action references:\n" + "\n".join(missing)


def _github_yaml_files(github_dir: Path) -> list[Path]:
    out: list[Path] = []
    for pattern in ("*.yml", "*.yaml"):
        out.extend(github_dir.rglob(pattern))
    return out
