from __future__ import annotations

import json
import stat
import tempfile
from pathlib import Path

from bmt_sdk.results import CaseResult

from runtime.kardome_case_metrics import read_metric_from_sidecar_json, read_namuh_from_sidecar_json
from runtime.kardome_runparams import (
    KardomeRunparamsConfig,
    KardomeRunparamsExecutor,
    execution_mode_for_runparams_case_results,
)
from tests._support.minimal_wav import write_silence_wav

_REPO = Path(__file__).resolve().parents[2]
_SK_TEMPLATE = _REPO / "runtime/assets/sk_kardome_input_template.json"


def test_read_namuh_krdm_bmt_case_metrics_v1_shape() -> None:
    import shutil

    tmp = Path(tempfile.mkdtemp(prefix="bmt-metrics-"))
    try:
        wav_out = tmp / "case.wav"
        side = wav_out.with_suffix(".bmt.json")
        side.write_text(
            json.dumps(
                {
                    "hi_namuh_count": 9,
                    "namuh_count": 9,
                    "schema": "krdm_bmt_case_metrics_v1",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        n, p = read_namuh_from_sidecar_json(wav_out)
        assert n == 9 and p == side
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_namuh_bmt_json_suffix() -> None:
    import shutil

    tmp = Path(tempfile.mkdtemp(prefix="bmt-metrics-"))
    try:
        wav_out = tmp / "sub" / "case.wav"
        wav_out.parent.mkdir(parents=True)
        side = wav_out.with_suffix(".bmt.json")
        side.write_text(json.dumps({"namuh_count": 7}) + "\n", encoding="utf-8")
        n, p = read_namuh_from_sidecar_json(wav_out)
        assert n == 7 and p == side
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_namuh_bmt_result_stem() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bmt-metrics-"))
    try:
        wav_out = tmp / "case.wav"
        side = tmp / "case_bmt_result.json"
        side.write_text(json.dumps({"metrics": {"hi_namuh_count": 2}}), encoding="utf-8")
        n, p = read_namuh_from_sidecar_json(wav_out)
        assert n == 2 and p == side
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def test_read_metric_from_sidecar_json_custom_key() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bmt-metrics-"))
    try:
        wav_out = tmp / "case.wav"
        side = wav_out.with_suffix(".bmt.json")
        side.write_text(json.dumps({"metrics": {"wake_hits": 3.5}}), encoding="utf-8")
        value, path = read_metric_from_sidecar_json(wav_out, metric_keys=("wake_hits",))
        assert value == 3.5
        assert path == side
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _runner_script_body(sidecar_body: str | None) -> str:
    writer = (
        ""
        if sidecar_body is None
        else f"pathlib.Path(str(out.with_suffix('.bmt.json'))).write_text({sidecar_body!r}, encoding='utf-8')"
    )
    return f"""#!/usr/bin/env python3
import pathlib
import sys

def arg(flag):
    idx = sys.argv.index(flag)
    return sys.argv[idx + 1]

out = pathlib.Path(arg("--user-output"))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(b"ok")
{writer}
print("Hi NAMUH counter = 999")
"""


def _make_executor(
    tmp_path: Path,
    runner_body: str,
    *,
    metric_name: str = "namuh_count",
    metric_json_keys: tuple[str, ...] = ("namuh_count", "hi_namuh_count", "namuh", "hi_namuh"),
) -> KardomeRunparamsExecutor:
    (tmp_path / "ds").mkdir(parents=True)
    write_silence_wav(tmp_path / "ds" / "one.wav")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "logs").mkdir()

    runner = tmp_path / "fake_runner.py"
    runner.write_text(runner_body, encoding="utf-8")
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)

    return KardomeRunparamsExecutor(
        KardomeRunparamsConfig(
            runner_path=runner,
            template_path=_SK_TEMPLATE,
            dataset_root=tmp_path / "ds",
            runtime_root=tmp_path / "runtime",
            outputs_root=tmp_path / "outputs",
            logs_root=tmp_path / "logs",
            parsing={},
            metric_name=metric_name,
            metric_json_keys=metric_json_keys,
        )
    )


def test_metrics_json_is_required(tmp_path: Path) -> None:
    ex = _make_executor(tmp_path, _runner_script_body(sidecar_body=None))
    result = ex.run()
    assert result.execution_mode_used == "kardome_legacy_metrics_json_missing"
    row = result.case_results[0]
    assert row.status == "failed"
    assert row.error == "metrics_json_missing"
    assert row.artifacts.get("metric_source") == "none"


def test_malformed_sidecar_json_fails_case(tmp_path: Path) -> None:
    ex = _make_executor(tmp_path, _runner_script_body(sidecar_body="{not json"))
    result = ex.run()
    row = result.case_results[0]
    assert row.status == "failed"
    assert row.error == "metrics_json_missing"


def test_sidecar_json_without_counter_fails_case(tmp_path: Path) -> None:
    ex = _make_executor(tmp_path, _runner_script_body(sidecar_body='{"other": 1}'))
    result = ex.run()
    row = result.case_results[0]
    assert row.status == "failed"
    assert row.error == "metrics_json_missing"


def test_execution_mode_json_only() -> None:
    cases = [
        CaseResult("a.wav", Path("a.wav"), 0, "ok", {}, {"metric_source": "metrics_json"}),
        CaseResult("_dataset_", Path("x"), -1, "failed", {}, {}),
    ]
    assert execution_mode_for_runparams_case_results(cases) == "kardome_legacy_metrics_json"


def test_executor_uses_configured_metric_name_and_keys(tmp_path: Path) -> None:
    ex = _make_executor(
        tmp_path,
        _runner_script_body(sidecar_body='{"metrics": {"wake_hits": 11}}'),
        metric_name="wake_hits",
        metric_json_keys=("wake_hits",),
    )
    result = ex.run()
    row = result.case_results[0]
    assert row.status == "ok"
    assert row.metrics == {"wake_hits": 11.0}
