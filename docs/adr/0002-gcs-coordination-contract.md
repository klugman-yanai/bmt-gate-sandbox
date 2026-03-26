# ADR 0002: GCS coordination contract

## Status

Accepted

## Context

The pipeline has no shared database. **Google Cloud Storage** holds:

- Frozen **plans** and per-leg **summaries** under `triggers/`
- **Snapshots** and **`current.json`** pointers under each project’s `results/` tree

Workers must agree on **paths**, **ordering**, and **cleanup** without transactions.

## Decision

Treat the bucket (mirroring **`benchmarks/`**) as the **single coordination plane**:

- Ephemeral objects under `triggers/` for the active run
- Persistent results under `projects/.../results/...`
- **Coordinator** is the single writer for pointer updates and ephemeral cleanup after tasks complete (per workflow design)

## Consequences

- **Positive:** Simple, inspectable artifacts; works with standard GCS tooling
- **Negative:** Must document invariants and test edge cases (partial failure, retries); see [plans/bmt-weak-points-remediation.md](../plans/bmt-weak-points-remediation.md)

## References

- [tools/repo/paths.py](../../tools/repo/paths.py) — `DEFAULT_STAGE_ROOT` / `benchmarks/`
- [docs/bmt-architecture-deep-dive.md](../bmt-architecture-deep-dive.md)
