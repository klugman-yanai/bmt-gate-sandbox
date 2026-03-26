# ADR 0004: Plugin SDK boundary (image vs stage bucket)

## Status

Accepted

## Context

BMT plugins are Python packages under `gcp/stage/projects/<project>/plugin_workspaces/` (and checksum-pinned copies under `plugins/…`). The runtime loads them from a **stage root** that mirrors GCS. Contributor-facing types and helpers live under `gcp/image/runtime/sdk/`.

## Decision

- **Public SDK (image):** `gcp.image.runtime.sdk` and explicitly documented re-exports (`BmtPlugin`, `ExecutionContext`, result types, manifest helpers, compatibility constants). Changes here ship with **Cloud Run image** deploys.
- **Per-project code (bucket / stage mirror):** plugin packages, `bmt.json`, datasets, native runners. Changes here propagate via **`gcp/stage/` → GCS sync**, without an image rebuild.

## Consequences

- Contributors should prefer `from gcp.image.runtime.sdk import …` for stable imports.
- Deep imports from other `gcp.image.runtime` modules are **not** guaranteed stable across image versions.
- New SDK surface should be covered by unit tests in `tests/`.
