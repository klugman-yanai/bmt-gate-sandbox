# Staged BMT projects (`benchmarks/projects/`)

The GCS bucket root mirrors this tree. Layout supports **v1** (`bmts/`, `plugin_workspaces/`, flat `plugins/<name>/sha256-…`) and **v2** (`benchmarks/`, `plugins/<name>/workspace/`, `plugins/<name>/releases/sha256-…`); resolution prefers v2 when present.

## Commands

- **`uv run python -m tools bmt stage doctor <project>`** — validate manifests, `inputs_prefix`, runner path, published digest vs tree, workspace load.
- **`uv run python -m tools bmt stage publish-plugin <project> <plugin_name>`** — publish the workspace once and set `plugin_ref` on every BMT that uses that plugin (`--no-sync` skips GCS project sync).
- **`uv run python -m tools bmt stage publish <project> <benchmark>`** — publish for a single BMT (legacy path).

Do not edit files under immutable **`plugins/.../sha256-...`** (or **`.../releases/sha256-...`**) by hand; change **`plugin_workspaces/...`** or **`plugins/.../workspace/`** and run **publish** / **publish-plugin**.
