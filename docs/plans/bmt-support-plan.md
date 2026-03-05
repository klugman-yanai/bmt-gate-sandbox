
Plan

Updated Plan: VM-Decides Runtime Support (No bmt_projects.json) + Non-Failing Partial Support
Summary
Update the design so CI/handoff requests legs from uploaded runners, and the VM is the sole authority on what is runnable.

Key policy updates applied:

Remove bmt_projects.json dependency for runtime support resolution.
Do not make developers pre-filter by VM support.
Pre-handshake must not claim Will run.
Post-handshake is authoritative: VM returns supported vs unsupported.
Do not fail when at least one leg is supported/accepted.
Fail only when zero legs are accepted by VM.
Important Interface / Contract Changes
VM handshake payload (authoritative runtime truth)
Add requested_legs with per-leg decision details.
Keep accepted_legs.
Expand rejected_legs to include full leg identity and reason.
Add support_resolution_version: "v2".
Manager discovery contract (no global manifest)
Per-project convention only:
bmt_manager.py
bmt_jobs.json
Leg support requires:
manager file exists
jobs config exists
bmts.<bmt_id>.enabled != false
Handoff success contract
handshake_ok=true and accepted_leg_count >= 1 => success.
accepted_leg_count == 0 => failure (no_runtime_supported_legs).
Summary semantics
Pre-handshake table uses intent language only:
Requested (awaiting VM capability ack)
Post-handshake table is definitive:
Will run (accepted)
Will skip: <reason> (rejected)
Implementation Plan

1) VM runtime support resolution without bmt_projects.json (bmt-gcloud)
Files:

vm_watcher.py
root_orchestrator.py
implementation.md
communication-flow.md
Changes:

In vm_watcher.py, before writing handshake ack:
For each requested leg, evaluate support by convention paths in bucket.
Parse bmt_jobs.json; validate bmts.<bmt_id> enabled.
Build:
requested_legs[] with decision=accepted|rejected and reason
accepted_legs[]
rejected_legs[] with full identity
Write handshake ack with these fields.
Execute only accepted legs.
If accepted count is zero:
Mark run disposition as accepted-but-empty and emit reason no_runtime_supported_legs.
Skip orchestrator execution loop.
In root_orchestrator.py:
Remove bmt_projects.json lookup.
Derive paths by convention:
manager: bmt_manager.py
jobs: bmt_jobs.json
Keep current manager invocation shape.
Reason codes (fixed set):

manager_missing
jobs_config_missing
jobs_schema_invalid
bmt_not_defined
bmt_disabled
invalid_leg_type
2) Core-main handoff/classify: requester not responsible for VM support
Files:

action.yml
matrix.py (only if needed for cleanup)
upload.sh
handshake.sh
action.yml
action.yml
summary.sh
action.yml
Changes:

Keep classify based on uploaded runners + release matrix only (no VM-support filtering).
In pre-handoff summary (summarize-matrix-handshake):
Replace Will run with Requested (awaiting VM capability ack).
In post-handshake summary:
Render authoritative per-project table from handshake payload (requested_legs, accepted/rejected).
In handoff-run:
Add explicit check after handshake:
if accepted_leg_count == 0 => fail with no_runtime_supported_legs
else continue success path even if some legs rejected.
In failure-fallback:
Handle and surface no_runtime_supported_legs reason cleanly in gate context and summary.
3) Checkout contention hardening (core-main)
Files:

New action.yml
build-and-test.yml
bmt.yml
composite actions with direct checkout usage
Changes:

Replace direct actions/checkout@v4 in hot paths with robust checkout action:
attempt1: SHA depth=1 timeout 5m
attempt2: SHA depth=1 timeout 5m + backoff
attempt3: SHA depth=0 timeout 10m + backoff
attempt4: branch/tag fallback timeout 10m
Remove duplicate checkouts where job-level checkout already exists.
4) Required-gate isolation (core-main)
Files:

build-and-test.yml
New build-and-test-extended.yml
Changes:

Required workflow = release builds + BMT handoff only.
Move nonrelease/debug matrix to informational workflow.
Keep branch-scoped concurrency cancellation and max-parallel caps.
5) Branch protection alignment
Repo settings:

Required checks:
required CI release check(s)
BMT Gate
Nonrelease informational workflow not required.
Test Cases and Scenarios
Partial support (target behavior)
Requested: 12 projects
VM supports: only sk
Expected:
pre-handoff: all Requested (awaiting VM capability ack)
handshake: accepted=1 rejected=11
handoff result: success
post-handshake table: only sk shows Will run
Zero support
Requested projects all unsupported
Expected:
handshake ack written with accepted=0 + rejection reasons
handoff fails with no_runtime_supported_legs
gate failure posted
Mixed rejection reasons
missing manager, missing jobs config, disabled bmt id
Expected:
explicit reason code per rejected leg
Checkout stress
concurrent CI runs active
Expected:
retries/fallback absorb transient fetch issues
lower checkout-related terminal failures
Required vs informational
nonrelease workflow fails
required release+BMT path still independently gateable
Static validation
actionlint clean
shell scripts pass lint checks used in repo
Rollout and Monitoring
VM-first (bmt-gcloud)
Implement watcher/orchestrator changes.
Sync bucket code.
Validate ack payload v2 fields with a controlled run.
Core-main second
Implement summary/handoff/fallback changes and checkout hardening.
Merge to ci/check-bmt-gate.
Monitor one full run (request table -> handshake truth -> final status).
Repro run
second run to confirm stable behavior under normal load.
Explicit Assumptions and Defaults
No bmt_projects.json is used for runtime support decisions.
Project support is determined solely by per-project convention files in bucket code namespace.
Developers/CI request from available uploaded runners; VM decides runtime support.
Partial acceptance is valid success.
Zero accepted legs is terminal failure.
BMT Gate remains final protected status context.
