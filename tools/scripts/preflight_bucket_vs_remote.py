#!/usr/bin/env python3
"""CLI shim: preflight lives in tools.remote.preflight_bucket (Storage API)."""

from __future__ import annotations

from tools.remote.preflight_bucket import main

if __name__ == "__main__":
    raise SystemExit(main())
