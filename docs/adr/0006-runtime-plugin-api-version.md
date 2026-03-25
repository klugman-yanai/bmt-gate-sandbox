# ADR 0006: Runtime support for `plugin.json` `api_version`

## Status

Accepted

## Context

`plugin.json` includes `api_version` (e.g. `v1`). The plugin class must match. Without a runtime check, a stage tree built for a **newer** image could be loaded by an **older** image and fail in confusing ways.

## Decision

- The image defines **`SUPPORTED_PLUGIN_API_VERSIONS`** in `gcp.image.runtime.sdk.compatibility`.
- After class/`plugin.json` identity checks, `load_plugin` validates `manifest.api_version` against that set and raises **`PluginLoadError`** if unsupported.

## Consequences

- Adding a new `api_version` requires updating the frozenset and releasing a new image.
- Optional follow-up: semver-style ranges (`packaging`) if multiple versions must coexist.
