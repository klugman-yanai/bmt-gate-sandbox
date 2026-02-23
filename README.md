# bmt-cloud-dev

Where BMT logic is planned and you interface with the GCP VM/bucket: author config/scripts, test locally, push via devtools; the CI workflow here is copied to production manually.

<!-- Test PR for live monitor verification -->

## Purpose

This repo holds:

1. Bucket mirror and VM-side scripts (`remote/`).
2. Thin CI: matrix discovery and trigger (GCS); VM runs BMT and reports status to GitHub (trigger-and-stop, no blocking workflow).
3. Local runner and devtools for sync/upload/validation.

## Canonical layout

- **Workflow:** `.github/workflows/ci.yml`; `.github/scripts/ci_driver.py` and `ci/` (matrix, trigger, start-vm, wait, gate; adapters, models, config).
- **VM:** `remote/vm_watcher.py` (trigger loop, orchestration driver, aggregation, promotion); `remote/root_orchestrator.py` (one leg: run per-project manager); `remote/sk/bmt_manager.py` (SK project: run runner per WAV, gate, upload results).
- **Local/dev:** `devtools/` (run_sk_bmt_batch, sync_remote_to_bucket, upload_runner, upload_wavs, validate_bucket_contract).
- **Config/data:** `remote/bmt_projects.json`, `remote/sk/config/` (bmt_jobs.json, input_template.json), `remote/sk/results/` (current.json pointer + snapshots per run_id).

`remote/` maps directly to `gs://<bucket>/`. See **ARCHITECTURE.md** for architecture and a full description of client-side and VM-side scripts; **CLAUDE.md** for config, linting, and env vars.

## CI flow (trigger-and-stop)

1. **Discover Matrix** — `ci_driver.py matrix` builds project+BMT matrix.
2. **Trigger** — `ci_driver.py trigger` writes **one** run trigger to GCS (`triggers/runs/<workflow_run_id>.json`) with all legs, then the workflow posts a "pending" commit status and **ends** (no long-running wait job).
3. **VM** — `vm_watcher.py` on the VM polls GCS for run triggers (or a Pub/Sub puller receives the same payload), runs `root_orchestrator.py` for each leg, reads verdicts from manager summaries, updates each leg's **current.json** pointer and cleans stale snapshots, then posts **commit status** (success/failure) to GitHub. Merge is gated by requiring the "BMT Gate" status check to pass.

This saves GitHub Actions runner minutes; the VM does the work and reports back. Set `GITHUB_STATUS_TOKEN` on the VM (PAT with `repo:status`). Require status check "BMT Gate" in branch protection.

## Local usage

Run a local BMT batch (config-driven, no cloud VM):

```bash
python3 devtools/run_sk_bmt_batch.py \
  --bmt-id false_reject_namuh \
  --jobs-config remote/sk/config/bmt_jobs.json \
  --runner remote/sk/runners/kardome_runner \
  --dataset-root data/sk/inputs/false_rejects \
  --workers 4
```

Devtools (bucket sync, runner/wav upload, contract validation):

```bash
BUCKET="<bucket>" python3 devtools/sync_remote_to_bucket.py
BUCKET="<bucket>" python3 devtools/upload_runner.py --runner-path <path>
BUCKET="<bucket>" python3 devtools/upload_wavs.py --source-dir <dir>
BUCKET="<bucket>" python3 devtools/validate_bucket_contract.py [--require-runner]
```

## Full reseed (destructive)

Clear bucket and reseed from `remote/`:

```bash
gcloud storage rm --recursive "gs://<bucket>/**"
BUCKET="<bucket>" python3 devtools/sync_remote_to_bucket.py --delete
BUCKET="<bucket>" python3 devtools/upload_runner.py --runner-path <binary>
BUCKET="<bucket>" python3 devtools/upload_wavs.py --source-dir <wav_root>
BUCKET="<bucket>" python3 devtools/validate_bucket_contract.py --require-runner
```

## Notes

- WAV payload and runner binaries are not committed.
- Runtime workspace default is `~/sk_runtime` (or per CLAUDE.md).
- Result files are written under snapshot prefixes; the watcher updates the canonical `current.json` pointer after all legs complete (see **ARCHITECTURE.md**).
- See **CLAUDE.md** for time/clocks, linting, config files, result paths, and GCP env vars.
- Test-environment note: docs-only commits may be used to trigger workflow checks.
