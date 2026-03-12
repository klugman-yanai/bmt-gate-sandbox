from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from typing import TypeVar, cast

T = TypeVar("T")


def combined_output(proc: CompletedProcess[str]) -> str:
    """Return stderr+stdout in one stable string for error assertions."""
    return f"{proc.stderr}\n{proc.stdout}"


def read_github_output(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines written to GITHUB_OUTPUT."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def decode_output_json(outputs: dict[str, str], key: str) -> T:
    """Decode JSON payload from parsed GITHUB_OUTPUT by key."""
    if key not in outputs:
        raise AssertionError(f"Missing output key: {key}")
    return cast(T, json.loads(outputs[key]))
