"""Assemble the production release package into .github-release/.

Pulls from two sources:
  - .github/          authoritative CI code (bmt package, actions, workflows)
  - scripts/release_templates/  files with no dev equivalent (trigger-ci.yml, actionlint.yaml)

Workflows in .github/workflows/ ship EXCEPT:
  - *-dev.yml files (dev-only; excluded by naming convention)
  - internal/ subdirectory in source (dev-only operational workflows; not copied into the bundle)

Release layout mirrors the repo: only **build-and-test.yml**, **bmt-handoff.yml**, and **clang-format-auto-fix.yml**
at **`.github-release/workflows/*.yml`**. Template workflows (**trigger-ci.yml**, **code-owner-enforcement.yml**, …)
ship under **`.github-release/workflows/internal/`**. The template **clang-format-auto-fix.yml** is skipped here because
the copy from `.github/workflows/` root is authoritative.

Run via: just release
CI / no local PEM: RELEASE_SKIP_SECRETS=1 or --skip-secrets
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from tools.repo.core_main_workflows import run_drift_check

REPO = Path(__file__).parent.parent
SRC = REPO / ".github"
TEMPLATES = Path(__file__).parent / "release_templates"
DEST = REPO / ".github-release"
SECRETS_SRC = REPO / "gcp" / "image" / "github" / "secrets"
PEM_NAME = "Kardome-org_core-main.pem"

EXCLUDE_ACTIONS = {"check-image-up-to-date"}
EXCLUDE_COPY = {"__pycache__", ".venv"}

# Authoritative clang-format lives at .github/workflows root; skip duplicate from templates/.
SKIP_TEMPLATE_WORKFLOWS = frozenset({"clang-format-auto-fix.yml"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _copy_tree(src: Path, dest: Path) -> None:
    for item in src.rglob("*"):
        if any(part in EXCLUDE_COPY for part in item.parts):
            continue
        if item.suffix == ".pyc":
            continue
        if item.is_file():
            _copy(item, dest / item.relative_to(src))


def _git_output(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _git_dirty() -> bool:
    out = _git_output(["status", "--porcelain"])
    return bool(out)


def _env_skip_secrets() -> bool:
    v = os.environ.get("RELEASE_SKIP_SECRETS", "").strip().lower()
    return v in ("1", "true", "yes")


def _iso_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _copy_root_release_workflows(workflows_dest: Path) -> None:
    for wf in sorted((SRC / "workflows").glob("*.yml")):
        if wf.stem.endswith("-dev"):
            continue
        _copy(wf, workflows_dest / wf.name)


def _copy_internal_template_workflows(internal_dest: Path) -> None:
    for wf in sorted((TEMPLATES / "workflows").glob("*.yml")):
        if wf.name in SKIP_TEMPLATE_WORKFLOWS:
            continue
        _copy(wf, internal_dest / wf.name)


def _copy_actions_bundle() -> None:
    for action_dir in sorted((SRC / "actions").iterdir()):
        if action_dir.name in EXCLUDE_ACTIONS:
            continue
        _copy(action_dir / "action.yml", DEST / "actions" / action_dir.name / "action.yml")


def _copy_bmt_package() -> None:
    _copy_tree(SRC / "bmt" / "ci", DEST / "bmt" / "ci")
    _copy(SRC / "bmt" / "pyproject.toml", DEST / "bmt" / "pyproject.toml")
    _copy(SRC / "bmt" / "uv.lock", DEST / "bmt" / "uv.lock")
    _copy(SRC / "bmt" / "config" / "README.md", DEST / "bmt" / "config" / "README.md")


def _copy_pem_or_exit(*, skip_secrets: bool) -> None:
    pem_src = SECRETS_SRC / PEM_NAME
    pem_dest = DEST / "bmt" / "config" / "secrets" / PEM_NAME
    if skip_secrets:
        print(
            "warning: skipping PEM copy (--skip-secrets or RELEASE_SKIP_SECRETS); "
            "use GitHub Secrets on the consumer repo instead of committing keys.",
            file=sys.stderr,
        )
        return
    if not pem_src.is_file():
        print(
            f"error: missing {pem_src}\n"
            "Place the GitHub App private key there for a full bundle, or run with "
            "--skip-secrets for CI/validation.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    _copy(pem_src, pem_dest)


def _write_provenance_and_manifest(*, skip_secrets: bool, workflows_dest: Path, internal_dest: Path) -> str:
    source_sha = _git_output(["rev-parse", "HEAD"]) or "unknown"
    source_ref = _git_output(["describe", "--tags", "--always"]) or "unknown"
    provenance = {
        "source_repo": str(REPO.name),
        "source_sha": source_sha,
        "source_ref": source_ref,
        "generated_at": _iso_timestamp(),
        "working_tree_dirty": _git_dirty(),
        "skip_secrets": skip_secrets,
    }
    (DEST / "bmt_release.json").write_text(json.dumps(provenance, indent=2) + "\n")

    workflow_paths = sorted(workflows_dest.glob("*.yml"))
    if internal_dest.is_dir():
        workflow_paths.extend(sorted(internal_dest.glob("*.yml")))
    workflow_names = sorted(p.name for p in workflow_paths)
    action_names = sorted(p.name for p in (DEST / "actions").iterdir())
    bmt_py_count = len(list((DEST / "bmt" / "ci").rglob("*.py")))

    pem_row = (
        "| `bmt/config/secrets/` PEM | *(omitted — use `--skip-secrets`)* |\n"
        if skip_secrets
        else f"| `bmt/config/secrets/{PEM_NAME}` | `gcp/image/github/secrets/` |\n"
    )

    manifest_body = (
        "# Release Package\n\n"
        "Generated by `just release`. **Do not edit manually.**\n\n"
        "## Provenance\n\n"
        f"| Field | Value |\n|-------|-------|\n"
        f"| `source_sha` | `{source_sha}` |\n"
        f"| `source_ref` | `{source_ref}` |\n"
        f"| `generated_at` | `{provenance['generated_at']}` |\n"
        f"| `working_tree_dirty` | `{provenance['working_tree_dirty']}` |\n"
        f"| `skip_secrets` | `{skip_secrets}` |\n\n"
        "Machine-readable: `bmt_release.json`.\n\n"
        "## Sources\n\n"
        "| Content | Source |\n"
        "|---------|--------|\n"
        "| `workflows/*.yml` | `.github/workflows/` root only (excl. `*-dev.yml`) |\n"
        "| `workflows/internal/*.yml` | `scripts/release_templates/workflows/*.yml` (excl. duplicate `clang-format-auto-fix.yml`) |\n"
        "| `actions/*/action.yml` | `.github/actions/` (`check-image-up-to-date` excluded) |\n"
        "| `bmt/ci/` | `.github/bmt/ci/` |\n"
        f"{pem_row}"
        "| `actionlint.yaml` | `scripts/release_templates/actionlint.yaml` |\n\n"
        "## Deploy\n\n"
        "Copy contents of `.github-release/` into `kardome/core-main/.github/` "
        "(see [.github/README.md](../.github/README.md) file-release checklist). "
        "Do **not** commit private keys to git on the consumer; use GitHub Secrets.\n"
    )
    (DEST / "RELEASE_MANIFEST.md").write_text(manifest_body)

    print(f"✓ Release package assembled → {DEST.relative_to(REPO)}/")
    print(f"  workflows : {len(workflow_names)} ({', '.join(workflow_names)})")
    print(f"  actions   : {len(action_names)}")
    print(f"  bmt/ci    : {bmt_py_count} .py files")
    print(f"  provenance: {source_sha[:12]}… → bmt_release.json")
    return source_sha


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def assemble(*, skip_secrets: bool) -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir()

    workflows_dest = DEST / "workflows"
    internal_dest = workflows_dest / "internal"

    _copy_root_release_workflows(workflows_dest)
    _copy_internal_template_workflows(internal_dest)
    _copy(TEMPLATES / "actionlint.yaml", DEST / "actionlint.yaml")
    _copy_actions_bundle()
    _copy_bmt_package()
    _copy_pem_or_exit(skip_secrets=skip_secrets)
    _write_provenance_and_manifest(
        skip_secrets=skip_secrets,
        workflows_dest=workflows_dest,
        internal_dest=internal_dest,
    )

    drift_rc = run_drift_check(DEST / "workflows", mode="release")
    if drift_rc != 0:
        raise SystemExit(drift_rc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble .github-release/ for core-main drop.")
    parser.add_argument(
        "--skip-secrets",
        action="store_true",
        help="Do not copy GitHub App PEM (for CI; consumer should use GitHub Secrets).",
    )
    args = parser.parse_args()
    skip = args.skip_secrets or _env_skip_secrets()
    assemble(skip_secrets=skip)


if __name__ == "__main__":
    main()
