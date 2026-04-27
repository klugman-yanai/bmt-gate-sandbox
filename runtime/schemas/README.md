# Runtime JSON schemas

Schemas in this directory describe runtime-generated JSON artifacts written by the Cloud Run BMT pipeline. The JSON files themselves are not versioned; they are written to GCS at runtime. These schemas are versioned and baked into the image so that:

- Documentation and validation tools can reference them in CI and local debugging.
- The image build carries a single source of truth for the shape of runtime outputs.

| Schema | Describes | Produced by |
|--------|-----------|-------------|
| `krdm_runner_execution_results_v1.schema.json` | Per-case `.bmt.json` runner execution results: `case_format`, counters, optional `paths` and `kardome_lib_version` | kardome_runner in core-main |
| `examples/sk_sanity_tests_case.bmt.json.example` | Example SK `sanity_tests` one-case output (false-alarm style); fixture-style `kardome_lib_version` | Reference |
| `krdm_bmt_case_metrics_v1.schema.json` | Older minimal per-case JSON (counter + key aliases) | Legacy runners; v2 is preferred for new work |
| `bmt_root_results.schema.json` | `bmt_root_results.json` (run summary in bucket) | Coordinator / compatibility tools |
| `manager_summary.schema.json` | `manager_summary.json` (per-leg summary) | Cloud Run task runtime |
| `ci_verdict.schema.json` | `snapshots/<run_id>/ci_verdict.json` | Cloud Run task runtime |
| `current_pointer.schema.json` | `current.json` (results pointer) | Cloud Run coordinator |
| `latest_result.schema.json` | `snapshots/<run_id>/latest.json` (full outcome) | Cloud Run task runtime |
## Schema Versioning & Compatibility Policy

Every canonical JSON artifact includes an optional `schema_version` integer field. The current version is **1** (defined in `gcp.image.config.constants.ARTIFACT_SCHEMA_VERSION`).

**Rules:**

- **Additive changes only** within a major version: new optional fields may be added; existing fields must not be removed or change type.
- **Consumers must ignore unknown keys** (`additionalProperties: true`).
- **Producers should emit `schema_version`** when writing artifacts so consumers can detect the version.
- If a breaking change is needed, bump the major version and add migration logic at the boundary.
