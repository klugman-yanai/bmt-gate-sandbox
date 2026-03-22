"""Unit tests for GitHub App authentication module."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from gcp.image.github import github_auth

pytestmark = pytest.mark.unit


class TestGithubAppProfile:
    def test_org_repository_uses_primary_profile(self) -> None:
        assert github_auth.github_app_profile_for_repository("Kardome-org/core-main") == "primary"

    def test_non_org_repository_uses_dev_profile(self) -> None:
        assert github_auth.github_app_profile_for_repository("klugman-yanai/bmt-gcloud") == "dev"

    def test_empty_repository_defaults_to_primary(self) -> None:
        assert github_auth.github_app_profile_for_repository("") == "primary"


class TestLoadGithubAppCredentials:
    """Tests for load_github_app_credentials()."""

    def test_missing_primary_credentials_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_APP_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_INSTALLATION_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)

        assert github_auth.load_github_app_credentials("Kardome-org/core-main") is None

    def test_partial_primary_credentials_return_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "67890")
        monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)

        assert github_auth.load_github_app_credentials("Kardome-org/core-main") is None

    def test_loads_primary_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "67890")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "private-key")

        credentials = github_auth.load_github_app_credentials("Kardome-org/core-main")

        assert credentials is not None
        assert credentials.app_id == "12345"
        assert credentials.installation_id == "67890"
        assert credentials.private_key == "private-key"

    def test_primary_alias_credentials_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GH_APP_ID", "12345")
        monkeypatch.setenv("GH_APP_INSTALLATION_ID", "67890")
        monkeypatch.setenv("GH_APP_PRIVATE_KEY", "private-key")
        monkeypatch.delenv("GITHUB_APP_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_INSTALLATION_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)

        credentials = github_auth.load_github_app_credentials("Kardome-org/core-main")

        assert credentials is not None
        assert credentials.app_id == "12345"
        assert credentials.installation_id == "67890"
        assert credentials.private_key == "private-key"

    def test_primary_canonical_credentials_win_over_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "canonical-id")
        monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "canonical-installation")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "canonical-key")
        monkeypatch.setenv("GH_APP_ID", "alias-id")
        monkeypatch.setenv("GH_APP_INSTALLATION_ID", "alias-installation")
        monkeypatch.setenv("GH_APP_PRIVATE_KEY", "alias-key")

        credentials = github_auth.load_github_app_credentials("Kardome-org/core-main")

        assert credentials is not None
        assert credentials.app_id == "canonical-id"
        assert credentials.installation_id == "canonical-installation"
        assert credentials.private_key == "canonical-key"

    def test_loads_dev_credentials_for_non_org_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_DEV_ID", "dev-id")
        monkeypatch.setenv("GITHUB_APP_DEV_INSTALLATION_ID", "dev-installation")
        monkeypatch.setenv("GITHUB_APP_DEV_PRIVATE_KEY", "dev-private-key")

        credentials = github_auth.load_github_app_credentials("klugman-yanai/bmt-gcloud")

        assert credentials is not None
        assert credentials.app_id == "dev-id"
        assert credentials.installation_id == "dev-installation"
        assert credentials.private_key == "dev-private-key"

    def test_dev_alias_credentials_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GH_APP_DEV_ID", "dev-id")
        monkeypatch.setenv("GH_APP_DEV_INSTALLATION_ID", "dev-installation")
        monkeypatch.setenv("GH_APP_DEV_PRIVATE_KEY", "dev-private-key")
        monkeypatch.delenv("GITHUB_APP_DEV_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_DEV_INSTALLATION_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_DEV_PRIVATE_KEY", raising=False)

        credentials = github_auth.load_github_app_credentials("klugman-yanai/bmt-gcloud")

        assert credentials is not None
        assert credentials.app_id == "dev-id"
        assert credentials.installation_id == "dev-installation"
        assert credentials.private_key == "dev-private-key"


class TestResolveGithubAppToken:
    """Tests for resolve_github_app_token()."""

    def test_missing_credentials_return_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_APP_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_INSTALLATION_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)

        assert github_auth.resolve_github_app_token("Kardome-org/core-main") is None

    @mock.patch("gcp.image.github.github_auth.get_installation_token_from_app")
    def test_successful_primary_app_auth(self, mock_get_token: mock.Mock, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_get_token.return_value = "test-app-token"
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "67890")
        monkeypatch.setenv(
            "GITHUB_APP_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
        )

        token = github_auth.resolve_github_app_token("Kardome-org/core-main")

        assert token == "test-app-token"
        mock_get_token.assert_called_once_with(
            "12345",
            "67890",
            "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        )

    @mock.patch("gcp.image.github.github_auth.get_installation_token_from_app")
    def test_successful_dev_app_auth(self, mock_get_token: mock.Mock, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_get_token.return_value = "dev-app-token"
        monkeypatch.setenv("GITHUB_APP_DEV_ID", "dev-id")
        monkeypatch.setenv("GITHUB_APP_DEV_INSTALLATION_ID", "dev-installation")
        monkeypatch.setenv("GITHUB_APP_DEV_PRIVATE_KEY", "dev-private-key")

        token = github_auth.resolve_github_app_token("klugman-yanai/bmt-gcloud")

        assert token == "dev-app-token"
        mock_get_token.assert_called_once_with("dev-id", "dev-installation", "dev-private-key")

    @mock.patch("gcp.image.github.github_auth.get_installation_token_from_app")
    def test_app_auth_failure_returns_none(self, mock_get_token: mock.Mock, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_get_token.return_value = None
        monkeypatch.setenv("GITHUB_APP_DEV_ID", "dev-id")
        monkeypatch.setenv("GITHUB_APP_DEV_INSTALLATION_ID", "dev-installation")
        monkeypatch.setenv("GITHUB_APP_DEV_PRIVATE_KEY", "dev-private-key")

        assert github_auth.resolve_github_app_token("klugman-yanai/bmt-gcloud") is None


class TestGetInstallationTokenFromApp:
    """Tests for get_installation_token_from_app()."""

    def test_missing_pyjwt_returns_none(self) -> None:
        with mock.patch("gcp.image.github.github_auth.HAS_JWT", new=False):
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

    @mock.patch("gcp.image.github.github_auth.HAS_JWT", new=True)
    @mock.patch("gcp.image.github.github_auth._jwt_encode")
    @mock.patch("gcp.image.github.github_auth.urllib.request.urlopen")
    def test_successful_token_exchange(self, mock_urlopen: mock.Mock, mock_jwt_encode: mock.Mock) -> None:
        mock_jwt_encode.return_value = "mock-jwt-token"
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
        mock_jwt_encode.assert_called_once()

    @mock.patch("gcp.image.github.github_auth.HAS_JWT", new=True)
    @mock.patch("gcp.image.github.github_auth._jwt_encode")
    @mock.patch("gcp.image.github.github_auth.urllib.request.urlopen")
    def test_api_error_returns_none(self, mock_urlopen: mock.Mock, mock_jwt_encode: mock.Mock) -> None:
        mock_jwt_encode.return_value = "mock-jwt-token"
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
