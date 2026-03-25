# ADR 0005: Baseline scores not passed into plugins (yet)

## Status

Accepted (current behavior)

## Context

`BmtPlugin.score` and `BmtPlugin.evaluate` accept `baseline: ScoreResult | None`. That parameter anticipates comparing a run to a stored baseline.

## Decision

The benchmark execution entrypoint (`execute_leg` in `gcp/image/runtime/execution.py`) **always passes `None`** for baseline today. Plugins must not assume baseline comparison works in production until this ADR is superseded and the loader is implemented.

## Consequences

- Plugin code may branch on `baseline is None` (bootstrap path) vs future non-`None` (comparison path).
- Removing or narrowing the `baseline` parameter requires a deliberate API revision and doc updates.
