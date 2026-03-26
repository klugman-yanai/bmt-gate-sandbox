# Adding a project or BMT

For a compact ordered checklist, run **`just workflow`**. For repo hints (`.venv`, `benchmarks/projects/`), run **`just status`** (alias: **`just workflow-status`**).

**Unfamiliar commands?** See **[contributor-commands.md](contributor-commands.md)** and **[local-bmt-testing.md](local-bmt-testing.md)** (run checks before **`just publish`**). **Short happy path:** [bmt-first-benchmark.md](bmt-first-benchmark.md).

Everything under **`benchmarks/`** is mirrored to your GCS bucket. Prefer **`just add`** (scaffold + optional BMT + optional dataset), **`just test-local`**, **`just publish`** (builds the plugin and sets **`enabled`: true** unless you pass **`--no-enable`**), then **`just sync-to-bucket`**. Lower-level Typer commands remain **`just stage …`** and **`just workspace …`**.

Each benchmark has a **folder** under `bmts/` (e.g. `example`, `my_second_bmt`). The manifest is always **`bmt.json`** inside that folder.

---

## New project

Use one **project name** (lowercase, digits, underscores; starts with a letter). Replace `myproject` with yours.

### 1. Scaffold (and optionally BMT + WAVs)

```bash
just add myproject
# optional in one go:
# just add myproject --bmt=my_second_bmt --data=/path/to/dataset.zip
```

Same as **`just stage project`** when you only create the tree; **`--bmt`** matches **`just stage bmt`**; **`--data`** matches **`just upload-wav`** (zip, directory, or `.tar`/`.tar.gz`/`.tgz`; for **7z**, extract first).

### 2. Edit the scaffold

- Plugin: `benchmarks/projects/myproject/plugin_workspaces/default/`
- Manifests: `benchmarks/projects/myproject/bmts/<folder>/bmt.json`

### 3. Quick checks before publish

```bash
just test-local
just tools bmt verify myproject example
```

See **[local-bmt-testing.md](local-bmt-testing.md)**.

### 4. Publish the plugin

```bash
just publish myproject example
# if only one BMT exists under benchmarks/projects/, you can use: just publish
```

This updates **`plugin_ref`**, sets **`enabled`: true** by default, and syncs the project subtree to GCS unless **`--no-sync`**.

### 5. Sync the full `benchmarks/` tree to the bucket

```bash
just sync-to-bucket
# same as: just workspace deploy
```

### 6. CI

Once the bucket matches, the next BMT run that includes this project can pick up the enabled leg.

---

## New BMT (second benchmark, same project)

```bash
just add myproject --bmt=my_second_bmt
```

Edit `benchmarks/projects/myproject/bmts/my_second_bmt/bmt.json`, upload WAVs (**`just add myproject --bmt=my_second_bmt --data=…`** or **`just upload-wav`**), then **`just test-local`**, **`just publish myproject my_second_bmt`**, **`just sync-to-bucket`**.

---

## Plugin code (reminder)

- Work in `benchmarks/projects/<project>/plugin_workspaces/<plugin>/`.
- After publish, `bmt.json` should reference an immutable bundle under `projects/<project>/plugins/...`.
- **API and runner behavior (stdout today, JSON later):** [bmt-python-contributor-protocol.md](bmt-python-contributor-protocol.md).

---

## See also

- [configuration.md](configuration.md) — `GCS_BUCKET` and related env
- [architecture.md](architecture.md) — runtime pipeline
