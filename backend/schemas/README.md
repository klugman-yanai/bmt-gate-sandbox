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

Config inputs (e.g. `bmt_jobs.json`) are validated against `backend/schemas/bmt_jobs.schema.json`.
