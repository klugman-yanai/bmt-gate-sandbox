# kardome_runner SIGSEGV — Root Cause and Fix

**Date:** 2026-03-16
**Component:** `core-main` — `Kardome/ai_models/Common/src/ai_model.cc`
**Severity:** Intermittent crash (non-deterministic SIGSEGV)

## How the bug was encountered

During Cloud Run job execution, `kardome_runner` v1.1.14 crashed with `SIGSEGV` (signal 11) near the end of processing long audio files (~17 minutes). The crash was non-deterministic: the same binary, libraries, config, and WAV file would sometimes complete successfully (exit 0 with TF Lite errors logged) and sometimes crash hard.

Cloud Run logs showed:

```
run_file FAILED exit=-11 sig=11 wav=.../SK_WuW_A_0_D_2.6_H_70_S_60_T_cafe_N_50_E_up.wav
```

The runner's own stderr contained:

```
ERROR: Invalid tensor index 0 (not in [0, -1002397952))
ERROR: Node number 2963 (RESHAPE) failed to invoke.
```

The corrupted tensor count (`-1002397952` / `0xC45E0000`) indicated heap memory corruption, not a logic error.

## How to reproduce

1. Build `kardome_runner` + `libKardome.so` for SK (`TFLITE=1`, `KWS_USE_INTERPOLATION=true`, `D_USE_IDENTIFICATION_THREAD=true`).
2. Run against a long WAV file (17+ min) with KWS enabled:

    ```bash
    LD_LIBRARY_PATH=/path/to/libs ./kardome_runner /path/to/config.json
    ```

3. Repeat 5-10 times. Some runs will exit 0 (with `Invalid tensor index` errors in stderr), others will SIGSEGV.

The crash is heap-layout-dependent — ASLR, thread scheduling, and allocator behavior determine whether the corruption lands on a critical structure.

## How the bug was found

After ruling out environment issues (identical binaries confirmed via `md5sum`, identical `ldd` output, identical `LD_LIBRARY_PATH`), local reproduction confirmed the non-deterministic nature.

Source analysis of `core-main` traced the KWS inference path:

```
main loop → krdmKwsIdentifyKeyword → [queue] → identifyKeywordThread
  → processKeyword → handleIdentification → m_kws_model->runModel()
```

`TfliteModel::runModel` (`ai_model.cc:415-459`) calls `TfLiteInterpreterResizeInputTensor` + `TfLiteInterpreterAllocateTensors` on **every invocation**, even though the input dimensions are constant `{1, 30, 128}` (because `KWS_USE_INTERPOLATION = true` for SK):

```cpp
// ai_model.cc:428-434 — called hundreds of times per file
int input_dims[] = {1, KRDM_NUM_MEL_BINS, input_length}; // always {1, 30, 128}
resizeInputTensor(this->m_interpreter, input_dims, input_dims_size);
allocateTensors(this->m_interpreter);
```

`ResizeInputTensor` marks internal tensors as dirty regardless of whether the size changed. `AllocateTensors` then processes this dirty flag, potentially freeing and reallocating internal tensor buffers. Over hundreds of invocations across a 17-minute file, this repeated free/realloc cycle corrupts TF Lite's internal heap structures — specifically the `tensors_size` field used for bounds-checking tensor indices.

A secondary issue: `KwsContext::uninit()` calls `m_kws_model->unloadModel()` (deleting the TF Lite interpreter) without first stopping the identification thread, creating a potential use-after-free during cleanup.

## The fix

### Primary: eliminate unnecessary resize+allocate in `runModel`

Move the one-time resize to `loadModel`, where the interpreter is created:

```cpp
// In TfliteModel::loadModel, after createInterpreter:
int input_dims[] = {1, KRDM_NUM_MEL_BINS, KRDM_NUM_MFCC_SEC_AND_HALF};
TfLiteInterpreterResizeInputTensor(m_interpreter, TFLITE_INPUT_IDX, input_dims, 3);
TfLiteInterpreterAllocateTensors(m_interpreter);
// then validate tensors as before
```

Strip `resizeInputTensor` and `allocateTensors` from `runModel` — the dimensions are fixed, so tensors only need to be allocated once:

```cpp
E_KRDM_AI_MODEL_RETURN_CODE TfliteModel::runModel(S_KWS_OUTPUTS *outputs, float *model_input, int input_length)
{
    if (!this->IsReady()) return AI_MODEL_CODE_NOT_READY;

    TfLiteTensor* input_tensor = TfLiteInterpreterGetInputTensor(this->m_interpreter, TFLITE_INPUT_IDX);
    if (input_tensor == NULL || !copyInputData(input_tensor, model_input, input_length))
        return AI_MODEL_CODE_INVALID_INPUT;

    if (!invokeInterpreter(this->m_interpreter))
        return AI_MODEL_CODE_MODEL_INVOCATION_ERR;

    if (!copyOutputData(this->m_interpreter, outputs))
        return AI_MODEL_CODE_PREPROCESSING_ERR;

    return AI_MODEL_CODE_OK;
}
```

### Secondary: stop thread before unloading model in `uninit()`

```cpp
void KwsContext::uninit()
{
#if USE_IDENTIFICATION_THREAD
    this->m_is_thread_allowed = false;
    if (this->m_identification_thread.joinable())
        this->m_identification_thread.join();
#endif
    // ... existing cleanup ...
}
```

## Affected builds

The resize+allocate bug lives in shared code (`TfliteModel::runModel`), so it affects every build that uses the TF Lite backend (`TFLITE == 1`). Builds using TF Lite Micro (`TFLM == 1`) take a different code path and are not affected.

| Build | TF Lite backend | Interpolation | Input dims constant | ID thread | Risk |
|---|---|---|---|---|---|
| **SK** | TFLITE | yes | `{1,30,128}` | **yes** | **Crashes observed** |
| **SKYWORTH** | TFLITE | yes | `{1,30,128}` | no | Latent — same heap churn |
| **HMTC** | TFLITE | **no** | **variable** | no | Latent — resize is functionally needed but allocate still churns |
| **AMO_KIOSK** | TFLITE | yes | `{1,30,102}` | no | Latent |
| **MALLET / WOVEN / CONTINENTAL** | TFLITE | yes | `{1,30,128}` | no | Latent |
| **RENAULT** | TFLITE | yes | `{1,30,128}` | no | Latent |
| **KT_GG4** | TFLITE | yes | `{1,30,102}` | no | Latent |
| LGVS_W / LGVS_LEGACY / MOBIS_L / MOBIS_S | TFLM | — | — | no | Not affected |

SK is the first to crash because it is the only build that also runs KWS on a separate thread (`D_USE_IDENTIFICATION_THREAD = true`) with `TFLITE_NUM_THREADS = 2`, widening the window for heap corruption to hit a critical structure. The other 6 TF Lite builds carry the same heap churn — they just haven't manifested it yet because their workloads may be shorter or their heap layout less fragile.

### HMTC: variable-length input

HMTC is the one TF Lite build where `KWS_USE_INTERPOLATION = false` and `KWS_USE_PADDING = false`. In `handleIdentification`, this means `runModel` receives `input_length = preprocess_ctx_out.model_input.size() / KRDM_NUM_MEL_BINS`, which varies per invocation depending on how many VAD-active frames were detected. The resize is therefore functionally necessary when the length changes.

However, the current code calls `ResizeInputTensor` + `AllocateTensors` unconditionally on every invocation — even when consecutive calls happen to have the same `input_length`. This still produces unnecessary heap churn.

**Recommended safety mechanism for HMTC:** cache the last allocated `input_length` and skip resize+allocate when it hasn't changed:

```cpp
E_KRDM_AI_MODEL_RETURN_CODE TfliteModel::runModel(S_KWS_OUTPUTS *outputs, float *model_input, int input_length)
{
    if (!this->IsReady()) return AI_MODEL_CODE_NOT_READY;

    if (input_length != this->m_last_input_length)
    {
        int input_dims[] = {1, KRDM_NUM_MEL_BINS, input_length};
        if (!resizeInputTensor(this->m_interpreter, input_dims, 3))
            return AI_MODEL_CODE_INVALID_INPUT;
        if (!allocateTensors(this->m_interpreter))
            return AI_MODEL_CODE_ALLOC_ERR;
        this->m_last_input_length = input_length;
    }

    TfLiteTensor* input_tensor = TfLiteInterpreterGetInputTensor(this->m_interpreter, TFLITE_INPUT_IDX);
    if (input_tensor == NULL || !copyInputData(input_tensor, model_input, input_length))
        return AI_MODEL_CODE_INVALID_INPUT;

    if (!invokeInterpreter(this->m_interpreter))
        return AI_MODEL_CODE_MODEL_INVOCATION_ERR;

    if (!copyOutputData(this->m_interpreter, outputs))
        return AI_MODEL_CODE_PREPROCESSING_ERR;

    return AI_MODEL_CODE_OK;
}
```

This requires adding `int m_last_input_length = 0;` to the `TfliteModel` class. It works for all builds: builds with constant input skip every resize after the first; HMTC only resizes when the length actually changes.

## Why this fixes it

The fix eliminates hundreds of unnecessary `free`/`realloc` cycles inside TF Lite per audio file. Since the input dimensions never change at runtime for SK builds (and most other builds), allocating tensors once at model load time is both correct and safe. For HMTC where the length does vary, the cached-length guard reduces resize+allocate calls to only those where the size actually changed. This removes the heap churn that gradually corrupts TF Lite's internal tensor metadata, preventing the SIGSEGV.
