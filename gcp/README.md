# GCP layout policy

`gcp/` is the single deployable surface: a direct local mirror of the bucket namespace.

Allowed top-level entries:

- `gcp/code/` (maps to bucket `code/`)
- `gcp/runtime/` (maps to bucket `runtime/`)
- `gcp/README.md`

Any extra top-level directory (for example `gcp/vmfs`, `gcp/bucket`, `gcp/bootstrap`, `gcp/legacy_project`) is policy drift.

## What belongs where

- Put watcher/orchestrator/vm/lib/config/manager code in `gcp/code`.
- Keep VM script edits under `gcp/code/vm` only.
- Keep pinned UV checksum in `gcp/code/_tools/uv/linux-x86_64/uv.sha256` (binary is uploaded to bucket by `just sync-gcp`).
- Keep VM runtime dependency contract in `gcp/code/pyproject.toml` and optional `gcp/code/uv.lock`. VM bootstrap uses repo-root `pyproject.toml` for fingerprinting; see [../docs/configuration.md](../docs/configuration.md#pyproject-files).
- Put runner binaries and input directory placeholders in `gcp/runtime`.
- **Runner lib dependencies:** Shared native deps (e.g. `libonnxruntime.so`) live in **`gcp/bmt/dependencies/`**. Each project’s lib dir (`gcp/bmt/<project>/lib/`) should contain the project’s `libKardome.so` plus **symlinks** to those shared deps so the loader finds them without copying. Run **`just symlink-deps`** (or `uv run python tools/scripts/symlink_bmt_deps.py`) to create/refresh symlinks; safe to run repeatedly. Paths are defined in `tools/repo/paths.py` (`DEFAULT_BMT_ROOT`, `BMT_DEPS_SUBDIR`, `BMT_PROJECT_LIB_SUBDIR`); override with **`BMT_ROOT`** env or **`--bmt-root`** for a different layout.
- Do not put `triggers/`, `results/`, or `outputs/` under `gcp/runtime` (generated at runtime, not source).
- Do not put local WAV datasets under `gcp/runtime/**/inputs`; keep local corpora under `data/` and upload explicitly.
- Do not put `__pycache__` or `*.pyc` under either mirror.

## Manual operations

- Sync code mirror: `just sync-gcp`
- Sync runtime seed mirror: `just sync-runtime-seed`
- **Pull bucket into local gcp/** (refresh from GCS so local has all code + runtime artifacts, e.g. after CI uploads): `just pull-gcp` (requires `GCS_BUCKET`). Excludes ephemeral paths (triggers, results, outputs, inputs, .venv) so layout stays valid.
- Verify both mirrors against bucket manifests: `just verify-sync`
- Validate local layout policy: `just validate-layout`
- Pre-commit hook (`tools/scripts/hooks/pre-commit-sync-gcp.sh`) blocks commits that touch `gcp/` unless the bucket is in sync (or `SKIP_SYNC_VERIFY=1`).
- Local diagnostics are non-authoritative and belong under `.local/diagnostics/`.
