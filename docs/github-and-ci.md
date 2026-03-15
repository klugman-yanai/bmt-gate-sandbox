# GitHub and CI

Single reference for communication flow, GitHub App permissions, Actions/CLI usage, and intended workflow output.

---

## Communication flow

`bmt-handoff.yml` validates handoff health only (trigger + VM handshake). Workflow success means handoff completed; failure means handoff failed. **BMT final outcome is VM-owned** and appears in PR checks/comments. This test repo uses `dummy-build-and-test.yml` (dummy/no-op build steps + runner artifact upload + BMT dispatch).

**Who owns what**

| Stage | Owner | Source of truth |
| --- | --- | --- |
| Build and dispatch | `dummy-build-and-test.yml` | Actions run result + BMT tail dispatch summary |
| Handoff (trigger + VM ack) | `bmt-handoff.yml` | Actions run result + handoff summary |
| BMT pending/final status | VM watcher | PR commit status (`BMT_STATUS_CONTEXT`) |
| Detailed run outcome | VM watcher | PR check run + PR comments |

**Current flow**

1. `dummy-build-and-test.yml` performs dummy/no-op CI steps, uploads runner artifacts, then dispatches `bmt-handoff.yml`.
2. `bmt-handoff.yml` prepares context, uploads runners, classifies path, and then: **04A Handoff Skip (No Legs)** when no supported uploaded legs exist, or **04B Handoff Run (Trigger + VM Ack)** when legs exist.
3. In run path, `bmt-handoff.yml` writes trigger, starts VM, waits for handshake ack, writes handoff summary, and exits.
4. VM resolves runtime support by convention files (`projects/<project>/bmt_manager.py` and `projects/<project>/bmt_jobs.json`) and writes authoritative handshake decisions.
5. VM processes accepted legs asynchronously and posts pending/final commit status + check run updates to the PR.
6. If PR is closed: before pickup, VM acknowledges trigger as skipped and exits without leg execution; during execution, VM stops before next leg, finalizes existing pending signals as cancelled (`check=neutral`, `status=error`), and skips PR comments.
7. If a newer commit arrives: older trigger SHA is superseded (`superseded_by_new_commit`); VM completes current leg, cancels remaining legs, finalizes old SHA signals, and does not promote pointers for the superseded run.

**What developers see**

| Scenario | What to look at |
| --- | --- |
| CI run success/failure | Dummy CI result + BMT handoff dispatch summary in workflow run. |
| Handoff success | Green `bmt-handoff.yml` run summary confirms VM acknowledged trigger. |
| Handoff failed (`no_runtime_supported_legs`) | VM acknowledged but accepted zero legs; gate fails with explicit reason. |
| BMT in progress/complete | PR **Checks** and PR **Comments** (VM-owned). |
| PR closed during/after handoff | Runtime trigger ack/status shows skipped/cancelled; no new PR comment. |
| New commit supersedes in-flight run | Older SHA run shows cancelled/superseded; gating continues on latest PR head SHA only. |

**Branch protection:** Require the commit status context named by `BMT_STATUS_CONTEXT` (default: `BMT Gate`). The gate is VM-owned status; `bmt-handoff.yml` run conclusion is a handoff signal, not final BMT verdict.

**Operational note:** If handoff succeeds but PR status does not move, debug VM auth/runtime in watcher logs and VM environment.

---

## GitHub App permissions

**Current implementation:** The VM posts a terminal gate commit status (`BMT Gate`) and runtime Check Run (`BMT Runtime`). PR comments are **not** implemented; the Issues/Pull requests permission is listed for when that feature is added.

**How to check current permissions**

```bash
# Option 1: env vars + private key path
export GITHUB_APP_TEST_ID="123456"
uv run python tools/gh_app_perms.py --private-key /path/to/your-app.private-key.pem

# Option 2: explicit app-id and key
uv run python tools/gh_app_perms.py --app-id 123456 --private-key /path/to/app.private-key.pem

# Only print the permissions object
uv run python tools/gh_app_perms.py --app-id 123456 --private-key /path/to/key.pem --jq .permissions
```

Canonical env names: `GITHUB_APP_*`; aliases `GH_APP_TEST_ID` / `GH_APP_PROD_ID` are also accepted. The script calls `GET https://api.github.com/app` with JWT auth. Repository/installation overrides: **Settings → GitHub Apps → Your App → Permissions and events**.

**Required permissions**

| Permission | Level | Why |
| --- | --- | --- |
| **Actions: Read and write** | Repository | CI uses repo secrets with `create-github-app-token` to call **workflow_dispatch** on `bmt-handoff.yml`. |
| **Commit statuses: Read and write** | Repository | bmt-handoff.yml failure paths; dummy-build-and-test trigger failure; VM for terminal gate context (`BMT Gate`). |
| **Checks: Read and write** | Repository | VM creates/updates Check Runs for live progress and final results. |
| **Issues: Read and write** (or **Pull requests: Read and write**) | Repository | Planned: PR comments. Not yet implemented. Workflow can post "Did not run" from failure-path jobs using `GITHUB_TOKEN`. |

**Workflows permission** — Not required for BMT. BMT triggers an existing workflow; it does not create or edit workflow files. Grant **Actions: Read and write**; leave **Workflows** unset unless the App edits workflow files.

**Who needs what**

- **Runners (GITHUB_TOKEN):** dummy-build-and-test trigger-bmt needs `statuses: write`, `issues: write`. bmt-handoff.yml jobs need `contents: read`, `id-token: write`, `statuses: write`, `actions: read`, `issues: write`. You can remove `checks: write` from bmt-handoff.yml; only the VM creates Check Runs.
- **VM (GitHub App installation token):** **Statuses** and **Checks** at minimum. **Issues** (or **Pull requests**) for when PR comments are added. VM does not trigger workflows or read repo contents from GitHub.

---

## Actions and CLI tools

Summary of workflow behavior and CLI usage. References: [GitHub Actions](https://docs.github.com/en/actions), [Checks API](https://docs.github.com/en/rest/checks/runs), [GitHub CLI](https://cli.github.com/manual/).

**GitHub Actions**

| Feature | Relevant to BMT |
| --- | --- |
| Job summary | Write to `$GITHUB_STEP_SUMMARY`; dummy-build-and-test and bmt-handoff.yml write dispatch/handoff summaries pointing users to PR checks/comments. |
| Re-run | Re-run all/failed/specific jobs (up to 30 days). Devs can re-run BMT from Actions tab. |
| Commit statuses | Branch protection requires `BMT_STATUS_CONTEXT`. Runtime progress via Check Run (`BMT_RUNTIME_CONTEXT`). |

**GitHub CLI**

| Command | Relevant to BMT |
| --- | --- |
| `gh run watch [run-id]` | Watch workflow until complete. Note: may require PAT with `checks:read`. |
| `gh run view [run-id]` | Run summary, `--log` / `--log-failed`, `--json` for scripting. |
| `gh pr checks [number\|branch]` | CI status for PR. **`--watch`** until checks finish; **`--web`** opens checks page. |

**Check Runs API (what the VM posts)**

- `output.title` — e.g. "BMT Progress: X/Y legs complete" / "BMT Complete: PASS|FAIL".
- `output.summary` — Markdown summary (progress table, final results).
- `output.text`, `output.annotations`, `output.images`, `actions` — Not used today; could add annotations or re-run actions later.

**Commit statuses:** Description limited to 140 characters (we truncate). Branch protection should require VM-owned `BMT_STATUS_CONTEXT`. See [Communication flow](#communication-flow) above for when we post status.

**Runtime retention:** Triggers/acks/status under `<runtime-root>/triggers/` are trimmed (e.g. `BMT_TRIGGER_METADATA_KEEP_RECENT`). Run triggers deleted when processing finishes. Snapshots: only `current.json`-referenced runs retained. Long-tail bucket history is intentionally not retained.

---

## Workflow output (intended UX)

**Note:** PR comments are **not** implemented. The VM posts commit status and a Check Run; the workflow posts job summaries. The intended UX below is the target once PR comments are added.

- **Setup** — Select VM, preflight, sync metadata, start VM. Prepare matrix and run context.
- **Upload** — Upload runner binaries to GCS per project.
- **Handshake** — Write trigger, wait for VM confirmation. Table: Project | BMT | Requested | Accepted.
- **Handoff** — Links to Checks tab and PR comment; later VM posts pass/fail, scores, logs. **Final** — BMT Gate status in branch protection must pass to merge.
