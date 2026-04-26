# Developer workflow (without the full pipeline)

Use this when you care about **plugins**, **`kardome_runner`**, **scores**, or **logs** — not about wiring Actions → Workflows → Cloud Run.

## 1. Three layers (pick the shallowest that answers your question)

| Layer | What you touch | When to use it |
| ----- | ---------------- | -------------- |
| **A. Plugin + SDK** | `plugins/projects/<project>/plugin.py`, `tests/bmt/`, `bmt_sdk` types | Pure scoring/eval logic, fast unit tests |
| **B. Runtime on disk** | `runtime/execution.py`, `gcp/stage` or `plugins` as stage tree | One real leg: plan → task → coordinator, local logs under workspace |
| **C. Full cloud** | Handoff workflow, GCS `triggers/`, Cloud Run jobs | Production parity, WIF, bucket state |

Most day‑to‑day work stays in **A** or **B**. Treat **C** only when something is specific to dispatch, IAM, or cross‑job behavior.

## 2. Local full leg (layer B) — one command

From repo root, point the stage tree at your bucket mirror (usually **`gcp/stage`** after `just deploy` sync, or **`plugins`** while iterating):

```bash
export BMT_RUNTIME_ROOT="$PWD/gcp/stage"          # or: export BMT_STAGE_ROOT=…
export BMT_ACCEPTED_PROJECTS_JSON='["sk"]'       # restrict plan to these projects
export BMT_WORKFLOW_RUN_ID="local-dev-1"       # any label; used in plan paths

uv run --package bmt-runtime python -m runtime.entrypoint run-local local-dev-1 \
  --stage-root "$PWD/gcp/stage"
```

`run-local` builds a plan, runs every planned task leg, then runs the coordinator (same code paths as Cloud Run **plan / task / coordinator**, without Google Workflows).

**Common env vars** (all optional except you usually want `BMT_ACCEPTED_PROJECTS_JSON`):

| Variable | Role |
| -------- | ---- |
| `BMT_RUNTIME_ROOT` / `BMT_STAGE_ROOT` | Stage root (`plugins/`, `projects/`, `triggers/` layout) |
| `BMT_FRAMEWORK_WORKSPACE` | Writable workspace root (default: temp dir `bmt-framework`) |
| `BMT_ACCEPTED_PROJECTS_JSON` | JSON array of project slugs to include in the plan |
| `BMT_HEAD_SHA`, `BMT_HEAD_BRANCH`, `BMT_PR_NUMBER`, `BMT_RUN_CONTEXT` | Filled into the plan metadata (GitHub parity); safe to omit for local runs |

## 3. Stepwise debugging (same layer B)

When you want **one** leg or to re‑run after changing a plugin:

```bash
# 1) Emit plan JSON under triggers/plans/<id>.json
uv run --package bmt-runtime python -m runtime.entrypoint plan local-dev-1 --stage-root gcp/stage --allow-workspace-plugins

# 2) Run a single task index (profile standard|heavy, index from plan)
uv run --package bmt-runtime python -m runtime.entrypoint task local-dev-1 --task-profile standard --task-index 0 --stage-root gcp/stage

# 3) Aggregate summaries + optional GitHub reporting hooks
uv run --package bmt-runtime python -m runtime.entrypoint coordinator local-dev-1 --stage-root gcp/stage
```

Use `--allow-workspace-plugins` on **plan** when the plugin still lives under `plugins/projects/...` instead of a published digest layout.

## 4. Where logs and runner output go

- **Per‑leg workspace** (under `BMT_FRAMEWORK_WORKSPACE`, default system temp):  
  `<project>/<bmt_slug>/<run_id>/logs/` — anything the plugin writes next to the run.
- **Snapshots on the stage tree** (under `projects/<project>/results/<bmt_slug>/snapshots/<run_id>/`):  
  `latest.json`, `ci_verdict.json`, mirrored **`logs/`**, and **`case_digest.json`** when present (`runtime/entrypoint.py` → `_write_snapshot_artifacts`).
- **SK plugin / batch probe** (`AdaptiveKardomeExecutor` → `_run_batch_probe`): every invocation writes **full** capture to the leg **`logs/`** tree (mirrored into GCS snapshots):
  - `batch_probe.stdout.log` — batch command **stdout**
  - `batch_probe.stderr.log` — **stderr**
  - `batch_probe.meta.txt` — exit code, argv, cwd (on timeout, `status=timeout` instead)
- **Read them from the bucket** (replace `RUN_ID`, `false_rejects` / `false_alarms`):

  ```bash
  B="${GCS_BUCKET:?}"
  R="RUN_ID"   # e.g. 1234567890-false_rejects from latest.json / plan leg
  gcloud storage cat "gs://$B/projects/sk/results/false_rejects/snapshots/$R/logs/batch_probe.stdout.log"
  gcloud storage cat "gs://$B/projects/sk/results/false_rejects/snapshots/$R/logs/batch_probe.stderr.log"
  ```

  Per-case `kardome_runner` logs remain as `*.log` next to each WAV under the same `logs/` snapshot prefix.

For **stdout counters** and batch JSON paths, see `plugins/projects/sk/plugin.py` and **`docs/kardome_runner_SK_runtime.md`**.

## 5. Cloud runs (layer C) — “where is my run?”

You do **not** need the whole architecture doc to trace one correlation id:

1. **`workflow_run_id`** — almost always the GitHub **`github.run_id`** of the workflow that invoked handoff (see **`docs/bmt-async-handoff-trace.md`**).
2. **GCS** — `triggers/plans/<id>.json`, `triggers/summaries/<id>/<project>-<bmt_slug>.json`, then snapshots under `projects/.../results/.../snapshots/<run_id>/`.
3. **Logs** — GCP Console → Cloud Run **job** execution for `bmt-task-standard` / `bmt-task-heavy` / `bmt-control` (container stdout/stderr). Same code as local **`python -m runtime.main`** with `BMT_MODE=task` / `plan` / `coordinator`.

## 6. Plugin development (layer A → B)

1. **Contract**: implement `BmtPlugin` (`bmt_sdk`); see **`docs/adding-a-project.md`** for layout and publish flow.
2. **Fast feedback**: add or extend tests under **`tests/bmt/`** (existing SK scoring tests are a good template).
3. **Runner parity**: run **`run-local`** (section 2) with a real `kardome_runner` on a small WAV subset before relying on CI.

## 7. CI / PEX commands (optional)

`uv run kardome-bmt …` (`ci/` package) is aimed at **GitHub Actions** (matrix, handoff, dispatch). For “why did my runner fail?” you usually still want **layer B** or **Cloud Run logs** (section 5), not every `kardome-bmt` subcommand.
