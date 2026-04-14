"""GitHub App authentication for workflow and Cloud Run reporting."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from github import GithubIntegration

from gcp.image.config.constants import HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class _PyJWTRS256Encode(Protocol):
    """Subset of :func:`jwt.encode` used for GitHub App JWTs."""

    def __call__(
        self,
        payload: dict[str, int | str],
        key: str,
        *,
        algorithm: str,
    ) -> str: ...


_jwt_encode: _PyJWTRS256Encode | None = None
try:
    import jwt as _jwt_module

    _jwt_encode = _jwt_module.encode
except ImportError:
    pass

HAS_JWT = _jwt_encode is not None

_JWT_ENCODE_ERRORS: tuple[type[BaseException], ...] = (ValueError, TypeError, OSError)
if HAS_JWT:
    from jwt.exceptions import PyJWTError

    _JWT_ENCODE_ERRORS = (*_JWT_ENCODE_ERRORS, PyJWTError)

PRIMARY_PROFILE = "primary"
DEV_PROFILE = "dev"
ORG_OWNER = "Kardome-org"


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


def encode_github_app_jwt_rs256(payload: dict[str, int | str], private_key: str) -> str:
    """Encode an RS256 JWT for GitHub App API calls. Raises if PyJWT is not installed."""
    if _jwt_encode is None:
        raise RuntimeError("PyJWT is required")
    return _jwt_encode(payload, private_key, algorithm="RS256")


def get_installation_token_from_app(
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
    if not app_id or not installation_id or not private_key:
        return None

    try:
        inst_id = int(str(installation_id).strip())
    except ValueError:
        logger.warning("GitHub App installation_id is not a valid integer: %r", installation_id)
        return None

    try:
        integration = GithubIntegration(
            integration_id=app_id,
            private_key=private_key,
            timeout=int(HTTP_TIMEOUT),
        )
        auth = integration.get_access_token(inst_id)
        return str(auth.token) if auth.token else None
    except Exception as e:
        logger.warning(
            "GitHub App installation token via PyGithub failed: %s",
            type(e).__name__,
            exc_info=True,
        )
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
