# Runtime JSON schemas

Schemas in this directory describe **runtime-generated** JSON artifacts produced by the VM (orchestrator, managers, watcher). The JSON files themselves are not versioned; they are written to GCS at runtime. These schemas are versioned and baked into the image so that:

- Documentation and validation tools can reference them on the VM or in CI.
- The image build carries a single source of truth for the shape of runtime outputs.

| Schema | Describes | Produced by |
|--------|-----------|-------------|
| `bmt_root_results.schema.json` | `bmt_root_results.json` (root summary in bucket) | `root_orchestrator.py` |
| `manager_summary.schema.json` | `manager_summary.json` (per-leg manager output) | Per-project manager |
| `ci_verdict.schema.json` | `snapshots/<run_id>/ci_verdict.json` | Per-project manager |
| `current_pointer.schema.json` | `current.json` (results pointer) | `vm_watcher.py` |
| `latest_result.schema.json` | `snapshots/<run_id>/latest.json` (full outcome) | Per-project manager |
| `bmt_jobs.schema.json` | `bmt_jobs.json` (per-project job definitions) | Config input |
| `bmt_registry.schema.json` | `bmt_projects.json` (project registry) | Config input |

Config inputs are validated at the boundary by `gcp.image.config_loader` which returns typed models.

## Schema Versioning & Compatibility Policy

Every canonical JSON artifact includes an optional `schema_version` integer field. The current version is **1** (defined in `gcp.image.config.constants.ARTIFACT_SCHEMA_VERSION`).

**Rules:**

- **Additive changes only** within a major version: new optional fields may be added; existing fields must not be removed or change type.
- **Consumers must ignore unknown keys** (`additionalProperties: true`).
- **Producers should emit `schema_version`** when writing artifacts so consumers can detect the version.
- If a breaking change is needed, bump the major version and add migration logic at the boundary.
