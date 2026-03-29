#!/usr/bin/env python3

from __future__ import annotations


def main() -> int:
    from backend.runtime.facade import RuntimeFacade

    return (
        RuntimeFacade()
        .bootstrap_runtime()
        .discover_runtime_mode()
        .load_run_identity()
        .load_task_assignment()
        .resolve_runtime_paths()
        .assemble_runtime_invocation()
        .resolve_runtime_stage()
        .execute_runtime_stage()
    )


if __name__ == "__main__":
    raise SystemExit(main())
