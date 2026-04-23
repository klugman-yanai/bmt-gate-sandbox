# SK `kardome_runner` runtime (isolation note)

This repo’s **BMT gate and Cloud Run path** stay stable on **`ci/check-bmt-gate`** using the
**published runner + `runtime/` + `plugins/`** contract. Treat **SK runner binary behaviour**
(tinywav, ONNX/TFLite, counters) as **orthogonal**: debug in **core-main**, not by duplicating
ad-hoc local trees outside the supported PR → **`ci/check-bmt-gate`** pipeline.

## Where SK tuning lives (core-main)

For **SK** builds, `kardome_init_params()` calls `getActiveParameters()` implemented in
**`Runners/params/src/run_params_SK.c`** (AFE/KWS `krdmSetParam` values). That is the
**authoritative** tuning surface for the product preset.

**JSON from BMT** (`parseJsonCalib` in `Runners/utils/src/utils.c`) still supplies **paths**
(`MICS_PATH`, `REF_PATH`, outputs, zones, `KWS_CONFIG` switches, etc.). Do not reintroduce
large “tuning blobs” in repo JSON; extend **`run_params_SK.c`** in core-main when behaviour
must change.

In **bmt-gcloud**, the per-case driver that writes that JSON and invokes ``kardome_runner`` is
**`runtime/kardome_runparams.py`** (``KardomeRunparamsExecutor``) — it is **not** a second
source of SK AFE/KWS numbers; it only supplies paths and manifest ``enable_overrides``.

## WAV / tinywav

Multi-channel BMT WAVs are often **WAVE_FORMAT_EXTENSIBLE**; the runner’s **tinywav** reader
in core-main expects **classic PCM format 1** for reliable parsing. If you transcode with
`ffmpeg -f s16le`, re-mux to a standard PCM WAVE (format tag 1, 16-byte `fmt` chunk) before
feeding the runner — see **`Runners/utils/src/tinywav.c`** in core-main.

## CI stability

- **Primary BMT validation:** PR into **`ci/check-bmt-gate`** → `build-and-test-dev.yml` →
  handoff + cloud BMT (see **`.github/README.md`**).

## SK scoring: NAMUH zeros vs pass/fail

- **`false_alarms`** (`plugin_config.comparison`: **`lte`**, lower is better): an average
  **`namuh_count` of `0` on passing cases is a good outcome** — the leg may **PASS** on
  bootstrap (`bootstrap_without_baseline`) the first time.
- **`false_rejects`** (`comparison`: **`gte`**, higher is better): **all passing cases at
  NAMUH `0`** is treated as a **likely runner/metrics bug**, but the gate **does not block
  the PR**: the leg **PASSes** with reason **`all_zero_keyword_hits_warn`** and a
  **`summary.warning`** string for triage. With a baseline, normal tolerance comparison still
  applies.

## Remote / bucket “junk” from experiments

This repository **cannot** delete arbitrary GCS objects without your credentials. If ad-hoc
uploads or scratch prefixes were created during experiments, clean them with your normal
bucket tools (e.g. `gcloud storage rm` on the known prefix) or lifecycle rules on a dedicated
scratch prefix. **Do not** delete `sk/runners/sk_gcc_release/kardome_runner` or manifest paths
unless you intend to break CI preseed assumptions.
