# Adding a project or BMT

Everything lives in the **stage scaffold** under `gcp/stage/` (mirrored to the bucket). Scaffolding uses one Just recipe, **`just stage`**, with subcommands **`project`**, **`bmt`**, and **`publish`** (same as `uv run python -m tools bmt stage …`). The steps below match what CI expects.

Each benchmark has a **folder name** under `bmts/` (e.g. `example`, `my_second_bmt`). The manifest inside it is always named **`bmt.json`**—so paths look like `bmts/<folder>/bmt.json`, not “bmt inside bmt.”

---

## New project

Use one **project name** everywhere (lowercase, digits, underscores; must start with a letter). Below it is `myproject`—swap it for yours.

### 1. Create the scaffold

```bash
just stage project myproject
```

This adds `gcp/stage/projects/myproject/` with a default plugin workspace, `bmts/example/bmt.json`, and placeholders.

### 2. Edit the scaffold

- Plugin code: `gcp/stage/projects/myproject/plugin_workspaces/default/`
- Change only what you need for parsing, scoring, and evaluation; leave orchestration and reporting to the framework.

### 3. Upload data

```bash
just upload-data myproject /path/to/dataset.zip
# optional: --dataset <name>
```

### 4. Publish the default BMT’s plugin

```bash
just stage publish myproject example
```

`example` is the default BMT name the scaffold created. This updates the manifest and can sync to GCS depending on your env.

### 5. Turn the BMT on

The scaffold ships `bmts/example/bmt.json` with `"enabled": false` so nothing runs before you are ready.

Edit `gcp/stage/projects/myproject/bmts/example/bmt.json` and set:

```json
"enabled": true
```

### 6. Push the stage tree to the bucket

CI reads the bucket, not only your laptop. After you change `bmt.json` (or any stage file), sync:

```bash
# from repo root, with bucket configured (see docs/configuration.md)
just workspace deploy
```

### 7. CI

After the bucket has the updated manifest, the next BMT run that includes this project can pick up the enabled BMT—no extra registry step.

---

## New BMT (second benchmark, same project)

### 1. Add another BMT

```bash
just stage bmt myproject my_second_bmt
```

### 2. Edit the manifest

`gcp/stage/projects/myproject/bmts/my_second_bmt/bmt.json`

The scaffold fills `inputs_prefix`, `results_prefix`, and `outputs_prefix`. Adjust if your layout differs; keep `plugin_ref` as a workspace ref until you publish.

### 3. Publish

```bash
just stage publish myproject my_second_bmt
```

### 4. Upload data

Same `just upload-data` pattern as in [New project](#new-project), pointed at this BMT’s inputs.

### 5. Enable and sync

Set `"enabled": true` in that `bmt.json`, then `just workspace deploy` (or your usual sync).

---

## Plugin code (reminder)

- Work in `gcp/stage/projects/<project>/plugin_workspaces/<plugin>/`.
- Published manifests should point at immutable bundles under `projects/<project>/plugins/<plugin>/sha256-<digest>/...` after publish.

---

## Dataset upload (short)

- Prefer a **zip** (or folder of WAVs): `just upload-data` puts files under `projects/<project>/inputs/...` in the bucket.
- Inspect what landed: `just mount myproject` → read-only view under `gcp/mnt/projects/myproject/`.

---

## Do not use for new work

- New `gcp/image/projects/<project>/bmt_manager.py` files
- Restoring `bmt_jobs.json`-style flows
- Old trigger-file / VM-era patterns
