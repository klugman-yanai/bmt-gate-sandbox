# Local checks before `just publish`

Cloud publish builds an immutable plugin bundle, turns **`enabled` on** in `bmt.json` (unless you pass `--no-enable`), and usually syncs the project subtree to GCS. Run cheaper checks first so you do not push broken plugins.

## 1. Quick repo gate

```bash
just test-local
```

This runs a **small** pytest slice (`tests/tools`) and `ruff` on `tools/bmt` and `tools/cli`. It is **not** a substitute for full **`just test`** before you open a PR.

## 2. Load the workspace plugin (no GCS)

Confirms manifests and the staged plugin code import correctly:

```bash
just tools bmt verify <project> <bmt_folder>
```

`<bmt_folder>` is the directory name under `bmts/` (same idea as `bmt_slug` in `bmt.json`).

## 3. Full verification

```bash
just test
```

## 4. Then publish

When you are satisfied:

```bash
just publish
```

If more than one BMT exists under `gcp/stage/projects/`, pass **project** and **benchmark folder**, or set **`BMT_PROJECT`** and **`BMT_BENCHMARK`**. See **`just tools publish --help`**.

## Related

- [adding-a-project.md](adding-a-project.md) — scaffold and bucket flow
- [architecture.md](architecture.md) — how Cloud Run runs plugins
