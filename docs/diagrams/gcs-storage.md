# GCS Storage & Coordination Model

Answers: *What is ephemeral vs durable, what keys matter, and who writes what?*

```mermaid
flowchart LR
    subgraph CR ["Cloud Run Jobs"]
        PLAN["Plan\n(CONTROL)"]
        TASK["Task\n(STANDARD / HEAVY)"]
        COORD["Coordinator\n(CONTROL)"]
    end
    DISPATCH["bmtgate\n(dispatch)"]

    subgraph GCS ["GCS Bucket  —  mirrors benchmarks/"]
        subgraph EPH ["Ephemeral  triggers/{wid}/  (coordinator deletes on success)"]
            direction TB
            T1["plans/{wid}.json\nleg matrix"]
            T2["reporting/{wid}.json\nGitHub check-run ID"]
            T3["progress/{wid}/{proj}-{slug}.json\nper-leg in-flight state"]
            T4["summaries/{wid}/{proj}-{slug}.json\nper-leg result"]
            T5["reporting/pr-active/{pr}.json\nsupersession guard"]
        end
        subgraph PERS ["Persistent  projects/"]
            direction TB
            P1["projects/{proj}/bmts/{slug}/bmt.json\nconfig  (synced; not CR-written)"]
            P2["projects/{proj}/plugins/ · lib/ · inputs/\nbundles, runner binary, audio  (synced)"]
            P3["results/{bench}/snapshots/{run_id}/\noutputs, logs, verdict"]
            P4["results/{bench}/current.json\nlatest + last_passing pointers"]
        end
        LOG["log-dumps/{wid}.txt\nfailure concat  (signed URL, 3-day expiry)"]
    end

    PLAN  -->|write| T1
    PLAN  -->|write| T2
    TASK  -->|write| T3
    TASK  -->|write| T4
    TASK  -->|write| P3
    COORD -->|read summaries, write| P4
    COORD -->|write on failure| LOG
    COORD -->|delete entire subtree| EPH
    DISPATCH -->|write / delete| T5
```

## Key facts

| Question | Answer |
| --- | --- |
| Where do I look for a live run? | `triggers/{wid}/` — plan, progress, summaries |
| Where do I look after a run? | `projects/.../results/` — snapshots + `current.json` |
| What does the coordinator read before writing `current.json`? | `triggers/summaries/{wid}/**` (all leg results) + existing `current.json` (`last_passing` pointer) |
| When are ephemeral keys deleted? | After coordinator calls `publish_final_results()` — successful **and** failed runs |
| Which keys survive across runs? | Everything under `projects/` (`snapshots/` pruned to latest + last_passing) |
| What is `last_passing`? | The `run_id` of the last run where all legs passed; used by tasks as the baseline snapshot |
| What can be partial / racy? | `triggers/summaries/` — a task crash leaves a leg absent; coordinator treats absent = failure |
