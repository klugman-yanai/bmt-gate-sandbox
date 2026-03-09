# Repository structure and design

How this repo is organized and what the layout represents.

---

## Current layout (modern convention)

- **`.github/workflows/`** — Workflow YAML (bmt.yml, build-and-test.yml, dummy-build-and-test.yml). **`.github/actions/`** — Composite actions only; no Python under `.github/`.
- **`packages/bmt-cli/`** — BMT CLI (Python) used by workflows; run with `uv run --project packages/bmt-cli bmt <cmd>`.
- **`deploy/code/`** — VM code and config; synced to bucket `code/` root.
- **`deploy/runtime/`** — Runtime seed (runner placeholders, etc.); synced to bucket `runtime/` root.
- **`config/`** — Repo-level env contract, repo vars; BMT bootstrap under `config/bmt/`.
- **`tools/`** — Local scripts (sync, upload, validate, monitor, gh/bucket helpers). Not part of production surface.
- **`data/`** — Local wav datasets (uploaded explicitly).
- **`tests/`**, **`docs/`** — Tests and documentation.

Single deploy entrypoint: **`just deploy`** runs `just sync-remote` then `just verify-sync` to push the deploy surface to the bucket. Production surface is documented in [architecture.md](architecture.md#production-surface).
