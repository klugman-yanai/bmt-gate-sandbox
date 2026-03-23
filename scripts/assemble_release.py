"""Assemble the production release package into .github-release/.

Pulls from two sources:
  - .github/          authoritative CI code (bmt package, actions, workflows)
  - scripts/release_templates/  files with no dev equivalent (trigger-ci.yml, actionlint.yaml)

Workflows in .github/workflows/ ship verbatim EXCEPT:
  - *-dev.yml files (dev-only; excluded by naming convention)
  - ops/ subdirectory (dev-only operational workflows)

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def assemble(*, skip_secrets: bool) -> None:
    # 1. Clean destination
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir()

    # 2. Copy workflows: exclude *-dev.yml and ops/ subdirectory
    for wf in sorted((SRC / "workflows").glob("*.yml")):
        if wf.stem.endswith("-dev"):
            continue
        _copy(wf, DEST / "workflows" / wf.name)

    # 3. Copy workflow templates (production-specific files with no dev equivalent)
    for wf in sorted((TEMPLATES / "workflows").iterdir()):
        _copy(wf, DEST / "workflows" / wf.name)

    # 4. Copy actionlint config from templates
    _copy(TEMPLATES / "actionlint.yaml", DEST / "actionlint.yaml")

    # 5. Copy actions (exclude dev-only)
    for action_dir in sorted((SRC / "actions").iterdir()):
        if action_dir.name in EXCLUDE_ACTIONS:
            continue
        _copy(action_dir / "action.yml", DEST / "actions" / action_dir.name / "action.yml")

    # 6. Copy bmt package
    _copy_tree(SRC / "bmt" / "ci", DEST / "bmt" / "ci")
    _copy(SRC / "bmt" / "pyproject.toml", DEST / "bmt" / "pyproject.toml")
    _copy(SRC / "bmt" / "uv.lock", DEST / "bmt" / "uv.lock")
    _copy(SRC / "bmt" / "config" / "README.md", DEST / "bmt" / "config" / "README.md")

    # 7. Copy production GitHub App key (optional for CI)
    pem_src = SECRETS_SRC / PEM_NAME
    pem_dest = DEST / "bmt" / "config" / "secrets" / PEM_NAME
    if skip_secrets:
        print(
            "warning: skipping PEM copy (--skip-secrets or RELEASE_SKIP_SECRETS); "
            "use GitHub Secrets on the consumer repo instead of committing keys.",
            file=sys.stderr,
        )
    elif not pem_src.is_file():
        print(
            f"error: missing {pem_src}\n"
            "Place the GitHub App private key there for a full bundle, or run with "
            "--skip-secrets for CI/validation.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    else:
        _copy(pem_src, pem_dest)

    # 8. Provenance + manifest
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

    workflow_names = sorted(p.name for p in (DEST / "workflows").iterdir())
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
        "| `workflows/` | `.github/workflows/*.yml` (excl. `*-dev.yml`, `ops/`) + "
        "`scripts/release_templates/workflows/` |\n"
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
