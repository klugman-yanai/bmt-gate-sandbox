from __future__ import annotations

import pytest
from bmtgate.clients import gcs
from google.api_core import exceptions as api_exceptions

pytestmark = pytest.mark.unit


def test_object_exists_raises_gcserror_on_infra_failure(monkeypatch) -> None:
    class FakeBlob:
        def exists(self) -> bool:
            raise api_exceptions.TooManyRequests("quota spike")

    class FakeBucket:
        def blob(self, path: str) -> FakeBlob:
            assert path == "projects/sk/kardome_runner"
            return FakeBlob()

    class FakeClient:
        def bucket(self, bucket_name: str) -> FakeBucket:
            assert bucket_name == "demo-bucket"
            return FakeBucket()

    def _fake_get_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr("bmtgate.clients.gcs._get_client", _fake_get_client)

    with pytest.raises(gcs.GcsError, match="Failed to check existence of gs://demo-bucket/projects/sk/kardome_runner"):
        gcs.object_exists("gs://demo-bucket/projects/sk/kardome_runner")


def test_create_json_if_absent_returns_false_when_receipt_already_exists(monkeypatch) -> None:
    class FakeBlob:
        def upload_from_string(self, data: str, if_generation_match: int) -> None:
            _ = (data, if_generation_match)
            raise api_exceptions.PreconditionFailed("already exists")

    class FakeBucket:
        def blob(self, path: str) -> FakeBlob:
            assert path == "triggers/dispatch/wf-1.json"
            return FakeBlob()

    class FakeClient:
        def bucket(self, bucket_name: str) -> FakeBucket:
            assert bucket_name == "demo-bucket"
            return FakeBucket()

    def _fake_get_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr("bmtgate.clients.gcs._get_client", _fake_get_client)

    assert gcs.create_json_if_absent("gs://demo-bucket/triggers/dispatch/wf-1.json", {"ok": True}) is False
