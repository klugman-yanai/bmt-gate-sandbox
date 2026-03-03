# GitHub Actions & GitHub CLI — reference for BMT

Summary of official docs and tools useful for BMT workflows, status/checks, and developer experience. All links and behavior are from [GitHub Actions](https://docs.github.com/en/actions), [GitHub REST API (Checks)](https://docs.github.com/en/rest/checks/runs), and [GitHub CLI](https://cli.github.com/manual/).

---

## GitHub Actions (workflow runs)

| Feature | What it does | Relevant to BMT |
|--------|----------------|------------------|
| **Job summary** | Write Markdown to `$GITHUB_STEP_SUMMARY`; it appears on the **Actions run summary** for that job. | `dummy-build-and-test.yml` BMT tail writes a dispatch-handoff summary; `bmt.yml` writes routing/trigger/handshake summaries. Both point users to PR checks/comments for final BMT outcome. |
| **Re-run** | Re-run all jobs, failed jobs only, or specific jobs (up to 30 days). Uses same SHA/ref. | Devs can re-run the BMT workflow from the Actions tab without pushing again. |
| **Workflow run logs** | Each run has logs per job/step. | Primary place for debugging when status says "Check Actions logs." |
| **Debug logging** | Enable runner diagnostic logging and step debug logging when re-running. | Useful when debugging handshake or runner upload failures. |
| **Commit statuses** | Workflows/apps can post status via API; branch protection can require a status. | BMT keeps merge gating in `BMT_STATUS_CONTEXT` (default `BMT Gate`). Runtime progress is shown via a separate check run in `BMT_RUNTIME_CONTEXT` (default `BMT Runtime`). |

---

## GitHub CLI — runs and checks (browser + terminal)

| Command | What it does | Relevant to BMT |
|---------|----------------|------------------|
| **`gh run watch [run-id]`** | Watch a workflow run until it completes; refreshes every 3s (or `-i N`). `--compact` shows only relevant/failed steps. `--exit-status` exits non-zero if run fails. | Devs can run `gh run watch <BMT_run_id>` to follow the BMT workflow from the terminal. Note: requires PAT with `checks:read` (not supported for fine-grained PATs per docs). |
| **`gh run view [run-id]`** | Show run summary. `--log` / `--log-failed` for logs; `-j JOB` for a job; `--json FIELD,...` for scripting; `-v` for verbose (steps). | Quick way to open run details and logs from CLI. |
| **`gh pr checks [number\|branch]`** | Show CI status for a PR. **`--watch`** watches until checks finish (interval 10s). **`--web`** opens the checks page in the browser. `--json` for scripting (includes `bucket`: pass/fail/pending/skipping/cancel). | Devs can run `gh pr checks --watch` on their branch to wait for BMT (and other checks) and `gh pr checks --web` to open the PR checks in the browser. |

Useful for docs and Justfile: tell devs they can **open the PR checks in the browser** with `gh pr checks --web` or by clicking the check in the PR, and **watch until done** with `gh pr checks --watch`.

---

## Check Runs API (what the VM posts)

The VM uses a **GitHub App** to create/update the runtime check run. The [Checks API](https://docs.github.com/en/rest/checks/runs) allows:

| Output field | Purpose | BMT use today |
|--------------|---------|----------------|
| **`output.title`** | Short title of the check output. | "BMT Progress: X/Y legs complete" / "BMT Complete: PASS\|FAIL". |
| **`output.summary`** | Markdown summary (what devs see when they open the check). | Progress table and final results table. |
| **`output.text`** | Optional longer text (e.g. raw logs). | Not used; could add failure log snippet for failed legs. |
| **`output.annotations`** | List of findings tied to files/lines: `path`, `annotation_level` (failure, warning, notice), `message`, optional `title`, `raw_details`, `start_line`, `end_line`. Shown in PR diff and check details. | Not used; could add one annotation per failed leg (e.g. a dummy path or "BMT leg sk/false_reject_namuh failed") to surface in the PR diff. |
| **`output.images`** | Array of `{ "alt": "...", "image_url": "https://..." }`. | Not used; could add a small status/chart image if we generate one. |
| **`actions`** | Optional list of `{ "label", "identifier", "description" }` for buttons (e.g. "Re-run"). Behavior is app-specific. | Not used. |

Only **GitHub Apps** can create/update check runs; OAuth/users have read-only. Our VM uses a GitHub App, so we can extend the check run with `text`, `annotations`, or `images` if we want richer in-browser feedback.

---

## Commit statuses API

- **Description** is limited to **140 characters** (we truncate in BMT).
- `BMT_RUNTIME_CONTEXT` names the VM-owned runtime check run (progress + terminal runtime outcome).
- `BMT_STATUS_CONTEXT` is used for terminal gate outcomes (`success`/`failure`/`error`).
- Used for the **merge gate**; check runs/runtime status are supplementary for detail.
- See `docs/communication-flow.md` for when we post status and what devs see.
- Branch protection should continue to require VM-owned `BMT_STATUS_CONTEXT`, not workflow run conclusion.

---

## Runtime retention policy (hard delete, no quarantine)

To keep bucket and VM filesystem usage bounded, runtime artifacts are pruned automatically:

- **Namespace:** runtime artifacts are under `<runtime-root> = gs://<bucket>/runtime`.
- **Snapshots:** for each BMT results prefix, only `current.json.latest` and `current.json.last_passing` snapshots are retained.
- **Trigger metadata:** `<runtime-root>/triggers/acks/*.json` and `<runtime-root>/triggers/status/*.json` are trimmed to the most recent entries; count is controlled by `BMT_TRIGGER_METADATA_KEEP_RECENT` (default `2`, i.e. current + previous).
- **Run triggers:** `<runtime-root>/triggers/runs/<workflow_run_id>.json` is deleted when processing finishes (or fails).
- **VM local workspace:** each project/BMT keeps only the newest two `run_*` directories.
- **Legacy history paths:** old archive/log history prefixes under `*/results/archive` and `*/results/logs/*` are removed by the watcher.

Primary debugging source remains GitHub workflow logs and Check Runs; long-tail bucket history is intentionally not retained.

---

## References

- [Re-running workflows and jobs](https://docs.github.com/en/actions/managing-workflow-runs/re-running-workflows-and-jobs)
- [Viewing workflow run history](https://docs.github.com/actions/managing-workflow-runs/viewing-workflow-run-history)
- [Using workflow run logs](https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/using-workflow-run-logs)
- [Job summaries](https://github.blog/2022-05-09-supercharging-github-actions-with-job-summaries/) (`$GITHUB_STEP_SUMMARY`)
- [REST API: Check runs](https://docs.github.com/en/rest/checks/runs)
- [GitHub CLI: gh run](https://cli.github.com/manual/gh_run), [gh run watch](https://cli.github.com/manual/gh_run_watch), [gh run view](https://cli.github.com/manual/gh_run_view)
- [GitHub CLI: gh pr checks](https://cli.github.com/manual/gh_pr_checks)
