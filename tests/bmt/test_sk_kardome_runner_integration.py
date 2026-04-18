"""Integration: real ``kardome_runner`` + SK aggregation (legacy stdout only).

Same path as production when adaptive falls through to legacy: ``LegacyKardomeStdoutExecutor``
(JSON config per WAV, stdout to log, counter from manifest ``plugin_config``). Batch
runner is out of scope for this module. Parsing is driven by ``runner_integration_contract.json``.

The runner in git may be 644; tests copy it to a temp dir and chmod +x before invoking.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from runtime.legacy_kardome import LegacyKardomeStdoutConfig, LegacyKardomeStdoutExecutor
from runtime.stdout_counter_parse import StdoutCounterParseConfig
from tests._support.minimal_wav import write_silence_wav
from tests.sk_runner_repo_paths import KARDOME_INPUT_TEMPLATE, REPO_ROOT, SK_KARDOME_RUNNER, SK_LIBKARDOME_SO

_SK_PROJECT = REPO_ROOT / "plugins/projects/sk"
_CONTRACT = _SK_PROJECT / "runner_integration_contract.json"


def _parsing_from_contract() -> dict[str, object]:
    contract = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    rel = str(contract.get("bmt_manifest_json", "false_alarms.json")).strip()
    manifest_path = _SK_PROJECT / rel
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_cfg = data.get("plugin_config", {})
    if not isinstance(plugin_cfg, dict):
        raise TypeError(f"{manifest_path}: plugin_config must be an object")
    return StdoutCounterParseConfig.model_validate(plugin_cfg).model_dump(mode="python", exclude_none=True)


def _import_sk_aggregate():
    sk_src = str(_SK_PROJECT)
    if sk_src not in sys.path:
        sys.path.insert(0, sk_src)
    from sk_scoring_policy import aggregate_mean_ok_cases

    return aggregate_mean_ok_cases


@pytest.mark.integration
def test_kardome_runner_executes_and_scores_aggregate() -> None:
    assert SK_KARDOME_RUNNER.is_file() and SK_LIBKARDOME_SO.is_file()

    tmp = Path(tempfile.mkdtemp(prefix="bmt-kardome-smoke-"))
    prev_ld = os.environ.get("LD_LIBRARY_PATH")
    try:
        runner = tmp / "kardome_runner"
        shutil.copy2(SK_KARDOME_RUNNER, runner)
        runner.chmod(0o755)
        shutil.copy2(SK_LIBKARDOME_SO, tmp / "libKardome.so")

        ds = tmp / "ds"
        ds.mkdir()
        write_silence_wav(ds / "one.wav")
        write_silence_wav(ds / "two.wav")

        runtime = tmp / "runtime"
        outputs = tmp / "outputs"
        logs = tmp / "logs"
        for p in (runtime, outputs, logs):
            p.mkdir(parents=True, exist_ok=True)

        prefix = str(tmp)
        os.environ["LD_LIBRARY_PATH"] = f"{prefix}:{prev_ld}" if prev_ld else prefix

        parsing = _parsing_from_contract()
        ex = LegacyKardomeStdoutExecutor(
            LegacyKardomeStdoutConfig(
                runner_path=runner,
                template_path=KARDOME_INPUT_TEMPLATE,
                dataset_root=ds,
                runtime_root=runtime,
                outputs_root=outputs,
                logs_root=logs,
                parsing=parsing,
            )
        )
        result = ex.run()

        assert result.execution_mode_used == "kardome_legacy_stdout"
        assert len(result.case_results) == 2, result.case_results
        for row in result.case_results:
            assert row.status == "ok", (row.case_id, row.exit_code, row.error)
            assert row.exit_code == 0, (row.case_id, row.error)

        aggregate_mean_ok_cases = _import_sk_aggregate()
        agg = aggregate_mean_ok_cases(result.case_results)
        expected = sum(float(r.metrics.get("namuh_count", 0.0)) for r in result.case_results) / len(result.case_results)
        assert isinstance(agg, float)
        assert agg == pytest.approx(expected)
    finally:
        if prev_ld is None:
            os.environ.pop("LD_LIBRARY_PATH", None)
        else:
            os.environ["LD_LIBRARY_PATH"] = prev_ld
        shutil.rmtree(tmp, ignore_errors=True)
