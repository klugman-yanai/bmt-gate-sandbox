# Deploy layout policy

`deploy/` is the single deployable surface: a direct local mirror of the bucket namespace.

Allowed top-level entries:

- `deploy/code/` (maps to bucket `code/`)
- `deploy/runtime/` (maps to bucket `runtime/`)
- `deploy/README.md`

Any extra top-level directory (for example `deploy/vmfs`, `deploy/bucket`, `deploy/bootstrap`, `deploy/legacy_project`) is policy drift.

## What belongs where

- Put watcher/orchestrator/bootstrap/lib/config/manager code in `deploy/code`.
- Keep bootstrap edits under `deploy/code/bootstrap` only.
- Keep pinned UV checksum in `deploy/code/_tools/uv/linux-x86_64/uv.sha256` (binary is uploaded to bucket by `just sync-remote`).
- Keep VM runtime dependency contract in `deploy/code/pyproject.toml` and `deploy/code/uv.lock`.
- Put runner binaries and input directory placeholders in `deploy/runtime`.
- Do not put `triggers/`, `results/`, or `outputs/` under `deploy/runtime` (generated at runtime, not source).
- Do not put local WAV datasets under `deploy/runtime/**/inputs`; keep local corpora under `data/` and upload explicitly.
- Do not put `__pycache__` or `*.pyc` under either mirror.

## Manual operations

- Sync code mirror: `just sync-remote`
- Sync runtime seed mirror: `just sync-runtime-seed`
- Verify both mirrors against bucket manifests: `just verify-sync`
- Validate local layout policy: `just validate-layout`
- Pre-commit hook (`scripts/hooks/pre-commit-sync-remote.sh`) blocks commits that touch `deploy/` unless the bucket is in sync (or `SKIP_SYNC_VERIFY=1`).
- Local diagnostics are non-authoritative and belong under `.local/diagnostics/`.
