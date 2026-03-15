# Adding a project, BMT data, manager logic, and JSON config

Step-by-step. Do each section in order when that’s what you need. No prior knowledge assumed.

---

## 1. Add a new project

**Goal:** New project runs on the VM and appears in the matrix. Everything lives under `gcp/image/projects/<project>/`.

| Step | Do this | Done when |
|------|--------|-----------|
| 1 | From repo root: `just add-project <project>` (e.g. `just add-project skyworth`). | You have `gcp/image/projects/<project>/bmt_manager.py` and `gcp/image/projects/<project>/bmt_jobs.json`. |
| 2 | Edit **`gcp/image/projects/<project>/bmt_jobs.json`**. Set **paths** to your GCS segments: `dataset_prefix`, `outputs_prefix`, `results_prefix`, `logs_prefix` (e.g. `skyworth/inputs/default`, `skyworth/results/default`). | Paths match where you will put data and results in the bucket. |
| 3 | In the same file set **runner.uri** to the GCS path of the runner binary (e.g. `skyworth/runners/skyworth_gcc_release/kardome_runner`). | Runner URI matches where the app-repo workflow uploads the binary. |
| 4 | Leave **template_uri** as `projects/shared/input_template.json` (all projects use the shared template). | No change needed. |
| 5 | Set **gate** to whatever your project’s pass/fail rule needs. All scoring/gate logic is in code (manager’s _evaluate_gate); the schema only allows optional fields like **tolerance_abs**. | Gate block is present; manager implements pass/fail in code. |
| 6 | Set **parsing**: `counter_pattern` to a regex with **one** capture group for the numeric score (e.g. `"Hi NAMUH counter = (\\d+)"`). Set `score_key` or `keyword` if your runner needs it. | Parsing matches the runner’s stdout. |
| 7 | From repo root: `GCS_BUCKET=<bucket> just deploy`. | Sync finishes without errors. |

**Manager logic is automated:** The scaffold generates a full manager; you do **not** edit `bmt_manager.py` for standard projects. Only edit it when you need custom gate or runner behavior (see §3).

---

## 2. Add new BMT .wav data (new dataset or new BMT)

**Goal:** A new BMT (new dataset or new gate) runs with its own WAVs in GCS.

| Step | Do this | Done when |
|------|--------|-----------|
| 1 | Open **`gcp/image/projects/<project>/bmt_jobs.json`**. Under **bmts**, add a **new key** (the BMT id). Use a **stable UUID** (e.g. generate once: `uuid5(NAMESPACE_DNS, "bmt-gcloud.<project>.<name>")`). | New entry exists under `bmts` with a unique id. |
| 2 | In that entry set **enabled**, **paths** (including **dataset_prefix** = GCS path where WAVs will live, e.g. `sk/inputs/false_alarms`), **runner**, **gate**, **parsing**. Copy shape from an existing BMT in the same file. | All required fields are set; **dataset_prefix** is the path you will upload to. |
| 3 | Put your WAVs in a **local directory** (e.g. `data/<project>/inputs/false_alarms/`). Do **not** commit large WAV trees. | You have a local folder of `.wav` files. |
| 4 | Upload to GCS. From repo root: `GCS_BUCKET=<bucket> uv run python -m tools.remote.bucket_upload_wavs --source-dir <local_dir> --dest-prefix <dataset_prefix>`. Use the **same** `dataset_prefix` as in step 2 (e.g. `--dest-prefix sk/inputs/false_alarms`). | Files appear under `gs://<bucket>/<dataset_prefix>/`. |

**Rule:** `--dest-prefix` must **exactly** match **paths.dataset_prefix** in `bmt_jobs.json` for that BMT.

---

## 3. Manager logic (automated; customize only when needed)

**Default:** The scaffold generates a complete manager. You do **not** edit `bmt_manager.py` for standard projects — config in `bmt_jobs.json` drives paths, runner, and parsing; gate logic is entirely in code.

**When to edit:** Only when your project needs **custom gate logic** (e.g. thresholds, ratios, multi-metric) or **custom runner behavior**. Then edit `gcp/image/projects/<project>/bmt_manager.py`: override **_evaluate_gate** for custom pass/fail, or **run_file** for different invocation/scoring. Subclass from `gcp.image.projects.shared.bmt_manager_base`; see `gcp/image/projects/sk/bmt_manager.py` (full) or `gcp/image/projects/skyworth/bmt_manager.py` (minimal).

---

## 4. Configure JSONs

**bmt_jobs.json (required)**

- **Path:** `gcp/image/projects/<project>/bmt_jobs.json`.
- **Template:** All projects use the same template. Leave **template_uri** as `projects/shared/input_template.json`.
- **Validate:** From repo root run `uv run python tools/scripts/validate_bmt_jobs_schema.py`. Fix any errors before syncing.
- **Schema:** `schemas/bmt_jobs.schema.json` (allowed keys; gate may include e.g. tolerance_abs; all scoring/gate logic is in code, not schema).

**Runtime JSONs:** Produced by the VM; you do not create or edit them. Schemas in `gcp/image/schemas/` are for reference only.

---

## Quick reference

| I want to… | Do this |
|------------|--------|
| **New project** | `just add-project <project>` → edit `bmt_jobs.json` (paths, runner, gate, parsing) → `GCS_BUCKET=<bucket> just deploy`. |
| **New BMT / new WAVs** | Add entry under **bmts** in `bmt_jobs.json` → upload WAVs with `bucket_upload_wavs --dest-prefix <dataset_prefix>` (same as **paths.dataset_prefix**). |
| **Custom manager logic** | Edit `gcp/image/projects/<project>/bmt_manager.py` only when needed; override _evaluate_gate or run_file (see §3). |
| **JSON config** | Edit `bmt_jobs.json`; run `validate_bmt_jobs_schema.py`. Keep **template_uri** as `projects/shared/input_template.json`. |
| **App repo / CI** | Add CMake preset, set PROJECT/PRESET for runner upload, ensure `.github/bmt/` exists. See [adding-a-new-project.md](adding-a-new-project.md). |
