"""Tests for plugin ``teardown`` ordering (mirrors :func:`gcp.image.runtime.execution.execute_leg`)."""

from __future__ import annotations

import pytest

from backend.runtime.sdk.plugin import BmtPlugin
from backend.runtime.sdk.results import PreparedAssets
from tests.support.fixtures.bmt_sdk import minimal_execution_context

pytestmark = pytest.mark.unit


class _TeardownProbe(BmtPlugin):
    plugin_name = "probe"
    api_version = "v1"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def prepare(self, context):
        self.calls.append("prepare")
        return self.prepared_assets_from_context(context)

    def execute(self, context, prepared_assets):
        self.calls.append("execute")
        raise RuntimeError("boom")

    def score(self, execution_result, baseline, context):
        self.calls.append("score")
        raise AssertionError("unreachable")

    def evaluate(self, score_result, baseline, context):
        self.calls.append("evaluate")
        raise AssertionError("unreachable")

    def teardown(self, context, prepared):
        self.calls.append("teardown")


def test_teardown_runs_after_prepare_when_execute_raises(tmp_path) -> None:
    ctx = minimal_execution_context(tmp_path)
    probe = _TeardownProbe()

    def _body() -> None:
        prepared = None
        try:
            prepared = probe.prepare(ctx)
            probe.execute(ctx, prepared)
        finally:
            if prepared is not None:
                probe.teardown(ctx, prepared)

    with pytest.raises(RuntimeError, match="boom"):
        _body()
    assert probe.calls == ["prepare", "execute", "teardown"]
