# Remote Layout Policy

`remote/` is a direct local mirror of the bucket namespace.

Allowed top-level entries:

- `remote/code/` (maps to `<code-root>`)
- `remote/runtime/` (maps to `<runtime-root>`)
- `remote/README.md`

Any extra top-level directory (for example `remote/vmfs`, `remote/bucket`, `remote/bootstrap`, `remote/legacy_project`) is policy drift.

## What Belongs Where

- Put watcher/orchestrator/bootstrap/lib/config/manager code in `remote/code`.
- Keep bootstrap edits under `remote/code/bootstrap` only.
- Keep pinned UV checksum in `remote/code/_tools/uv/linux-x86_64/uv.sha256` (binary is uploaded to bucket by `just sync-remote`).
- Keep VM runtime dependency contract in `remote/code/pyproject.toml` and `remote/code/uv.lock`.
- Put runner binaries and input directory placeholders in `remote/runtime`.
- Do not put `triggers/`, `results/`, or `outputs/` under `remote/runtime` (generated at runtime, not source).
- Do not put local WAV datasets under `remote/runtime/**/inputs`; keep local corpora under `data/` and upload explicitly.
- Do not put `__pycache__` or `*.pyc` under either mirror.

## Manual Operations

- Sync code mirror: `just sync-remote`
- Sync runtime seed mirror: `just sync-runtime-seed`
- Verify both mirrors against bucket manifests: `just verify-sync`
- Validate local layout policy: `just validate-layout`
- Pre-commit advisory hook (`scripts/hooks/pre-commit-sync-remote.sh`) warns when `remote/` and bucket manifests diverge.
- Local diagnostics are non-authoritative and belong under `.local/diagnostics/`.
