# Shared stage assets (`benchmarks/projects/shared/`)

## `dependencies/`

Put **cross-project** native libraries here (one physical copy in git and in GCS) so every BMT does not duplicate large `.so` trees.

In each `bmt.json`, set:

- **`runner.uri`** — project-specific binary under `projects/<id>/lib/` (e.g. `kardome_runner`).
- **`runner.deps_prefix`** — `projects/shared/dependencies` (or a subfolder if you split versions later).

At runtime, the Kardome executor puts the runner’s directory on `LD_LIBRARY_PATH` first, then appends `deps_prefix`, so project-local `.so` files resolve before shared ones.

Versioned libraries may include an unversioned name as a **symlink** to the SONAME actually required by project binaries (e.g. `libonnxruntime.so` → `libonnxruntime.so.1` when `NEEDED` is `libonnxruntime.so.1`).
