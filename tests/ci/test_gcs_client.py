from __future__ import annotations

import pytest
from bmtgate.clients import gcs

pytestmark = pytest.mark.unit


def test_object_exists_raises_gcserror_on_infra_failure(monkeypatch) -> None:
    class FakeBlob:
        def exists(self) -> bool:
            raise RuntimeError("quota spike")

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
