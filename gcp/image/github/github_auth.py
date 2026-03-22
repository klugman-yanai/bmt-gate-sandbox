"""GitHub App authentication for workflow and Cloud Run reporting."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass

# Optional PyJWT import (graceful degradation if not installed)
try:
    import jwt

    HAS_JWT = True
except ImportError:
    HAS_JWT = False

from gcp.image.config.constants import GITHUB_API_VERSION, HTTP_TIMEOUT, JWT_CLOCK_SKEW_SEC, JWT_LIFETIME_SEC

PRIMARY_PROFILE = "primary"
DEV_PROFILE = "dev"
ORG_OWNER = "Kardome-org"


def github_api_headers(token: str, *, content_type: str | None = None) -> dict[str, str]:
    """Return standard GitHub API request headers for the given bearer token."""
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


@dataclass(frozen=True, slots=True)
class GitHubAppCredentials:
    app_id: str
    installation_id: str
    private_key: str


def _resolve_env_value(*, env: Mapping[str, str], canonical_name: str) -> str:
    value = str(env.get(canonical_name, "")).strip()
    if value:
        return value
    alias_name = canonical_name.replace("GITHUB_", "GH_", 1)
    return str(env.get(alias_name, "")).strip()


def github_app_profile_for_repository(repository: str) -> str:
    owner = repository.partition("/")[0].strip()
    if owner == ORG_OWNER:
        return PRIMARY_PROFILE
    return DEV_PROFILE if owner else PRIMARY_PROFILE


def _credential_names_for_profile(profile: str) -> tuple[str, str, str]:
    if profile == DEV_PROFILE:
        return (
            "GITHUB_APP_DEV_ID",
            "GITHUB_APP_DEV_INSTALLATION_ID",
            "GITHUB_APP_DEV_PRIVATE_KEY",
        )
    return (
        "GITHUB_APP_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY",
    )


def get_installation_token_from_app(  # noqa: PLR0911
    app_id: str,
    installation_id: str,
    private_key: str,
) -> str | None:
    """
    Generate installation token from GitHub App credentials.

    Args:
        app_id: GitHub App ID
        installation_id: GitHub App Installation ID
        private_key: GitHub App private key (PEM format)

    Returns:
        Installation token string, or None on failure
    """
    if not HAS_JWT:
        return None

    if not app_id or not installation_id or not private_key:
        return None

    try:
        # Generate JWT
        now = int(time.time())
        payload = {
            "iat": now - JWT_CLOCK_SKEW_SEC,
            "exp": now + JWT_LIFETIME_SEC,
            "iss": app_id,
        }
        jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

        # Exchange JWT for installation token
        url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        req = urllib.request.Request(
            url,
            data=b"",
            headers=github_api_headers(jwt_token),
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            if resp.status != 201:
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("token")

    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return None
    except (json.JSONDecodeError, KeyError):
        return None
    except Exception:  # Catch PyJWT errors and any other unexpected errors
        return None


def load_github_app_credentials(
    repository: str,
    env: Mapping[str, str] | None = None,
) -> GitHubAppCredentials | None:
    resolved_env = env or os.environ
    credential_names = _credential_names_for_profile(github_app_profile_for_repository(repository))
    app_id = _resolve_env_value(env=resolved_env, canonical_name=credential_names[0])
    installation_id = _resolve_env_value(env=resolved_env, canonical_name=credential_names[1])
    private_key = _resolve_env_value(env=resolved_env, canonical_name=credential_names[2])
    if not (app_id and installation_id and private_key):
        return None
    return GitHubAppCredentials(
        app_id=app_id,
        installation_id=installation_id,
        private_key=private_key,
    )


def resolve_github_app_token(
    repository: str,
    env: Mapping[str, str] | None = None,
) -> str | None:
    credentials = load_github_app_credentials(repository, env)
    if credentials is None:
        return None
    return get_installation_token_from_app(
        credentials.app_id,
        credentials.installation_id,
        credentials.private_key,
    )
