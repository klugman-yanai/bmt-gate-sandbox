#!/usr/bin/env python3
"""Single entrypoint for gcp/image. Config-driven; no CLI parsing.

Reads a JSON config file and dispatches to the appropriate operation:
  - watcher: polls GCS/Pub/Sub for triggers, runs orchestrator per leg
  - orchestrator: runs a single BMT leg

Config resolution: explicit path > BMT_CONFIG env var > well-known paths.
See entrypoint_config.py for details.
"""

from __future__ import annotations

import sys


def main(config_path: str | None = None) -> int:
    # Defer heavy imports until after config is loaded (fast fail on bad config)
    from gcp.image.entrypoint_config import load_entrypoint_config

    config = load_entrypoint_config(config_path)

    if config.mode == "watcher":
        from gcp.image.run import run_watcher

        assert config.watcher is not None
        return run_watcher(config.watcher)

    if config.mode == "orchestrator":
        from gcp.image.run import run_orchestrator

        assert config.orchestrator is not None
        return run_orchestrator(config.orchestrator)

    return 1


if __name__ == "__main__":
    # Accept optional config path as first positional arg (not argparse — just sys.argv)
    path = sys.argv[1] if len(sys.argv) > 1 else None
    raise SystemExit(main(path))
