#!/usr/bin/env python3
"""Fetch GitHub App metadata (e.g. permissions) using app JWT auth."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import click

try:
    import jwt as pyjwt
except ImportError:
    click.echo("PyJWT required: uv pip install pyjwt cryptography", err=True)
    sys.exit(1)


def get_app_id_from_env() -> str:
    return os.environ.get("GITHUB_APP_TEST_ID") or os.environ.get("GITHUB_APP_PROD_ID") or ""


def fetch_app_metadata(app_id: str, private_key: str) -> dict:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": app_id}
    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    req = urllib.request.Request(
        "https://api.github.com/app",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def extract_path(data: dict, path: str) -> dict | None:
    obj: dict | None = data
    for part in path.strip().lstrip(".").split("."):
        if part and isinstance(obj, dict):
            obj = obj.get(part)
        else:
            obj = None
    return obj


@click.command()
@click.argument("private_key_path", required=False, type=click.Path(exists=True))
@click.option("--app-id", help="GitHub App ID (numeric). Or set GITHUB_APP_TEST_ID / GITHUB_APP_PROD_ID")
@click.option("--private-key", "private_key_path_opt", type=click.Path(exists=True), help="Path to app private key PEM")
@click.option("--jq", "jq_path", help="Optional jq-style path to print (e.g. .permissions)")
def main(
    private_key_path: str | None, app_id: str | None, private_key_path_opt: str | None, jq_path: str | None
) -> int:
    app_id = app_id or get_app_id_from_env()
    if not app_id:
        click.echo("Set --app-id or GITHUB_APP_TEST_ID / GITHUB_APP_PROD_ID", err=True)
        return 1

    key_path = private_key_path_opt or private_key_path
    if not key_path:
        click.echo("Provide private key path (positional or --private-key)", err=True)
        return 1

    private_key = Path(key_path).read_text()

    try:
        data = fetch_app_metadata(app_id, private_key)
    except urllib.error.HTTPError as e:
        click.echo(e.read().decode(), err=True)
        return 1

    if jq_path:
        data = extract_path(data, jq_path)

    click.echo(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
