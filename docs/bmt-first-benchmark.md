# Your first BMT benchmark (happy path)

You already know what a BMT is. This page is for someone who **just cloned the repo** and needs a **short path** to add a benchmark without first learning the whole GitHub Actions → Workflows → Cloud Run pipeline.

**Deeper detail:** [bmt-python-contributor-protocol.md](bmt-python-contributor-protocol.md) · [adding-a-project.md](adding-a-project.md) · [architecture.md](architecture.md)

---

## Glossary (three places your work shows up)

| Place | What it is |
| ----- | ---------- |
| **`gcp/stage/`** in git | The **source of truth** you edit. It mirrors the GCS bucket layout. |
| **GCS bucket** | What **CI and Cloud Run** read at runtime. If the bucket does not match your branch, runs will use **old** plugins or manifests. |
| **Cloud Run image** (`gcp/image/`) | The **Python framework**: `BmtPlugin`, loader, Kardome stdout path, etc. Changing this requires **building and deploying a new image**, not only syncing the bucket. |

Plugins and `bmt.json` files live under **`gcp/stage/`** and sync to the bucket. The **SDK** (`gcp.image.runtime.sdk`) ships **inside the image**.

---

## Blessed path (new project + one benchmark)

1. **Environment:** `uv sync` (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
2. **Scaffold:** `just add <project>` (optional: `--bmt=<folder>` and `--data=…` for WAVs).
3. **Plugin code:** `gcp/stage/projects/<project>/plugin_workspaces/default/src/…` — implement `BmtPlugin` (`prepare`, `execute`, `score`, `evaluate`).
4. **Manifest:** Prefer generating `bmts/<folder>/bmt.json` from Pydantic (see protocol doc §3). Quick option:
   ```bash
   uv run python -m tools bmt stage manifest-template <project> <folder> --stdout
   ```
   Or write under `bmts/<folder>/` and use `--force` to overwrite a scaffolded file when you mean to.
5. **Local checks:** `just test-local` and/or `uv run python -m pytest tests/ -q`; for a narrow check: `uv run python -m tools bmt verify <project> <folder>`.
6. **Publish plugin + enable:** `just publish <project> <folder>` (updates checksum-pinned plugin ref and usually sets `enabled`).
7. **Sync bucket:** `just sync-to-bucket` (needs `GCS_BUCKET`).

Until step 7 completes for your branch, **remote** runs may not see your changes.

---

## Troubleshooting (common first failures)

| Symptom | Likely cause |
| --------| ------------- |
| CI still runs an old plugin | Bucket not synced, or `plugin_ref` still points at an old **checksum-pinned** bundle. Republish and sync. |
| `published:` required / load fails in CI | An **enabled** benchmark must use a **published** `plugin_ref`, not `workspace:`. Publish before enabling. |
| `Runner path is not configured` | `runner.uri` in `bmt.json` does not point at a `kardome_runner` (or equivalent) under `gcp/stage/`. |
| Cannot import `sk_plugin` in a random test | Plugin packages live under `plugin_workspaces/.../src`; tests add that path or load via `load_plugin` with a stage root. |
| `PluginLoadError` about `api_version` | `plugin.json` must declare an API version this **image** supports (see `gcp.image.runtime.sdk.SUPPORTED_PLUGIN_API_VERSIONS`). |

---

## SDK quickstart (imports)

```python
from gcp.image.runtime.sdk import (
    BmtPlugin,
    ExecutionContext,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
    build_default_bmt_manifest,
)
```

Implement a subclass, set `plugin_name` and `api_version` to match `plugin.json`, and use the **helpers** on `BmtPlugin` (`prepared_assets_from_context`, `parse_plugin_config`, `execution_failure_result`, etc.)—see the protocol doc.

---

## What to ignore at first

- **Structured JSON from `kardome_runner`:** still future; stdout parsing is the current default for the reference path.
- **Baseline score comparison:** the runtime does not pass a baseline into `score`/`evaluate` yet; see [ADR 0005](adr/0005-baseline-scoring-not-loaded.md).
