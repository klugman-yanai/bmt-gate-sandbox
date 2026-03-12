# Adding a new BMT project

This guide walks through adding a new project (e.g. **Skyworth**) so the VM and CI can run BMT legs for it. The example uses a minimal manager; real projects (like **sk**) will have more logic.

## 1. Where the project lives

- **Bucket convention:** The VM and orchestrator expect **one directory per project** under the code namespace:
  - `{project}/bmt_manager.py` — manager script (downloaded and run by the orchestrator).
  - `{project}/config/bmt_jobs.json` — BMT definitions (enabled BMTs, paths, gate, runner URI, etc.).
  - Optional: `{project}/config/input_template.json` (or other config your manager needs).

- **Repo mirror:** To get that into the bucket, add the same layout under **`gcp/code/`** and sync:
  - `gcp/code/<project>/bmt_manager.py`
  - `gcp/code/<project>/config/bmt_jobs.json`
  - (optional) `gcp/code/<project>/config/input_template.json`

So for **Skyworth** you add `gcp/code/skyworth/` with the files above. After `just sync-gcp` (or your sync step), the bucket has `skyworth/bmt_manager.py` and `skyworth/config/bmt_jobs.json`.

## 2. What to add in bmt-gcloud

### 2.1 Manager script: `gcp/code/<project>/bmt_manager.py`

- Subclass **`BmtManagerBase`** from `gcp.code.projects.base.bmt_manager_base`.
- Implement the abstract methods:
  - **`setup_assets()`** — Download/cache runner binary, template, and dataset from GCS (paths from `self.bmt_cfg["paths"]` and `self.bmt_cfg["runner"]`).
  - **`collect_input_files(inputs_root)`** — Return the list of input files (e.g. `.wav` under the dataset dir).
  - **`run_file(input_file, inputs_root)`** — Run the BMT on one file; return a dict with at least `file`, `exit_code`, `status`, `error`.
  - **`compute_score(file_results)`** — Aggregate per-file results into a single score.
  - **`get_runner_identity()`** — Return a dict describing the runner (name, source ref, etc.).
- Optional: override **`_evaluate_gate(...)`** only if this project’s pass/fail rule is not the simple “current vs baseline” gte/lte. For SK, gate logic is in the manager: it reads **`gate.comparison`** and **`gate.tolerance_abs`** from config and implements gte/lte in **`_evaluate_gate`**. Other projects can implement thresholds, ratios, or any logic; the base does not read or interpret **`gate`**.
- Entrypoint: parse args (include `--jobs-config`), load `bmt_jobs.json`, select `bmts[bmt_id]`, instantiate your manager, call `manager.run()`.

See **`gcp/code/projects/sk/bmt_manager.py`** for a full example; **`gcp/code/skyworth/bmt_manager.py`** for a minimal one.

### 2.2 Jobs config: `gcp/code/<project>/config/bmt_jobs.json`

- Top-level key **`bmts`**: object mapping `bmt_id` → config per BMT.
- Each BMT config must include:
  - **`enabled`** (bool)
  - **`paths`**: `dataset_prefix`, `outputs_prefix`, `results_prefix`, `logs_prefix` (GCS path segments under the runtime bucket).
  - **`gate`**: **not interpreted by the base.** Pass/fail logic lives in the project manager’s **`_evaluate_gate`**. For SK (and any project that uses baseline “current vs baseline” gte/lte), the manager reads **`comparison`** (`"gte"` or `"lte"`) and **`tolerance_abs`** from `gate` and implements that rule in code. Other projects can put any keys under `gate` and implement custom logic in **`_evaluate_gate`** (thresholds, ratios, multi-metric, etc.). Optional **`pass_when`** in config is for human documentation only.
  - **`runner`**: e.g. **`uri`** (path under runtime bucket, e.g. `skyworth/runners/skyworth_gcc_release/kardome_runner`), optional **`deps_prefix`**.
  - **`template_uri`** (if your manager uses a template).
  - **`runtime`**, **`parsing`**, **`warning_policy`**, **`artifacts`** as needed (see existing `gcp/bmt/sk/bmt_jobs.json` or `gcp/code/skyworth/config/bmt_jobs.json`).

### 2.3 Optional: local BMT root (`gcp/bmt/<project>/`)

- For **local** runs and dev, you can mirror inputs/config under **`gcp/bmt/<project>/`** (e.g. `gcp/bmt/skyworth/inputs/`, `gcp/bmt/skyworth/bmt_jobs.json`).  
- **`tools/repo/paths.py`** uses **`DEFAULT_BMT_ROOT = "gcp/bmt"`**; scripts like **`symlink_bmt_deps.py`** use this to find project libs and deps.  
- The **bucket** is populated from **`gcp/code/`** (sync) and from **runner upload** (runtime artifacts); `gcp/bmt/` is for local layout only unless you copy from it into `gcp/code/` or runtime.

### 2.4 Layout policy (optional)

- **`tools/repo/gcp_layout_policy.py`** has a **`REQUIRED_CODE_FILES`** list (e.g. `sk/bmt_manager.py`, `sk/config/bmt_jobs.json`).  
- To make CI enforce the presence of a new project, add the same paths for your project (e.g. `skyworth/bmt_manager.py`, `skyworth/config/bmt_jobs.json`).  
- Alternatively, change the policy to discover projects by scanning for `*/bmt_manager.py` under `gcp/code/` so new projects are picked up without editing the list.

## 3. App repo (e.g. core-main): matrix and runner upload

- **Matrix:** The BMT workflow gets the list of legs from the **caller** (e.g. build-and-test). The caller typically builds **FULL_MATRIX** from **CMakePresets.json**: each preset like **`Skyworth_gcc_Release`** becomes a row with **`project`** = `skyworth` and **`bmt_id`** (e.g. `skyworth_default` or the preset name). So in the **app repo** you add a CMake preset for Skyworth and any BMT IDs you want to run.
- **Runner upload:** The workflow step that uploads the runner uses **`PROJECT`** and **`PRESET`** (e.g. `PROJECT=skyworth`, `PRESET=skyworth_gcc_release`). It uploads the runner binary (and optional libs) to the bucket at **`{project}/runners/{preset}/`** (e.g. `skyworth/runners/skyworth_gcc_release/kardome_runner`).  
- **Filter step:** The BMT workflow keeps only legs whose **project** appears in the set of **successfully uploaded** runner projects. So the first time you add Skyworth, after the runner upload job runs for Skyworth, the filter will include Skyworth legs and the VM will run them — as long as **bmt-gcloud** already has **`gcp/code/skyworth/`** synced to the bucket.

## 4. `.github/bmt/` in the app repo

- The **BMT CLI** and workflow config live under **`.github/bmt/`** (in **bmt-gcloud**). The **app repo** (e.g. core-main) that runs the BMT workflow needs the same **`.github/bmt/`** tree (and related workflows/actions) so that `uv run bmt matrix`, `bmt write-run-trigger`, etc. exist.
- **Creating `.github/bmt/` when the runner is uploaded:** If you want the app repo to “create `.github/bmt/` automatically when a runner is uploaded” (e.g. for a new project), that logic belongs in the **app repo’s workflow**: for example, a step that ensures `.github/bmt/` exists (e.g. copy from a template or from bmt-gcloud) when the upload job runs. In **bmt-gcloud** we only define the canonical CLI and config; we don’t create app-repo folders. Document in the app repo’s workflow or a runbook that “first-time setup for a new project includes ensuring `.github/bmt/` is present (e.g. by syncing from bmt-gcloud).”

## 5. Summary checklist (Skyworth example)

| Step | Where | Action |
|------|--------|--------|
| 1 | bmt-gcloud | Add `gcp/code/skyworth/bmt_manager.py` (subclass of `BmtManagerBase`, implement abstract methods). |
| 2 | bmt-gcloud | Add `gcp/code/skyworth/config/bmt_jobs.json` (at least one BMT with `paths`, `gate`, `runner`, etc.). |
| 3 | bmt-gcloud | Optionally add `gcp/code/skyworth/config/input_template.json` and/or `gcp/bmt/skyworth/` for local use. |
| 4 | bmt-gcloud | Run sync so the bucket gets `skyworth/` (e.g. `just sync-gcp` with `GCS_BUCKET` set). |
| 5 | App repo | Add CMake preset (e.g. `Skyworth_gcc_Release`) and ensure the build uploads the runner with `PROJECT=skyworth`, `PRESET=skyworth_gcc_release`. |
| 6 | App repo | Ensure `.github/bmt/` exists (copy from bmt-gcloud or run a one-time setup). |
| 7 | (Optional) | Update **`REQUIRED_CODE_FILES`** in **`tools/repo/gcp_layout_policy.py`** if you want CI to require `skyworth/bmt_manager.py` and `skyworth/config/bmt_jobs.json`. |

After that, when the BMT workflow runs and the matrix includes Skyworth, the VM will download **`skyworth/bmt_manager.py`** and **`skyworth/config/bmt_jobs.json`** from the bucket and run the manager for each Skyworth leg.
