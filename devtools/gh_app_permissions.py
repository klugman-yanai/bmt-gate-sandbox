#!/usr/bin/env python3
"""
Fetch GitHub App metadata (e.g. permissions) using app JWT auth.

Requires: App ID (from GitHub App "About" on the app settings page),
          and the app's private key PEM file.

Usage:
  # With explicit app ID and key path:
  python devtools/gh_app_permissions.py --app-id 123456 --private-key secrets/dev/bmt-gate-sandbox.2026-02-19.private-key.pem

  # Or via env (e.g. GITHUB_APP_TEST_ID and key path):
  GITHUB_APP_TEST_ID=123456 python devtools/gh_app_permissions.py secrets/dev/bmt-gate-sandbox.2026-02-19.private-key.pem

  # Only print .permissions:
  python devtools/gh_app_permissions.py --app-id 123456 --private-key secrets/.../key.pem --jq '.permissions'
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import jwt as pyjwt
except ImportError:
    print("PyJWT required: uv pip install pyjwt cryptography", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Get GitHub App metadata (permissions) via JWT")
    parser.add_argument("private_key_path", nargs="?", help="Path to app private key PEM file")
    parser.add_argument("--app-id", help="GitHub App ID (numeric). Or set GITHUB_APP_TEST_ID / GITHUB_APP_PROD_ID")
    parser.add_argument("--private-key", dest="private_key_path_opt", metavar="PATH", help="Path to app private key PEM (alternative to positional)")
    parser.add_argument("--jq", metavar="JQ_PATH", help="Optional jq-style path to print (e.g. .permissions)")
    args = parser.parse_args()

    app_id = args.app_id
    if not app_id:
        import os

        app_id = os.environ.get("GITHUB_APP_TEST_ID") or os.environ.get("GITHUB_APP_PROD_ID") or ""
    if not app_id:
        print("Set --app-id or GITHUB_APP_TEST_ID / GITHUB_APP_PROD_ID", file=sys.stderr)
        sys.exit(1)

    key_path = args.private_key_path_opt or args.private_key_path
    if not key_path:
        print("Provide private key path (positional or --private-key)", file=sys.stderr)
        sys.exit(1)
    private_key = Path(key_path).read_text()

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": app_id,
    }
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
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(e.read().decode(), file=sys.stderr)
        sys.exit(1)

    if args.jq:
        path = args.jq.strip().lstrip(".")
        obj = data
        for part in path.split("."):
            if part:
                obj = obj.get(part)
        print(json.dumps(obj, indent=2))
    else:
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
