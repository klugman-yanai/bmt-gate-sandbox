# BMT Diagrams

This file is the canonical location for Mermaid diagrams used by BMT docs.

## End-To-End Sequence

```mermaid
sequenceDiagram
    autonumber
    participant U as Developer
    participant CI as GitHub Actions: ci.yml
    participant BMT as GitHub Actions: bmt.yml
    participant GCS as GCS Bucket
    participant VM as VM: vm_watcher.py
    participant GH as GitHub Status/Checks

    U->>CI: push / pull_request on dev
    CI->>CI: Build matrix + runner artifacts
    CI->>BMT: workflow_dispatch(ci_run_id, head_sha, ...)

    BMT->>GCS: Upload runner bundle(s)
    BMT->>GCS: Write triggers/runs/workflow_run_id.json
    BMT->>VM: Start VM instance

    VM->>GCS: Poll and read run trigger
    VM->>GCS: Write triggers/acks/workflow_run_id.json
    BMT->>GCS: Wait/read ack
    BMT->>GH: Post pending commit status
    BMT-->>U: Workflow ends (non-blocking)

    VM->>GH: Create Check Run (in_progress)
    loop per leg (project,bmt_id,run_id)
        VM->>VM: root_orchestrator.py
        VM->>VM: project bmt_manager.py
        VM->>GCS: Write snapshots/run_id/*
        VM->>GH: Update Check Run progress
    end

    VM->>GCS: Update current.json pointers
    VM->>GCS: Cleanup stale snapshots
    VM->>GH: Post final commit status + complete Check Run
    VM->>GCS: Delete trigger file
    VM->>VM: Exit if --exit-after-run
```

## VM Processing Flow

```mermaid
flowchart TD
    A[Start vm_watcher.py] --> B[Poll triggers/runs/*.json]
    B --> C{Trigger found?}
    C -- No --> B
    C -- Yes --> D[Download run payload]
    D --> E[Resolve GitHub auth for repository]
    E --> F[Write handshake ack to triggers/acks]
    F --> G[Initialize triggers/status file + heartbeat thread]
    G --> H[Create GitHub Check Run + post pending status]
    H --> I[Download root_orchestrator.py from bucket]
    I --> J{For each leg}
    J --> K[Run root_orchestrator.py]
    K --> L[Run project manager bmt_manager.py]
    L --> M[Manager uploads snapshot artifacts + ci_verdict]
    M --> N[Watcher reads manager_summary + updates progress]
    N --> J
    J --> O[Aggregate leg outcomes]
    O --> P[Update current.json latest/last_passing]
    P --> Q[Delete stale snapshots]
    Q --> R[Finalize status file + complete Check Run]
    R --> S[Post final commit status]
    S --> T[Delete run trigger]
    T --> U{"exit_after_run flag set?"}
    U -- Yes --> V["Exit: startup script stops VM"]
    U -- No --> B
```

## GCS Object Lifecycle

```mermaid
flowchart LR
    subgraph ControlPlane[Control-plane objects]
      TRIG["triggers/runs/workflow_run_id.json"]
      ACK["triggers/acks/workflow_run_id.json"]
      STAT["triggers/status/workflow_run_id.json"]
    end

    subgraph Runners[Runner bundles]
      RUNNER["project/runners/preset/*"]
    end

    subgraph Results[Result objects per BMT]
      SNAP["snapshots/run_id/latest.json + ci_verdict.json + logs/*"]
      PTR["current.json (latest + last_passing)"]
      CLEAN["stale snapshots removed"]
    end

    RUNNER --> TRIG
    TRIG --> ACK
    TRIG --> STAT
    TRIG --> SNAP
    SNAP --> PTR
    PTR --> CLEAN
```
