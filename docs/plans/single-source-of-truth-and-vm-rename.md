# Single source of truth and gcp layout

## Job config: one place only

**Single source of truth for BMT job config is the VM mirror:** `gcp/image/projects/<project>/bmt_jobs.json`. That directory is synced to the bucket so the VM and orchestrator read the same files.

- **Do not** keep a second copy under `gcp/local/<project>/bmt_jobs.json`. `gcp/local/` is for **local-only** layout: runner dependencies (`dependencies/`), per-project `lib/` symlinks, and optional local inputs. Config that the VM uses lives only under `gcp/image/`.

**No brittle local paths in VM config.** Files under `gcp/image/` are synced to the bucket and may be baked into the image via Packer. They must not reference local repo paths (e.g. no `$schema` pointing at `schemas/`). The schema validator passes the schema explicitly; at runtime the VM loads JSON only.

## Where bmt_root_results.json lives

**`bmt_root_results.json` is a runtime artifact.** The root orchestrator writes it to the **GCS runtime bucket** (one object per run; fixed name in the bucket). It is not stored in the repo. A **versioned schema** lives in `gcp/image/schemas/bmt_root_results.schema.json` and is baked into the image for documentation and optional validation; all other runtime JSONs (manager_summary, ci_verdict, current.json, latest.json) have schemas in the same directory.

## bmt_jobs vs bmt_root_results: GCS vs VM filesystem

| File | Where it should live | Rationale |
|------|----------------------|-----------|
| **bmt_jobs.json** | **GCS** (bucket `code/`) | Config is the source of truth in the bucket; synced from repo (`gcp/image/`). At runtime the root orchestrator **downloads** it from GCS into the run workspace and passes the local path to the manager. Keeping it in GCS means config changes (gate, paths, new BMTs) take effect after `just sync-gcp` and do not require rebuilding the Packer image. The image may contain a snapshot of `code/` at bake time, but the orchestrator deliberately fetches from GCS so each run uses the latest config. |
| **bmt_root_results.json** | **GCS** (runtime bucket) only | It is **output** of the root orchestrator (per-run summary). Written to GCS so CI and other consumers can read it. The VM writes it locally only as a staging step before upload; it does not need to persist on the VM filesystem. |

So: both are **GCS-backed**. The VM filesystem (Packer image) holds code and venv; config (bmt_jobs) is read from GCS at runtime, and run results (bmt_root_results) are written to GCS.

## What to put in GCS so the image won’t often require rebuilds

At runtime the watcher **downloads** `root_orchestrator.py` from GCS, and the orchestrator **downloads** each leg’s manager and `bmt_jobs.json` from GCS. So those artifacts are always taken from the bucket, not from the baked image. The image only needs to provide the watcher, lib, config (e.g. GitHub repos), and vm scripts.

**Keep these in GCS** (sync from `gcp/image/` with `just sync-gcp`) so that changes do **not** require an image rebuild:

| In bucket `code/` | Purpose |
|-------------------|--------|
| `root_orchestrator.py` | Downloaded by the watcher before each run. |
| `<project>/bmt_manager.py` | Downloaded by the orchestrator per leg. **New project = add file + sync; no image rebuild.** |
| `projects/<project>/bmt_jobs.json` | Downloaded by the orchestrator per leg. Gate/paths/new BMTs: edit and sync. |
| `projects/shared/input_template.json` | Fetched by the manager from the bucket when needed (single shared template). |
| Runner binaries (e.g. under `runtime/`) | Uploaded by CI; managers download at runtime. |

**These force an image rebuild** when changed (image-affecting paths: `infra/packer/**`, `gcp/image/**`):

| What | Why |
|------|-----|
| **Packer template** (`infra/packer/**`) | Image build definition. |
| **VM scripts** (`gcp/image/vm/**`) | `run_watcher.sh`, `startup_entrypoint.sh`, `install_deps.sh`, `vm_deps.txt`, `shared.sh`, etc. Run from the image at boot. |
| **Watcher and shared code** | `vm_watcher.py`, `lib/`, `config/` (e.g. `github_repos.json`) are currently baked; the watcher runs from the image. Changing them requires a new image until/unless we move to “download watcher from GCS at startup”. |

So: **new BMT or new project** (new manager script, new or updated `bmt_jobs.json`, new runner) → sync (and upload runners) to GCS only; **no image rebuild**. Changes to watcher, vm scripts, or Packer → **image rebuild required**.

## gcp layout

The code mirror is **`gcp/image/`** (VM-side code and config), synced to bucket `code/`. The **bucket prefix** for that content is `code` (i.e. we sync `gcp/image/` → `gs://bucket/code/`).

Resulting layout:

- **`gcp/image/`** — VM code and config; synced to bucket `code/`. Single source of truth for `bmt_jobs.json`, managers, and VM scripts.
- **`gcp/local/`** — Local BMT layout only: deps, per-project lib symlinks, optional inputs. No duplicate job config.
- **`gcp/remote/`** — Runtime seed (if any) for the bucket.
