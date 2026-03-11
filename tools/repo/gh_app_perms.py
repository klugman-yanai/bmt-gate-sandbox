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

import jwt as pyjwt


def get_app_id_from_env() -> str:
    return (
        os.environ.get("GH_APP_TEST_ID")
        or os.environ.get("GH_APP_PROD_ID")
        or os.environ.get("GITHUB_APP_TEST_ID")
        or os.environ.get("GITHUB_APP_PROD_ID")
        or ""
    )


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


class GhAppPerms:
    """Fetch GitHub App metadata (e.g. permissions) using app JWT auth."""

    def run(
        self,
        *,
        app_id: str = "",
        private_key_path: str = "",
        jq_path: str = "",
    ) -> int:
        if pyjwt is None:
            print("PyJWT required: uv pip install pyjwt cryptography", file=sys.stderr)
            return 1

        app_id = (app_id or get_app_id_from_env()).strip()
        if not app_id:
            print(
                "Set BMT_APP_ID or GH_APP_TEST_ID / GH_APP_PROD_ID (legacy GITHUB_APP_* also supported)",
                file=sys.stderr,
            )
            return 1

        key_path = (private_key_path or os.environ.get("BMT_APP_PRIVATE_KEY_PATH") or "").strip()
        if not key_path:
            print("Set BMT_APP_PRIVATE_KEY_PATH (path to app private key PEM)", file=sys.stderr)
            return 1

        private_key = Path(key_path).read_text()

        try:
            data = fetch_app_metadata(app_id, private_key)
        except urllib.error.HTTPError as e:
            print(e.read().decode(), file=sys.stderr)
            return 1

        if jq_path:
            extracted = extract_path(data, jq_path)
            data = extracted if extracted is not None else data

        print(json.dumps(data, indent=2))
        return 0


if __name__ == "__main__":
    app_id = (os.environ.get("BMT_APP_ID") or get_app_id_from_env()).strip()
    private_key_path = (os.environ.get("BMT_APP_PRIVATE_KEY_PATH") or "").strip()
    jq_path = (os.environ.get("BMT_JQ_PATH") or "").strip()
    raise SystemExit(
        GhAppPerms().run(
            app_id=app_id,
            private_key_path=private_key_path,
            jq_path=jq_path,
        )
    )
