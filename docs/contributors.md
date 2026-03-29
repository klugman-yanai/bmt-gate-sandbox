# Plugin SDK & manifest reference

**Workflow** (scaffold, verify, publish, sync): [CONTRIBUTING.md](../CONTRIBUTING.md). **Pipeline:** [architecture.md](architecture.md).

## Imports

```python
import bmtplugin as bmt


class MyPlugin(bmt.BmtPlugin):
    ...
```

## Troubleshooting

- Stale digest in CI → republish + **`just sync-to-bucket`**
- Enabled BMTs need **`published:`** `plugin_ref`
- **`runner.uri`** under synced `benchmarks/` layout
- **`PluginLoadError` / `api_version`** → [architecture.md — ADR summaries](architecture.md#adr-summaries)

**Deferred:** `kardome_runner_json` adapter; **`baseline`** may be **`None`** in `execute` (ADR 0005).

## Protocol (concise)

**You own:** plugin package, dataset layout, Pydantic → valid **`BmtManifest`** (`backend/src/backend/runtime/models.py`).

**Platform owns:** loader, harness, `bmts/` paths.

**`BmtPlugin`:** `prepare`, `execute`, `score`, `evaluate`; match **`plugin.json`**. `teardown` in `finally` after successful `prepare`.

**`bmt.json`:** `model_dump_json(by_alias=True)`; `BmtManifest.model_validate_json`. Template: `uv run python -m tools bmt stage manifest-template …`.

**Runner (typical):** stdout counter line + **`LegacyKardomeStdoutExecutor`** / **`StdoutCounterParseConfig`**.

**Code map:** `backend/src/backend/runtime/sdk/`, `backend/src/backend/runtime/models.py`, `plugin_loader.py`, `stdout_counter_parse.py`, `legacy_kardome.py`.
