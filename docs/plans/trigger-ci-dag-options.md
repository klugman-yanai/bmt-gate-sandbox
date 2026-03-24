# Trigger CI DAG Options

## Current (broken UX)

Push to `ci/check-bmt-gate` shows the full `bmt_handoff` sub-graph as skipped grey nodes.

```mermaid
flowchart LR
  subgraph trigger-ci.yml
    subgraph build-and-test-dev.yml
      snap[Snapshot] --> rel[Release Build]
      snap --> nonrel[Non-Release Build]
      rel --> handoff["bmt_handoff\n(skipped but visible)"]
    end
  end

  style handoff fill:#888,stroke:#666,color:#fff
```

## Option A — Two trigger files (recommended)

### Push DAG (trigger-ci.yml)

```mermaid
flowchart LR
  subgraph trigger-ci.yml — push only
    subgraph build-and-test-dev.yml
      snap[Snapshot] --> rel[Release Build]
      snap --> nonrel[Non-Release Build]
    end
  end
```

### PR DAG (trigger-ci-pr.yml)

```mermaid
flowchart LR
  subgraph trigger-ci-pr.yml — PR only
    subgraph build-and-test-dev.yml
      snap[Snapshot] --> rel[Release Build]
      snap --> nonrel[Non-Release Build]
    end
    rel --> handoff[bmt-handoff.yml]
  end
```

- Push: 3 jobs, no handoff node
- PR: 4 jobs, handoff always runs
- No skipped grey nodes ever

## Option B — Single trigger, handoff promoted to caller

```mermaid
flowchart LR
  subgraph trigger-ci.yml — push + PR
    subgraph build-and-test-dev.yml
      snap[Snapshot] --> rel[Release Build]
      snap --> nonrel[Non-Release Build]
    end
    rel -.->|"PR only"| handoff["bmt-handoff.yml\n(skipped on push)"]
  end

  style handoff fill:#888,stroke:#666,color:#fff,stroke-dasharray: 5 5
```

- Push: 3 build jobs + 1 grey collapsed node
- PR: 3 build jobs + expanded handoff sub-graph
- Single file but still shows a skipped node on push
