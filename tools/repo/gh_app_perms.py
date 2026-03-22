#!/usr/bin/env python3
"""Fetch GitHub App metadata (e.g. permissions) using app JWT auth."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from shutil import which

import jwt as pyjwt

from gcp.image.config.constants import JWT_CLOCK_SKEW_SEC, JWT_LIFETIME_SEC
from gcp.image.github.github_auth import (
    DEV_PROFILE,
    PRIMARY_PROFILE,
    github_api_headers,
    github_app_profile_for_repository,
)


def _repository_slug() -> str:
    repository = (os.environ.get("BMT_GITHUB_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if "/" in repository:
        return repository
    if which("gh") is None:
        return ""
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        capture_output=True,
        text=True,
        check=False,
    )
    slug = result.stdout.strip()
    return slug if result.returncode == 0 and "/" in slug else ""


def _app_profile() -> str:
    explicit = (os.environ.get("BMT_GITHUB_APP_PROFILE") or "").strip().lower()
    if explicit in {PRIMARY_PROFILE, DEV_PROFILE}:
        return explicit
    return github_app_profile_for_repository(_repository_slug())


def get_app_id_from_env() -> str:
    if _app_profile() == DEV_PROFILE:
        return (os.environ.get("GITHUB_APP_DEV_ID") or os.environ.get("GH_APP_DEV_ID") or "").strip()
    return (os.environ.get("GITHUB_APP_ID") or os.environ.get("GH_APP_ID") or "").strip()


def get_private_key_path_from_env() -> str:
    if _app_profile() == DEV_PROFILE:
        return (
            os.environ.get("GITHUB_APP_DEV_PRIVATE_KEY_PATH")
            or os.environ.get("GH_APP_DEV_PRIVATE_KEY_PATH")
            or os.environ.get("BMT_APP_PRIVATE_KEY_PATH")
            or ""
        ).strip()
    return (
        os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
        or os.environ.get("GH_APP_PRIVATE_KEY_PATH")
        or os.environ.get("BMT_APP_PRIVATE_KEY_PATH")
        or ""
    ).strip()


def fetch_app_metadata(app_id: str, private_key: str) -> dict:
    now = int(time.time())
    payload = {"iat": now - JWT_CLOCK_SKEW_SEC, "exp": now + JWT_LIFETIME_SEC, "iss": app_id}
    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    req = urllib.request.Request(
        "https://api.github.com/app",
        headers=github_api_headers(token),
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
                "Set GITHUB_APP_ID / GITHUB_APP_DEV_ID for the current repository profile.",
                file=sys.stderr,
            )
            return 1

        key_path = (private_key_path or get_private_key_path_from_env()).strip()
        if not key_path:
            print(
                "Set GITHUB_APP_PRIVATE_KEY_PATH or GITHUB_APP_DEV_PRIVATE_KEY_PATH (path to app private key PEM).",
                file=sys.stderr,
            )
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
    private_key_path = (os.environ.get("BMT_APP_PRIVATE_KEY_PATH") or get_private_key_path_from_env() or "").strip()
    jq_path = (os.environ.get("BMT_JQ_PATH") or "").strip()
    raise SystemExit(
        GhAppPerms().run(
            app_id=app_id,
            private_key_path=private_key_path,
            jq_path=jq_path,
        )
    )
