from __future__ import annotations

import json
import stat
import tempfile
from pathlib import Path

from bmt_sdk.results import CaseResult

from runtime.kardome_case_metrics import read_namuh_from_sidecar_json
from runtime.kardome_runparams import (
    KardomeRunparamsConfig,
    KardomeRunparamsExecutor,
    execution_mode_for_runparams_case_results,
)
from runtime.stdout_counter_parse import StdoutCounterParseConfig
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


def test_bmt_json_preferred_over_stdout(tmp_path: Path) -> None:
    (tmp_path / "ds").mkdir(parents=True)
    write_silence_wav(tmp_path / "ds" / "one.wav")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "logs").mkdir()

    runner = tmp_path / "fake_runner.py"
    runner.write_text(
        """#!/usr/bin/env python3
import json, pathlib, sys
cfg_path = pathlib.Path(sys.argv[1])
cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
out = pathlib.Path(cfg["USER_OUTPUT_PATH"])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(b"ok")
(out.with_suffix(".bmt.json")).write_text(
    json.dumps({"namuh_count": 4}),
    encoding="utf-8",
)
print("Hi NAMUH counter = 999")
""",
        encoding="utf-8",
    )
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)

    parsing = StdoutCounterParseConfig().model_dump(mode="python", exclude_none=True)
    ex = KardomeRunparamsExecutor(
        KardomeRunparamsConfig(
            runner_path=runner,
            template_path=_SK_TEMPLATE,
            dataset_root=tmp_path / "ds",
            runtime_root=tmp_path / "runtime",
            outputs_root=tmp_path / "outputs",
            logs_root=tmp_path / "logs",
            parsing=parsing,
        )
    )
    result = ex.run()
    assert result.execution_mode_used == "kardome_legacy_metrics_json"
    assert len(result.case_results) == 1
    row = result.case_results[0]
    assert row.status == "ok"
    assert row.metrics["namuh_count"] == 4.0
    assert row.artifacts.get("metric_source") == "metrics_json"
    assert row.artifacts.get("metrics_json_path", "").endswith(".bmt.json")


def test_stdout_fallback_when_no_sidecar(tmp_path: Path) -> None:
    (tmp_path / "ds").mkdir(parents=True)
    write_silence_wav(tmp_path / "ds" / "a.wav")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "logs").mkdir()

    runner = tmp_path / "fake_runner.py"
    runner.write_text(
        """#!/usr/bin/env python3
import json, pathlib, sys
cfg = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
out = pathlib.Path(cfg["USER_OUTPUT_PATH"])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(b"x")
print("Hi NAMUH counter = 5")
""",
        encoding="utf-8",
    )
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)

    parsing = StdoutCounterParseConfig().model_dump(mode="python", exclude_none=True)
    ex = KardomeRunparamsExecutor(
        KardomeRunparamsConfig(
            runner_path=runner,
            template_path=_SK_TEMPLATE,
            dataset_root=tmp_path / "ds",
            runtime_root=tmp_path / "runtime",
            outputs_root=tmp_path / "outputs",
            logs_root=tmp_path / "logs",
            parsing=parsing,
        )
    )
    result = ex.run()
    assert result.execution_mode_used == "kardome_legacy_stdout"
    row = result.case_results[0]
    assert row.status == "ok"
    assert row.metrics["namuh_count"] == 5.0
    assert row.artifacts.get("metric_source") == "stdout_log"


def _fake_runner_writes_sidecar_then_stdout(tmp_path: Path, *, sidecar_body: str) -> None:
    (tmp_path / "ds").mkdir(parents=True)
    write_silence_wav(tmp_path / "ds" / "x.wav")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "logs").mkdir()

    runner = tmp_path / "fake_runner.py"
    runner.write_text(
        f"""#!/usr/bin/env python3
import json, pathlib, sys
cfg = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
out = pathlib.Path(cfg["USER_OUTPUT_PATH"])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(b"x")
pathlib.Path(str(out.with_suffix(".bmt.json"))).write_text({sidecar_body!r}, encoding="utf-8")
print("Hi NAMUH counter = 6")
""",
        encoding="utf-8",
    )
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)

    parsing = StdoutCounterParseConfig().model_dump(mode="python", exclude_none=True)
    ex = KardomeRunparamsExecutor(
        KardomeRunparamsConfig(
            runner_path=runner,
            template_path=_SK_TEMPLATE,
            dataset_root=tmp_path / "ds",
            runtime_root=tmp_path / "runtime",
            outputs_root=tmp_path / "outputs",
            logs_root=tmp_path / "logs",
            parsing=parsing,
        )
    )
    result = ex.run()
    assert result.execution_mode_used == "kardome_legacy_stdout"
    assert result.case_results[0].metrics["namuh_count"] == 6.0
    assert result.case_results[0].artifacts.get("metric_source") == "stdout_log"


def test_malformed_sidecar_json_falls_back_to_stdout(tmp_path: Path) -> None:
    _fake_runner_writes_sidecar_then_stdout(tmp_path, sidecar_body="{not json")


def test_sidecar_json_without_counter_falls_back_to_stdout(tmp_path: Path) -> None:
    _fake_runner_writes_sidecar_then_stdout(tmp_path, sidecar_body='{"other": 1}')


def test_execution_mode_hybrid_when_mixed_sources() -> None:
    cases = [
        CaseResult("a.wav", Path("a.wav"), 0, "ok", {}, {"metric_source": "metrics_json"}),
        CaseResult("b.wav", Path("b.wav"), 0, "ok", {}, {"metric_source": "stdout_log"}),
    ]
    assert execution_mode_for_runparams_case_results(cases) == "kardome_legacy_hybrid_metrics"


def test_execution_mode_ignores_internal_case_ids() -> None:
    cases = [
        CaseResult("_dataset_", Path("x"), -1, "failed", {}, {}),
        CaseResult("a.wav", Path("a.wav"), 0, "ok", {}, {"metric_source": "stdout_log"}),
    ]
    assert execution_mode_for_runparams_case_results(cases) == "kardome_legacy_stdout"
