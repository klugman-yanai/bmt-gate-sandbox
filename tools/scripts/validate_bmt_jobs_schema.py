#!/usr/bin/env python3
"""Validate all bmt_jobs.json files under gcp/image against schemas/bmt_jobs.schema.json.

Config files in gcp/image are synced to the bucket and may be baked into the image;
they must not reference local paths (e.g. $schema). This script passes the schema
explicitly. Exits 0 if all pass, 1 on first error. Use in CI or pre-commit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    root = Path(__file__).resolve().parent.parent.parent
    if not (root / "schemas").is_dir():
        raise SystemExit("Expected repo root with schemas/")
    return root


def main() -> int:
    root = _repo_root()
    schema_path = root / "schemas" / "bmt_jobs.schema.json"
    if not schema_path.is_file():
        print(f"::error::Schema not found: {schema_path}", file=sys.stderr)
        return 1

    try:
        import jsonschema
    except ImportError:
        print("::error::Install jsonschema (e.g. uv sync)", file=sys.stderr)
        return 1

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    # Find all bmt_jobs.json under gcp/image (VM/bucket config; no $schema to keep paths portable).
    jobs_files = sorted(root.glob("gcp/image/**/bmt_jobs.json"))
    if not jobs_files:
        print("No bmt_jobs.json files found under gcp/image/", file=sys.stderr)
        return 0

    for path in jobs_files:
        rel = path.relative_to(root)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            validator.validate(data)
            print(f"OK {rel}")
        except json.JSONDecodeError as e:
            print(f"::error::{rel}: Invalid JSON: {e}", file=sys.stderr)
            return 1
        except jsonschema.ValidationError as e:
            print(f"::error::{rel}: Schema validation failed: {e.message}", file=sys.stderr)
            if e.path:
                print(f"  at {'/'.join(str(p) for p in e.path)}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
