# Architecture Decision Records (ADRs)

This directory holds **minimal** ADRs: only **expensive-to-reverse** or **high blast-radius** decisions. Routine refactors and small features do **not** need an ADR (use PR description + [CHANGELOG.md](../../CHANGELOG.md)).

## When to add an ADR

- Changing the **coordination contract** (bucket paths, plan/summary shapes, identity boundaries)
- Replacing **major** execution topology (e.g. different orchestrator or job model)
- Security-relevant **defaults** that are hard to roll back

## Index

| ADR | Title |
| --- | --- |
| [0001-accept-workflows-cloud-run.md](0001-accept-workflows-cloud-run.md) | Google Workflows + Cloud Run as the BMT execution plane |
| [0002-gcs-coordination-contract.md](0002-gcs-coordination-contract.md) | GCS as coordination plane and artifact store |

## Superseding

If a decision is reversed, add a **new** ADR that references the old one and mark the old as superseded in the new file’s header—do not delete history.
