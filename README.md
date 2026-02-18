# BMT Cloud Sandbox

Minimal sandbox for cloud-orchestrated BMT gating.

## Purpose
This repo keeps only:
1. Bucket bootstrapping assets (`remote/` mirror).
2. Thin CI trigger logic.
3. Local bootstrap/dev scripts.

## Canonical layout
- `.github/workflows/ci.yml`
- `.github/scripts/trigger_cloud_bmt.py`
- `.github/scripts/validate_cloud_infra.py`
- `remote/root_orchestrator.py`
- `remote/bmt_projects.json`
- `remote/bmt_root_results.json`
- `remote/sk/sk_bmt_manager.py`
- `remote/sk/config/bmt_jobs.json`
- `remote/sk/config/input_template.json`
- `remote/sk/results/false_rejects/latest.json`
- `remote/sk/results/false_rejects/last_passing.json`
- `remote/sk/results/sk_bmt_results.json`
- `repo/bootstrap/*.py`
- `repo/dev/run_local_bmt.py`

`remote/` maps directly to `gs://<bucket>/`.

## CI model
- Single workflow: `.github/workflows/ci.yml`
- Matrix sub-jobs per `project+bmt`
- Each job only authenticates and triggers VM orchestration

## Local bootstrap usage
Sync mirror to bucket:

```bash
BUCKET="<bucket>" python3 ./repo/bootstrap/sync_remote_to_bucket.py
```

Upload runner with rotation:

```bash
BUCKET="<bucket>" python3 ./repo/bootstrap/upload_runner.py \
  --runner-path repo/staging/runners/sk_gcc_release/kardome_runner
```

Upload wavs:

```bash
BUCKET="<bucket>" python3 ./repo/bootstrap/upload_wavs.py \
  --source-dir repo/staging/wavs/false_rejects
```

Validate bucket contract:

```bash
BUCKET="<bucket>" python3 ./repo/bootstrap/validate_bucket_contract.py
```

Validate bucket contract + runner binary present:

```bash
BUCKET="<bucket>" python3 ./repo/bootstrap/validate_bucket_contract.py --require-runner
```

Run one local sanity invocation (still cloud-backed for assets/data):

```bash
BUCKET="<bucket>" python3 ./repo/dev/run_local_bmt.py \
  --project sk --bmt-id false_reject_namuh
```

## Notes
- WAV payload is not committed.
- Runner binaries are not committed.
- Runtime workspace default is `~/sk_runtime`.

## Full reseed flow (destructive)
Clear bucket and reseed from `remote/`:

```bash
gcloud storage rm --recursive "gs://<bucket>/**"
BUCKET="<bucket>" python3 ./repo/bootstrap/sync_remote_to_bucket.py --delete
BUCKET="<bucket>" python3 ./repo/bootstrap/upload_runner.py --runner-path "<local_runner_binary>"
BUCKET="<bucket>" python3 ./repo/bootstrap/upload_wavs.py --source-dir "<local_wav_root>"
BUCKET="<bucket>" python3 ./repo/bootstrap/validate_bucket_contract.py --require-runner
```
