# Adding a project or BMT

Everything lives in the **stage scaffold** under `gcp/stage/` (mirrored to the bucket). Use the `just` commands below; they match what CI expects.

Before enabling a new project in cloud CI, run the [plugin conformance checklist](plugin-conformance-checklist.md).

---

## New project

Use one **project slug** everywhere (lowercase, digits, underscores; must start with a letter). Below it is `myproject`—swap it for yours.

### 1. Create the scaffold

```bash
just add-project myproject
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
just publish-bmt myproject example
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
just deploy
```

### 7. CI

After the bucket has the updated manifest, the next BMT run that includes this project can pick up the enabled BMT—no extra registry step.

---

## New BMT (second benchmark, same project)

### 1. Add another BMT slug

```bash
just add-bmt myproject my_second_bmt
```

### 2. Edit the manifest

`gcp/stage/projects/myproject/bmts/my_second_bmt/bmt.json`

The scaffold fills `inputs_prefix`, `results_prefix`, and `outputs_prefix`. Adjust if your layout differs. The manifest may carry **`plugin_ref`** for bookkeeping; the Cloud Run loader always imports **`projects/<project>/plugin.py`** (see `runtime/plugin_loader.py`).

### 3. Publish

```bash
just publish-bmt myproject my_second_bmt
```

### 4. Upload data

Same `just upload-data` pattern as in [New project](#new-project), pointed at this BMT’s inputs.

### 5. Enable and sync

Set `"enabled": true` in that `bmt.json`, then `just deploy` (or your usual sync).

---

## Plugin code (reminder)

- Work in `gcp/stage/projects/<project>/plugin_workspaces/<plugin>/`.
- **`just publish-bmt`** copies assets into **`projects/<project>/plugins/<plugin>/sha256-<digest>/...`** for versioned non-Python files (templates, digests). **`plugin.py`** must still live at **`projects/<project>/plugin.py`** on the synced stage tree — that is what the image imports.

---

## Dataset upload (short)

- Prefer a **zip** (or folder of WAVs): `just upload-data` puts files under `projects/<project>/inputs/...` in the bucket.
- Inspect what landed: `just mount-project myproject` → read-only view under `gcp/mnt/projects/myproject/`.

---

## SK as the reference implementation (extendible design)

The **SK Kardome benchmark** under **`plugins/projects/sk/`** is the repo’s worked example of the plugin model—copy its shape when adding a new project, then replace scoring and runner wiring:

| Piece | Role |
| ----- | ---- |
| **`plugin.py`** | `BmtPlugin`: `prepare` / `execute` / `score` / `verdict`; wires `AdaptiveKardomeExecutor` (batch JSON probe → `KardomeRunparamsExecutor` per-case fallback). |
| **`sk_scoring_policy.py`** | Declares comparison direction, aggregates, and reason codes the gate understands. |
| **`false_alarms.json` / `false_rejects.json`** | Flat BMT manifests: `plugin_config`, `execution.policy`, `runner.template_path`, `forced_wav_path_keys_exclude`, etc. |
| **`runner_integration_contract.json`** | Repo-local contract for tests: which manifest drives structured metrics parsing (`metrics_json_v1`) and batch schema expectations (see `tests/sk_runner_repo_paths.py`). |
| **`runtime/kardome_runparams.py`** (image) | Invokes runner runparams CLI (`--input-wav` / `--user-output` / toggles) and reads sidecar `.bmt.json`; **numeric SK preset** lives in core-main **`run_params_SK.c`**. |
| **`runtime/kardome_case_metrics.py`** (image) | Filenames and JSON keys the image reads next to `USER_OUTPUT_PATH`. Match what your runner writes (see that module). |

**Core-main alignment:** Extend **`Runners/params/src/run_params_SK.c`** for behaviour changes; extend **`sanity_tests.c`** (or the SK runner entrypoint your build uses) to **write structured BMT JSON** so the framework’s plugin path stays stable. See **`docs/kardome_runner_SK_runtime.md`** for the split between JSON paths and C run params.

---

## Do not use for new work

- New per-project `bmt_manager.py` trees under obsolete `gcp/image/` layouts
- Restoring `bmt_jobs.json`-style flows
- Old trigger-file / VM-era patterns
