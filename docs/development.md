# Development

This repo maintains one **supported production path**:

- GitHub Actions invokes **Google Workflows** directly.
- Workflows runs **`bmt-control`** (plan + coordinator) and **`bmt-task-standard`** / **`bmt-task-heavy`** (one leg per task).
- The runtime entrypoint is [`gcp/image/main.py`](../gcp/image/main.py), dispatching into [`gcp/image/runtime/`](../gcp/image/runtime/).

For **production incidents** (stuck checks, GCS inspection), see **[runbook.md](runbook.md)** — this page is for **contributor** local workflows.

## Local layout

- [`gcp/image`](../gcp/image) — Image-baked framework and runtime
- [`gcp/stage`](../gcp/stage) — Editable staged mirror of bucket manifests, plugins, assets
- [`gcp/mnt`](../gcp/mnt) — Optional read-only bucket mount for inspection
- Dataset archives may live anywhere; `just upload-data` takes an explicit path

## Common commands

- `just add-project <project>`
- `just add-bmt <project> <bmt_slug>`
- `just publish-bmt <project> <bmt_slug>`
- `just upload-data <project> <source> [--dataset <name>]`
- `just mount-project <project>` / `just umount-project <project>`

## Dataset upload (`just upload-data`)

**Entry:** `just upload-data` → [`tools/remote/bucket_upload_dataset.py`](../tools/remote/bucket_upload_dataset.py) (`BucketUploadDataset`).

- **Archives (zip):** Large or unbounded archives should use the **Cloud Run dataset-import** path (server-side extraction in `gcp/image/runtime/`). Set **`GCP_PROJECT`**, **`CLOUD_RUN_REGION`**, and **`BMT_CONTROL_JOB`** (and related vars your environment uses) so the import job can run. If those are missing, the tool should **fail fast** with a message to extract the archive locally and pass a **directory**, or to configure Cloud Run.
- **Directories:** Sync uses **`gcloud storage`** (rsync-style); you should see **native gcloud progress** on a TTY when implemented.
- **Pre-flight / completion:** The uploader may print a **pre-flight** summary (source stats, destination URI, mode: cloud-import vs rsync) and a **completion** summary after success.

## Verification

After changing tools or CI:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run python -m pytest tests/ -q
```

Focused subset while iterating:

```bash
uv run python -m pytest tests/bmt tests/ci tests/infra tests/tools -q
```

**Smoke (optional):**

- `uv run bmt write-context --help` and `write-handoff-summary --help` when touching handoff
- `uv run python -m tools repo show-env` and `uv run python -m tools repo validate`

**E2E / mock handoff:** See **[plans/2026-03-22-e2e-ci-validation.md](plans/2026-03-22-e2e-ci-validation.md)** (`gh workflow run bmt-handoff.yml` with `use_mock_runner=true` where applicable).

## Integration boundary (mental model)

1. Publish staged plugin bundle
2. Upload dataset (`just upload-data`)
3. Invoke Workflow (CI or manual)
4. Workflow writes `triggers/plans/<workflow_run_id>.json`
5. Task jobs write `triggers/summaries/<workflow_run_id>/...`
6. Coordinator writes snapshots and `current.json` under each leg’s results prefix

## Troubleshooting (contributor)

- **Layout / policy:** `just test` (gcp + repo layout policies)
- **Bucket out of sync:** `just deploy` before committing `gcp/` changes (or `SKIP_SYNC_VERIFY=1` to bypass pre-commit)
- **Repo vars vs Pulumi:** `just validate`, [configuration.md](configuration.md)

Large refactors may touch `gcp/image/runtime/github_reporting.py`, `entrypoint.py`, `.github/bmt/ci/handoff.py`, or `tools/repo/gh_repo_vars.py` — follow the PR description and team plans.

## Cloud Run job testing

Exercise the same runtime paths the VM image uses: see sections in this file and [configuration.md](configuration.md) for required env. For full **production CI locally** with real GCS, see the historical sections in [CONTRIBUTING](../CONTRIBUTING.md) and the **Testing** section of [CLAUDE.md](../CLAUDE.md) (pointer/snapshot flow with a real bucket).
