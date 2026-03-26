# Documentation

**Start:** [README](../README.md) · **Contribute:** [CONTRIBUTING](../CONTRIBUTING.md)

| Goal | Doc |
| --- | --- |
| Pipeline, bucket layout, runtime modes | [architecture.md](architecture.md) |
| Diagrams, terms, handoff steps | [pipeline-dag.md](pipeline-dag.md) |
| Maintainer risks & contracts | [bmt-architecture-deep-dive.md](bmt-architecture-deep-dive.md) |
| Env vars, Pulumi, secrets | [configuration.md](configuration.md) |
| New project / BMT | [adding-a-project.md](adding-a-project.md) |
| Plugin + runner contract | [bmt-python-contributor-protocol.md](bmt-python-contributor-protocol.md) |
| Happy-path benchmark | [bmt-first-benchmark.md](bmt-first-benchmark.md) |
| Pre-publish checks | [local-bmt-testing.md](local-bmt-testing.md) |
| `just` / CLI vocabulary | [contributor-commands.md](contributor-commands.md) |
| Incidents, GCS | [runbook.md](runbook.md) |
| Priorities | [ROADMAP.md](../ROADMAP.md) |
| Decisions (ADRs) | [adr/README.md](adr/README.md) |

Design notes and historical plans live under `docs/plans/`, `docs/roadmap/`, and `docs/archive/`. **Path vocabulary:** current code uses **`benchmarks/`** (GCS mirror) and **`backend/`** (Cloud Run image); older write-ups may still say `gcp/stage` or `gcp/image`—treat as the same unless the text is explicitly historical.

**Maintainer index:** [bmt-architecture-deep-dive.md](bmt-architecture-deep-dive.md) · [plans/bmt-weak-points-remediation.md](plans/bmt-weak-points-remediation.md)
