# GCP layout policy

`gcp/` is the single deployable surface for VM and bucket.

**Source of truth:**
- **`gcp/remote/`** — Bucket content. The bucket root is 1:1 with the layout under `gcp/remote` (runners, inputs, results, triggers, metadata, etc.). GCS is the source of truth for that content; locally you view it (e.g. read-only gcsfuse mount or pull).
- **`gcp/image/`** — VM code and config; **managed via infra** (Packer). Contents are baked into the VM image at build time; they are not uploaded to the bucket. Publish code = image build from this repo; see [../docs/brainstorms/2026-03-12-gcp-remote-image-mounts-brainstorm.md](../docs/brainstorms/2026-03-12-gcp-remote-image-mounts-brainstorm.md).

Allowed top-level entries:

- `gcp/image/` — VM code/config (infra-managed; baked into image)
- `gcp/remote/` — Bucket content (1:1 with bucket root)
- `gcp/README.md`

Any extra top-level directory (for example `gcp/imagefs`, `gcp/bucket`, `gcp/bootstrap`, `gcp/legacy_project`) is policy drift.

*Current bucket still uses `code/` and `runtime/` prefixes; tools sync gcp/image → bucket code/ and gcp/remote → bucket runtime/. Target layout (bucket root = gcp/remote, no code in GCS) is in the brainstorm above.*

## What belongs where

- **gcp/image:** Watcher, orchestrator, VM lib/config/scripts, and per-project managers. All of this is **managed via infra**: Packer ([infra/packer/bmt-runtime.pkr.hcl](../infra/packer/bmt-runtime.pkr.hcl)) bakes it into the VM image; Terraform and config ([infra/terraform](../infra/terraform), [gcp/image/config](../gcp/image/config)) reference it. Do not upload gcp/image to the bucket; publish = image build.
- **gcp/image/schemas/:** Versioned JSON schemas for **runtime-generated** artifacts (`bmt_root_results.json`, `manager_summary.json`, `ci_verdict.json`, `current.json`, `latest.json`). The JSON files themselves are not versioned; the schemas are baked into the image for documentation and optional validation. See [gcp/image/schemas/README.md](image/schemas/README.md).
- Keep VM script edits under `gcp/image/scripts` only.
- Keep pinned UV checksum in `gcp/image/_tools/uv/linux-x86_64/uv.sha256` (binary is uploaded to bucket by `just deploy` until layout migration).
- Keep VM runtime dependency contract in `gcp/image/pyproject.toml` and optional `gcp/image/uv.lock`. VM bootstrap uses repo-root `pyproject.toml` for fingerprinting; see [../docs/configuration.md](../docs/configuration.md#pyproject-files).
- **gcp/remote:** Runner binaries, input placeholders, runtime metadata (e.g. `bmt_root_results.json`), and any other bucket-only data. This is the local view of bucket content.
- **Runner lib dependencies:** Shared native deps (e.g. `libonnxruntime.so`) live in **`gcp/local/dependencies/`**. Each project’s lib dir (`gcp/local/<project>/lib/`) should contain the project’s `libKardome.so` plus **symlinks** to those shared deps so the loader finds them without copying. Run **`just symlink-deps`** (or `uv run python tools/scripts/symlink_bmt_deps.py`) to create/refresh symlinks; safe to run repeatedly. Paths are defined in `tools/repo/paths.py` (`DEFAULT_BMT_ROOT`, `BMT_DEPS_SUBDIR`, `BMT_PROJECT_LIB_SUBDIR`); override with **`BMT_ROOT`** env or **`--bmt-root`** for a different layout.
- Do not put `triggers/`, `results/`, or `outputs/` under `gcp/remote` (generated at runtime, not source).
- Do not put local WAV datasets under `gcp/remote/**/inputs`; keep local corpora under `data/` and upload explicitly.
- Do not put `__pycache__` or `*.pyc` under either mirror.

## Manual operations

- Sync code mirror: `just deploy`
- Sync runtime seed mirror: `just sync-runtime-seed`
- **Pull bucket into local gcp/** (refresh from GCS so local has all code + runtime artifacts, e.g. after CI uploads): `just pull-gcp` (requires `GCS_BUCKET`). Excludes ephemeral paths (triggers, results, outputs, inputs, .venv) so layout stays valid.
- Deploy syncs and verifies both code and runtime seed; verify only is part of `just deploy`.
- Validate local layout policy: `just validate-layout`
- Pre-commit hook blocks commits that touch `gcp/` unless the bucket is in sync (or `SKIP_SYNC_VERIFY=1`). Run `just deploy` to sync and verify.
- Local diagnostics are non-authoritative and belong under `.local/diagnostics/`.
