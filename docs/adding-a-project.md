# Adding a project or BMT

Two paths: **full checklist** (bmt-gcloud + app repo) or **quick** (bmt-gcloud only: new project, new BMT/WAVs, or custom manager).

---

## Full checklist (bmt-gcloud + app repo)

Get a new project running on the VM and in CI. Do the steps **in order**.

| # | Where | What |
|---|--------|------|
| 1 | bmt-gcloud | Scaffold: `just add-project <project>`. |
| 2 | bmt-gcloud | Edit `gcp/image/projects/<project>/bmt_jobs.json` (paths, runner.uri, gate, parsing.counter_pattern). |
| 3 | bmt-gcloud | Validate: `uv run python tools/scripts/validate_bmt_jobs_schema.py`. Sync: `GCS_BUCKET=<bucket> just deploy`. |
| 4 | App repo | Add CMake preset; ensure workflow uploads runner with correct PROJECT/PRESET. **runner.uri** in bmt_jobs.json must match. |
| 5 | App repo | Ensure `.github/bmt/` exists (copy from bmt-gcloud or one-time setup). |

No project list to edit — layout policy finds projects by `*/bmt_manager.py` under `gcp/image/`.

**Scaffold creates:** `gcp/image/projects/<project>/bmt_manager.py` and `bmt_jobs.json`. Set **paths.dataset_prefix**, **paths.outputs_prefix** (etc.), **runner.uri**, **template_uri** (`projects/shared/input_template.json`), **gate**, **parsing**. Manager is generated; edit `bmt_manager.py` only for custom gate or runner behavior (see [Custom manager](#custom-manager)).

---

## Quick (bmt-gcloud only)

### New project

`just add-project <project>` → edit `bmt_jobs.json` (paths, runner.uri, gate, parsing) → `GCS_BUCKET=<bucket> just deploy`.

### New BMT or WAV dataset

1. In `gcp/image/projects/<project>/bmt_jobs.json`, under **bmts**, add a new BMT id (stable UUID).
2. Set **paths.dataset_prefix** (and other paths), **runner**, **gate**, **parsing** for that BMT.
3. Upload WAVs: `GCS_BUCKET=<bucket> uv run python -m tools.remote.bucket_upload_wavs --source-dir <local_dir> --dest-prefix <dataset_prefix>`. **dest-prefix** must match **paths.dataset_prefix** for that BMT.

### Custom manager

Scaffold gives a full manager. Override **\_evaluate_gate** or **run_file** in `gcp/image/projects/<project>/bmt_manager.py` only when you need custom gate or runner behavior. Subclass from `gcp.image.projects.shared.bmt_manager_base`; see `gcp/image/projects/sk/bmt_manager.py` or `gcp/image/projects/skyworth/bmt_manager.py`.

---

## Reference

- **bmt_jobs.json:** `gcp/image/projects/<project>/bmt_jobs.json`. Schema: `schemas/bmt_jobs.schema.json`. Keep **template_uri** as `projects/shared/input_template.json`.
- **Config:** [configuration.md](configuration.md). **Architecture:** [architecture.md](architecture.md).
