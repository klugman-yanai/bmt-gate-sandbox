"""Unit tests for GitHub App authentication module."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "deploy" / "code" / "lib"))
import github_auth  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture
def test_config() -> Iterator[str]:
    """Create a temporary test configuration file."""
    config_data = {
        "version": "1.0",
        "repositories": {
            "test-org/test-repo": {
                "repo_env": "test",
                "description": "Test repository",
                "secret_prefix": "GITHUB_APP_TEST",
                "enabled": True,
            },
            "prod-org/prod-repo": {
                "repo_env": "prod",
                "description": "Production repository",
                "secret_prefix": "GITHUB_APP_PROD",
                "enabled": True,
            },
            "no-prefix/no-prefix-repo": {
                "repo_env": "test",
                "description": "Missing secret prefix",
                "enabled": True,
            },
            "disabled-org/disabled-repo": {
                "repo_env": "disabled",
                "description": "Disabled repository",
                "secret_prefix": "GITHUB_APP_DISABLED",
                "enabled": False,
            },
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        config_path = f.name

    yield config_path

    Path(config_path).unlink(missing_ok=True)


class TestLoadGithubReposConfig:
    """Tests for load_github_repos_config()."""

    def test_load_valid_config(self, test_config: str) -> None:
        config = github_auth.load_github_repos_config(test_config)
        assert config is not None
        assert "repositories" in config
        assert "test-org/test-repo" in config["repositories"]

    def test_load_nonexistent_config(self) -> None:
        config = github_auth.load_github_repos_config("/nonexistent/path.json")
        assert config is None

    def test_load_invalid_json(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {")
            invalid_path = f.name

        try:
            config = github_auth.load_github_repos_config(invalid_path)
            assert config is None
        finally:
            Path(invalid_path).unlink(missing_ok=True)

    def test_load_missing_repositories_key(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"version": "1.0"}, f)
            invalid_path = f.name

        try:
            config = github_auth.load_github_repos_config(invalid_path)
            assert config is None
        finally:
            Path(invalid_path).unlink(missing_ok=True)


class TestListEnabledRepositories:
    """Tests for list_enabled_repositories()."""

    def test_list_enabled_repositories(self, test_config: str) -> None:
        repos = github_auth.list_enabled_repositories(test_config)
        assert repos is not None
        assert sorted(repos) == ["no-prefix/no-prefix-repo", "prod-org/prod-repo", "test-org/test-repo"]

    def test_list_enabled_repositories_returns_none_without_config(self) -> None:
        repos = github_auth.list_enabled_repositories("/nonexistent/path.json")
        assert repos is None


class TestResolveAuthForRepository:
    """Tests for resolve_auth_for_repository()."""

    def test_no_config_returns_none(self) -> None:
        token = github_auth.resolve_auth_for_repository(
            "any-repo/any-name",
            config_path="/nonexistent/path.json",
        )
        assert token is None

    def test_unknown_repository_returns_none(self, test_config: str) -> None:
        token = github_auth.resolve_auth_for_repository(
            "unknown-org/unknown-repo",
            config_path=test_config,
        )
        assert token is None

    def test_disabled_repository_returns_none(self, test_config: str) -> None:
        token = github_auth.resolve_auth_for_repository(
            "disabled-org/disabled-repo",
            config_path=test_config,
        )
        assert token is None

    def test_missing_secret_prefix_returns_none(self, test_config: str) -> None:
        token = github_auth.resolve_auth_for_repository(
            "no-prefix/no-prefix-repo",
            config_path=test_config,
        )
        assert token is None

    def test_missing_app_secrets_returns_none(self, test_config: str) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            token = github_auth.resolve_auth_for_repository(
                "test-org/test-repo",
                config_path=test_config,
            )
            assert token is None

    def test_partial_app_secrets_returns_none(self, test_config: str) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "GITHUB_APP_TEST_ID": "12345",
                "GITHUB_APP_TEST_INSTALLATION_ID": "67890",
            },
            clear=True,
        ):
            token = github_auth.resolve_auth_for_repository(
                "test-org/test-repo",
                config_path=test_config,
            )
            assert token is None

    def test_empty_repository_returns_none(self, test_config: str) -> None:
        token = github_auth.resolve_auth_for_repository("", config_path=test_config)
        assert token is None

    @mock.patch("github_auth.get_installation_token_from_app")
    def test_successful_app_auth(self, mock_get_token: mock.Mock, test_config: str) -> None:
        mock_get_token.return_value = "test-app-token"
        with mock.patch.dict(
            os.environ,
            {
                "GITHUB_APP_TEST_ID": "12345",
                "GITHUB_APP_TEST_INSTALLATION_ID": "67890",
                "GITHUB_APP_TEST_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
            },
            clear=True,
        ):
            token = github_auth.resolve_auth_for_repository(
                "test-org/test-repo",
                config_path=test_config,
            )
            assert token == "test-app-token"
            mock_get_token.assert_called_once()

    @mock.patch("github_auth.get_installation_token_from_app")
    def test_app_auth_failure_returns_none(self, mock_get_token: mock.Mock, test_config: str) -> None:
        mock_get_token.return_value = None
        with mock.patch.dict(
            os.environ,
            {
                "GITHUB_APP_TEST_ID": "12345",
                "GITHUB_APP_TEST_INSTALLATION_ID": "67890",
                "GITHUB_APP_TEST_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
            },
            clear=True,
        ):
            token = github_auth.resolve_auth_for_repository(
                "test-org/test-repo",
                config_path=test_config,
            )
            assert token is None


class TestResolveConfigPath:
    """Tests for _resolve_config_path()."""

    def test_explicit_path_wins(self, test_config: str) -> None:
        resolved = github_auth._resolve_config_path(test_config)
        assert resolved == Path(test_config)

    def test_env_override_wins(self, test_config: str) -> None:
        with mock.patch.dict(os.environ, {"BMT_GITHUB_REPOS_CONFIG": test_config}, clear=True):
            resolved = github_auth._resolve_config_path(None)
        assert resolved == Path(test_config)

    def test_default_path_exists(self) -> None:
        resolved = github_auth._resolve_config_path(None)
        assert resolved.name == "github_repos.json"


class TestGetInstallationTokenFromApp:
    """Tests for get_installation_token_from_app()."""

    def test_missing_pyjwt_returns_none(self) -> None:
        with mock.patch("github_auth.HAS_JWT", new=False):
            token = github_auth.get_installation_token_from_app(
                "12345",
                "67890",
                "test-key",
            )
            assert token is None

    def test_missing_credentials_returns_none(self) -> None:
        assert github_auth.get_installation_token_from_app("", "67890", "key") is None
        assert github_auth.get_installation_token_from_app("12345", "", "key") is None
        assert github_auth.get_installation_token_from_app("12345", "67890", "") is None

    @mock.patch("github_auth.HAS_JWT", new=True)
    @mock.patch("github_auth.jwt")
    @mock.patch("github_auth.urllib.request.urlopen")
    def test_successful_token_exchange(self, mock_urlopen: mock.Mock, mock_jwt: mock.Mock) -> None:
        mock_jwt.encode.return_value = "mock-jwt-token"
        mock_response = mock.MagicMock()
        mock_response.status = 201
        mock_response.read.return_value = json.dumps({"token": "test-installation-token"}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        token = github_auth.get_installation_token_from_app(
            "12345",
            "67890",
            "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        )

        assert token == "test-installation-token"
        mock_jwt.encode.assert_called_once()

    @mock.patch("github_auth.HAS_JWT", new=True)
    @mock.patch("github_auth.jwt")
    @mock.patch("github_auth.urllib.request.urlopen")
    def test_api_error_returns_none(self, mock_urlopen: mock.Mock, mock_jwt: mock.Mock) -> None:
        mock_jwt.encode.return_value = "mock-jwt-token"
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            "https://api.github.com",
            401,
            "Unauthorized",
            None,  # type: ignore[arg-type]
            None,
        )

        token = github_auth.get_installation_token_from_app(
            "12345",
            "67890",
            "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        )

        assert token is None
