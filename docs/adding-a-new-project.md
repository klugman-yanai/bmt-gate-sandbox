# Adding a new BMT project (full checklist)

Get a new project running on the VM and in CI. Do the steps **in order**. All paths and commands are exact.

---

## Checklist (do in order)

| # | Where | What |
|---|--------|------|
| 1 | bmt-gcloud | Scaffold project: `just add-project <project>`. |
| 2 | bmt-gcloud | Edit `gcp/image/projects/<project>/bmt_jobs.json` (paths, runner, gate, parsing). |
| 3 | bmt-gcloud | No code edit needed — the scaffold generates the manager. Edit `bmt_manager.py` only if you need custom gate or runner logic (see [adding-new-project-and-bmt.md](adding-new-project-and-bmt.md) §3). |
| 4 | bmt-gcloud | Validate: `uv run python tools/scripts/validate_bmt_jobs_schema.py`. Sync: `GCS_BUCKET=<bucket> just sync-gcp`. |
| 5 | App repo | Add CMake preset for the project; ensure the workflow uploads the runner with the correct PROJECT and PRESET. |
| 6 | App repo | Ensure `.github/bmt/` exists (copy from bmt-gcloud or run your one-time setup). |

No need to edit a “project list” anywhere — the layout policy finds projects by `*/bmt_manager.py` under `gcp/image/`.

---

## Step 1: Scaffold (bmt-gcloud)

**Command (from repo root):**

```bash
just add-project <project>
```

Example: `just add-project skyworth`.

**Creates:**

- `gcp/image/projects/<project>/bmt_manager.py`
- `gcp/image/projects/<project>/bmt_jobs.json` (one BMT with a generated UUID)

**Done when:** Both files exist. Next: edit the JSON.

---

## Step 2: Edit bmt_jobs.json (bmt-gcloud)

**File:** `gcp/image/projects/<project>/bmt_jobs.json`.

**You must set:**

| Field | Meaning | Example |
|-------|---------|---------|
| **paths.dataset_prefix** | GCS path where WAVs live | `skyworth/inputs/default` |
| **paths.outputs_prefix**, **results_prefix**, **logs_prefix** | GCS paths for outputs/results/logs | `skyworth/outputs/default`, etc. |
| **runner.uri** | GCS path to the runner binary | `skyworth/runners/skyworth_gcc_release/kardome_runner` |
| **template_uri** | Leave as `projects/shared/input_template.json` (all projects use the same template). | — |
| **gate** | Project-specific; all scoring/gate logic is in code. Schema allows optional **tolerance_abs**; no comparison logic in schema. | See existing BMTs or [adding-new-project-and-bmt.md](adding-new-project-and-bmt.md). |
| **parsing.counter_pattern** | Regex with **one** capture group for the score | `"Hi NAMUH counter = (\\d+)"` |
| **parsing** (optional) | **score_key**, **keyword** if your runner needs them | See `gcp/image/projects/sk/bmt_jobs.json` |

**Done when:** Paths point to where the app repo will upload the runner and where you will upload WAVs; gate and parsing match what your manager expects.

---

## Step 3: bmt_manager.py (bmt-gcloud) — usually no edit

The scaffold generates a full manager; **you do not edit** `bmt_manager.py` for standard projects.

**Only if** your project needs custom gate logic (e.g. thresholds, ratios) or custom runner behavior: edit `gcp/image/projects/<project>/bmt_manager.py`, subclass **BmtManagerBase** from `gcp.image.projects.shared.bmt_manager_base`, and override **_evaluate_gate** or **run_file** as needed. See `gcp/image/projects/sk/bmt_manager.py` (full) or `gcp/image/projects/skyworth/bmt_manager.py` (minimal).

**Done when:** You did not touch the file (standard), or your custom manager runs as expected.

---

## Step 4: Validate and sync (bmt-gcloud)

**Validate config:**

```bash
uv run python tools/scripts/validate_bmt_jobs_schema.py
```

Fix any reported errors.

**Sync to bucket:**

```bash
GCS_BUCKET=<bucket> just sync-gcp
```

**Done when:** Validation passes and sync completes. The bucket then has `projects/<project>/bmt_manager.py` and `projects/<project>/bmt_jobs.json`.

---

## Step 5: App repo — CMake preset and runner upload

- **Add a CMake preset** for the new project (e.g. `Skyworth_gcc_Release`). The BMT matrix is built from presets; each preset becomes a leg with **project** and **bmt_id**.
- **Runner upload:** The workflow step that uploads the runner uses **PROJECT** and **PRESET** (e.g. `PROJECT=skyworth`, `PRESET=skyworth_gcc_release`). It uploads the binary to the bucket at **`<project>/runners/<preset>/`** (e.g. `skyworth/runners/skyworth_gcc_release/`).
- **Match bmt_jobs.json:** **runner.uri** in `bmt_jobs.json` must match that path (e.g. `skyworth/runners/skyworth_gcc_release/kardome_runner`).

**Done when:** Build produces the runner and the workflow uploads it to the same path you set in **runner.uri**. The BMT workflow keeps only legs whose project was successfully uploaded.

---

## Step 6: App repo — .github/bmt/

The app repo (e.g. core-main) needs the **`.github/bmt/`** tree so that `uv run bmt matrix`, `bmt write-run-trigger`, etc. exist. Copy it from bmt-gcloud or run your one-time setup that creates/updates `.github/bmt/`.

**Done when:** In the app repo, `uv run bmt matrix` (or equivalent) runs and includes the new project when the runner has been uploaded.

---

## Summary

1. **bmt-gcloud:** Scaffold → edit `bmt_jobs.json` → (optional) edit `bmt_manager.py` → validate → sync.
2. **App repo:** Add preset and runner upload (PROJECT/PRESET) → ensure `.github/bmt/` exists.

For adding only a new BMT dataset, new WAVs, or JSON config, use [adding-new-project-and-bmt.md](adding-new-project-and-bmt.md).
