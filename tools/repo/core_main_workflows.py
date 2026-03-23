"""Compare local GitHub workflow YAML with Kardome-org/core-main on the dev branch."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from difflib import unified_diff
from pathlib import Path
from typing import Any, cast

from tools.shared.cli_availability import command_available

CORE_MAIN_REPO = "Kardome-org/core-main"
CORE_MAIN_REF = "dev"


def _env_skip() -> bool:
    v = os.environ.get("CORE_MAIN_WORKFLOW_CHECK", "").strip().lower()
    return v in ("0", "false", "skip", "no")


def _strict_drift() -> bool:
    return os.environ.get("CORE_MAIN_WORKFLOW_CHECK", "").strip().lower() == "strict"


def _gh_authenticated() -> bool:
    if not command_available("gh"):
        return False
    r = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.returncode == 0


def _gh_api_json(path: str) -> object | None:
    """GET via ``gh api`` (path includes query string if needed). Returns parsed JSON or None."""
    r = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _remote_workflow_names() -> list[str] | None:
    data = _gh_api_json(f"repos/{CORE_MAIN_REPO}/contents/.github/workflows?ref={CORE_MAIN_REF}")
    if not isinstance(data, list):
        return None
    names: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        row = cast(dict[str, Any], item)
        if row.get("type") == "file":
            name = row.get("name")
            if isinstance(name, str) and name.endswith((".yml", ".yaml")):
                names.add(name)
        elif row.get("type") == "dir" and row.get("name") == "internal":
            internal = _gh_api_json(
                f"repos/{CORE_MAIN_REPO}/contents/.github/workflows/internal?ref={CORE_MAIN_REF}"
            )
            if not isinstance(internal, list):
                continue
            for child in internal:
                if not isinstance(child, dict):
                    continue
                crow = cast(dict[str, Any], child)
                if crow.get("type") != "file":
                    continue
                cname = crow.get("name")
                if isinstance(cname, str) and cname.endswith((".yml", ".yaml")):
                    names.add(cname)
    return sorted(names)


def _remote_workflow_text(name: str) -> str | None:
    for rel in (name, f"internal/{name}"):
        data = _gh_api_json(
            f"repos/{CORE_MAIN_REPO}/contents/.github/workflows/{rel}?ref={CORE_MAIN_REF}"
        )
        if not isinstance(data, dict):
            continue
        payload = cast(dict[str, Any], data)
        if payload.get("encoding") != "base64":
            continue
        raw_b64 = payload.get("content")
        if not isinstance(raw_b64, str):
            continue
        raw = base64.b64decode(raw_b64.replace("\n", ""))
        return raw.decode("utf-8", errors="replace")
    return None


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip() + "\n"


def run_drift_check(local_workflows_dir: Path, *, mode: str) -> int:
    """Compare local ``*.yml`` / ``*.yaml`` to core-main ``dev`` when names overlap.

    By default this is **informational** (exit 0): prints ``match`` or ``diff`` per file.
    Set ``CORE_MAIN_WORKFLOW_CHECK=strict`` to exit 1 when any overlapping file differs.

    ``mode`` is ``preflight`` or ``release`` (only affects messaging when ``gh`` is missing:
    ``release`` fails if you need the check but cannot reach the API — unless skipped).

    Returns 0 if ok or skipped, 1 on strict drift or unrecoverable error.
    """
    if _env_skip():
        print("CORE_MAIN_WORKFLOW_CHECK=skip: skipping core-main workflow drift check.")
        return 0

    strict = _strict_drift()

    if not command_available("gh") or not _gh_authenticated():
        msg = "core-main workflow check skipped (install and authenticate `gh`: gh auth login)."
        if mode == "release" and strict:
            print(f"::error::{msg}", file=sys.stderr)
            return 1
        print(f"warning: {msg}")
        return 0

    remote_names = _remote_workflow_names()
    if remote_names is None:
        msg = "could not list workflows on Kardome-org/core-main (dev) via gh api"
        if mode == "release" and strict:
            print(f"::error::{msg}", file=sys.stderr)
            return 1
        print(f"warning: {msg}")
        return 0

    if not local_workflows_dir.is_dir():
        print(f"::error::Missing directory: {local_workflows_dir}", file=sys.stderr)
        return 1

    local_by_name: dict[str, Path] = {}
    for p in sorted(local_workflows_dir.glob("*.yml")):
        local_by_name[p.name] = p
    for p in sorted(local_workflows_dir.glob("*.yaml")):
        local_by_name.setdefault(p.name, p)
    internal_dir = local_workflows_dir / "internal"
    if internal_dir.is_dir():
        for p in sorted(internal_dir.glob("*.yml")):
            local_by_name.setdefault(p.name, p)
        for p in sorted(internal_dir.glob("*.yaml")):
            local_by_name.setdefault(p.name, p)
    local_names = sorted(local_by_name)
    overlap = sorted(set(remote_names) & set(local_names))
    if not overlap:
        print(
            f"notice: no overlapping workflow names between {local_workflows_dir} and {CORE_MAIN_REPO}@{CORE_MAIN_REF}."
        )
        return 0

    print(f"core-main workflows ({CORE_MAIN_REPO}@{CORE_MAIN_REF}) vs {local_workflows_dir}:")
    any_diff = False
    for name in overlap:
        remote = _remote_workflow_text(name)
        if remote is None:
            print(f"  ? {name} — could not fetch remote", file=sys.stderr)
            any_diff = True
            continue
        local_path = local_by_name[name]
        local = local_path.read_text(encoding="utf-8", errors="replace")
        rn = _normalize(remote)
        ln = _normalize(local)
        if rn == ln:
            print(f"  match  {name}")
            continue
        any_diff = True
        print(f"  differ {name}")
        diff_lines = list(
            unified_diff(
                ln.splitlines(),
                rn.splitlines(),
                fromfile=f"local/{name}",
                tofile=f"{CORE_MAIN_REPO}@{CORE_MAIN_REF}/{name}",
                lineterm="",
            )
        )
        max_lines = 80 if not strict else 200
        for line in diff_lines[:max_lines]:
            print(line, file=sys.stderr)
        if len(diff_lines) > max_lines:
            print(f"... ({len(diff_lines) - max_lines} more lines)", file=sys.stderr)

    if strict and any_diff:
        print("::error::CORE_MAIN_WORKFLOW_CHECK=strict: workflow drift vs core-main dev.", file=sys.stderr)
        return 1
    return 0
