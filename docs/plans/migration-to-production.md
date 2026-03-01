# Migration Plan: BMT to Production Repo

## Overview

Enable BMT gating in `Kardome-org/core-main` with **only `.github/` changes**. The dev repo owns all infrastructure (VM, GCS, config) and the production repo downloads config from GCS at runtime.

---

## Architecture

```
Dev Repo ──syncs──▶ GCS Bucket ◀──downloads── Prod Repo CI
                         │
                         └──downloads──▶ VM (runs BMT)
```

**Key insight:** Prod repo has no `remote/` directory. CI downloads config from GCS where dev repo already syncs it.

---

## Dev Repo Changes

### 1. Add `dispatch-workflow` Command

Create `.github/scripts/ci/commands/dispatch_workflow.py`:

```python
"""Dispatch a workflow via GitHub API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import click


@click.command("dispatch-workflow")
@click.option("--workflow", required=True, help="Workflow filename (e.g., bmt.yml)")
@click.option("--ref", required=True, help="Git ref (e.g., refs/heads/dev)")
@click.option("--ci-run-id", required=True, help="CI workflow run ID")
@click.option("--head-sha", required=True, help="Head commit SHA")
@click.option("--head-branch", required=True, help="Head branch name")
@click.option("--head-event", required=True, help="Event type (push, pull_request_target)")
@click.option("--pr-number", default="", help="PR number (if applicable)")
@click.option("--token-env", default="GITHUB_APP_TOKEN", help="Env var containing token")
@click.option("--repository", default=None, help="Repository (owner/repo), defaults to GITHUB_REPOSITORY env")
def command(
    workflow: str,
    ref: str,
    ci_run_id: str,
    head_sha: str,
    head_branch: str,
    head_event: str,
    pr_number: str,
    token_env: str,
    repository: str | None,
) -> None:
    """Dispatch a workflow via GitHub API with BMT inputs."""
    token = os.environ.get(token_env, "")
    if not token:
        raise click.ClickException(f"Token not found in ${token_env}")
    
    repo = repository or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        raise click.ClickException("Repository not specified (use --repository or GITHUB_REPOSITORY)")
    
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    
    inputs = {
        "ci_run_id": ci_run_id,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "head_event": head_event,
    }
    if pr_number:
        inputs["pr_number"] = pr_number
    
    body = {"ref": ref, "inputs": inputs}
    
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 204:
                raise click.ClickException(f"Unexpected status: {resp.status}")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8") if exc.fp else ""
        raise click.ClickException(f"HTTP {exc.code}: {error_body}") from exc
    
    click.echo(f"::notice::Dispatched workflow {workflow} for run {ci_run_id}")
```

Register in `ci_driver.py`:

```python
from ci.commands.dispatch_workflow import command as dispatch_workflow_cmd

# Add to existing imports and command registrations
cli.add_command(dispatch_workflow_cmd)
```

### 2. Sync Config to GCS

```bash
just sync-remote
```

---

## Production Repo Changes

### 1. Files to Copy (16 files)

Copy from dev repo `.github/scripts/` to prod repo `.github/scripts/`:

```
.github/scripts/
├── ci_driver.py
├── ci/
│   ├── __init__.py
│   ├── models.py
│   ├── config.py
│   ├── github_output.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   └── gcloud_cli.py
│   └── commands/
│       ├── __init__.py
│       ├── dispatch_workflow.py
│       ├── job_matrix.py
│       ├── run_trigger.py
│       ├── start_vm.py
│       ├── upload_runner.py
│       ├── wait_handshake.py
│       └── verdict_gate.py
```

### 2. Create `.github/workflows/bmt.yml`

Copy from dev repo with these modifications:

**Add config download step before matrix:**

```yaml
- name: Download BMT config from GCS
  run: |
    mkdir -p /tmp/bmt-config
    ROOT="gs://${GCS_BUCKET}/code"

    gcloud storage cp "${ROOT}/bmt_projects.json" /tmp/bmt-config/ --quiet
    gcloud storage cp -r "${ROOT}/sk/config" /tmp/bmt-config/sk/ --quiet

    echo "BMT_CONFIG_ROOT=/tmp/bmt-config" >>"$GITHUB_ENV"
```

**Update commands to use `$BMT_CONFIG_ROOT`:**

```yaml
- name: Build BMT matrix
  run: |
    uv run python ./.github/scripts/ci_driver.py matrix \
      --config-root "$BMT_CONFIG_ROOT" \
      --project-filter "${BMT_PROJECTS:-}"
```

### 3. Modify `.github/workflows/build-and-test.yml`

Add this job after the `build` job:

```yaml
  trigger-bmt:
    name: Trigger BMT
    needs: build
    if: success()
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request_target.head.sha || github.sha }}

      - name: Generate GitHub App token
        id: app-token
        uses: actions/create-github-app-token@v2
        with:
          app-id: ${{ secrets.APP_ID }}
          private-key: ${{ secrets.PRIVATE_KEY }}
          permission-actions: write

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          python-version: "3.12"

      - name: Dispatch BMT workflow
        env:
          GITHUB_APP_TOKEN: ${{ steps.app-token.outputs.token }}
          GITHUB_REPOSITORY: ${{ github.repository }}
        run: |
          uv run python ./.github/scripts/ci_driver.py dispatch-workflow \
            --workflow bmt.yml \
            --ref "refs/heads/${{ github.event.pull_request_target.head.ref || github.ref_name }}" \
            --ci-run-id "${{ github.run_id }}" \
            --head-sha "${{ github.event.pull_request_target.head.sha || github.sha }}" \
            --head-branch "${{ github.event.pull_request_target.head.ref || github.ref_name }}" \
            --head-event "${{ github.event_name }}" \
            --pr-number "${{ github.event.pull_request.number || '' }}"
```

### 4. GitHub Settings

**Variables (Settings → Secrets and variables → Actions → Variables):**

| Variable | Value |
|----------|-------|
| `GCS_BUCKET` | `train-kws-202311-bmt-gate` |
| `GCP_WIF_PROVIDER` | `projects/416686035248/locations/global/workloadIdentityPools/bmt-gate-gha-dev/providers/github-oidc` |
| `GCP_SA_EMAIL` | `bmt-runner-sa@train-kws-202311.iam.gserviceaccount.com` |
| `GCP_ZONE` | `europe-west4-a` |
| `BMT_VM_NAME` | `bmt-performance-gate` |
| `BMT_STATUS_CONTEXT` | `BMT Gate` |
| `BMT_PROJECTS` | `all release runners` |

**Secrets (Settings → Secrets and variables → Actions → Secrets):**

| Secret | Notes |
|--------|-------|
| `APP_ID` | GitHub App ID |
| `PRIVATE_KEY` | GitHub App private key |

### 5. Branch Protection

Settings → Branches → Branch protection rules → Add rule for `dev`:

- [x] Require status checks to pass before merging
- [x] Require branches to be up to date before merging
- [x] Status checks: `BMT Gate`

---

## Execution Checklist

| Step | Action | Repo |
|------|--------|------|
| 1 | Create `dispatch_workflow.py` command | Dev |
| 2 | Register command in `ci_driver.py` | Dev |
| 3 | Run `just sync-remote` | Dev |
| 4 | Copy `.github/scripts/` (16 files) | Prod |
| 5 | Copy `.github/workflows/bmt.yml` | Prod |
| 6 | Add `trigger-bmt` job to `.github/workflows/build-and-test.yml` | Prod |
| 7 | Configure GitHub variables (8) | Prod |
| 8 | Configure GitHub secrets (2) | Prod |
| 9 | Configure branch protection | Prod |
| 10 | Test with PR to `dev` | Prod |

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Config from GCS, not `remote/` | Prod repo only needs `.github/` changes |
| `dispatch-workflow` command | Simplifies trigger job from ~40 lines to ~15 |
| Same VM for both repos | Multi-repo auth in `github_repos.json` handles this |
| `APP_ID` / `PRIVATE_KEY` secrets | Clean naming; no installation ID needed for CI |

---

## Notes

- The VM already has `GITHUB_APP_PROD_*` secrets in GCP Secret Manager for posting commit status
- The CI workflow uses `actions/create-github-app-token` which auto-discovers installation ID
- Code and runtime use fixed roots: `gs://<bucket>/code` and `gs://<bucket>/runtime`
