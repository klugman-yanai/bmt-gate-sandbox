# Staged BMT projects (`benchmarks/projects/`)

The GCS bucket root mirrors this tree. Pipeline context: [docs/architecture.md](../../docs/architecture.md).

## Layout (current)

- **`projects/<id>/`** — one BMT “project” (tenant).
  - **`plugin.json`** + **`src/<python_package>/`** — primary editable plugin (use **`plugin_ref`: `workspace:main`**). The `main` segment is the stable workspace slot name; path resolution uses the project root when `plugin.json` lives there.
  - Legacy: **`plugin_workspaces/<name>/`** or **`plugins/<name>/workspace/`** (still supported).
  - **`bmts/<slug>/bmt.json`**, **`inputs/`**, **`lib/`** (project-specific runner binary + libraries such as `libKardome.so`), etc.
- **`shared/dependencies/`** — native libraries reused by every project (e.g. ONNX, TensorFlow Lite). Point **`runner.deps_prefix`** in `bmt.json` here so `LD_LIBRARY_PATH` includes this tree after the runner’s directory.
- **`plugins/.../sha256-...`** — bucket-only published bundles; not committed (see root `.gitignore`).

## Commands

- **`uv run python -m tools bmt stage doctor <project>`** — validate manifests, paths, published digest vs tree, plugin load.
- **`uv run python -m tools bmt stage publish-plugin <project> <plugin_name>`** — publish the workspace once and set `plugin_ref` on every BMT that references that plugin (`--no-sync` skips GCS sync).
- **`uv run python -m tools bmt stage publish <project> <benchmark>`** — publish for a single BMT (legacy path).

Do not edit immutable **`plugins/.../sha256-...`** by hand. Edit the workspace / flat `src/` tree, **publish**, then sync to the bucket.
