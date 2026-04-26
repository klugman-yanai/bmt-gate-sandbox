# Cloud Run–Native Solutions for SIGBUS (kardome_runner / libKardome.so)

**Date:** 2026-03-16  
**Context:** Python 3.12 orchestrator invoking native binary `kardome_runner` + shared lib `libKardome.so`. GLIBC_2.43 / GLIBCXX_3.4.32 required. Fedora 44/rawhide base works locally; Cloud Run Job executions fail with `Container terminated on signal 7` (SIGBUS) before app logs.

**Assumptions:** The Cloud Run job image is built from [`runtime/Dockerfile`](../../runtime/Dockerfile) (see `cfg.cloud_run_image_uri` in `infra/pulumi/config.py`). That Dockerfile uses Ubuntu 22.04; the kardome sandbox image (`tools/scripts/Dockerfile.kardome-sandbox`) is also Ubuntu 22.04 so local runs match the Cloud Run environment.

---

## 1. Root Cause Analysis

### What We Know

| Fact | Source |
|------|--------|
| **Cloud Run Jobs always use Gen2** | [Cloud Run execution environments](https://cloud.google.com/run/docs/about-execution-environments) — "Cloud Run jobs and worker pools only use the second generation execution environment" |
| **Gen2 = full Linux compatibility** | No gVisor; microVM with all syscalls, namespaces, cgroups supported |
| **SIGBUS (exit 7)** | [Container contract](https://cloud.google.com/run/docs/container-contract): "Task attempted to access memory outside its allocated boundaries" |
| **GLIBC 2.43** | Released Jan 2026; only Fedora rawhide/44 have it. Ubuntu 24.04 has 2.39 |
| **GLIBCXX 3.4.32** | GCC 13.2+; Ubuntu 22.04 has up to 3.4.30 |

### Likely Causes (Ranked)

1. **Fedora userspace + Cloud Run host kernel mismatch** — Fedora expects newer kernel interfaces or memory semantics; Cloud Run Gen2 microVM host may differ.
2. **Vendor binary built on bleeding-edge toolchain** — `libKardome.so` / `kardome_runner` may use instructions or memory patterns that trigger SIGBUS on Cloud Run’s host.
3. **Early crash before Python logs** — Crash during Python startup, first import, or first `subprocess.run(kardome_runner)`; without logs, exact point is unknown.

---

## 2. Architecture Options (Ranked)

### A) Stay on Cloud Run — Rebuild Vendor Binaries for Older glibc (Recommended)

**Idea:** Rebuild `kardome_runner` and `libKardome.so` (if source available) against Ubuntu 22.04 or 24.04 glibc/libstdc++. glibc is backward-compatible; binaries built on older glibc run on newer.

**Pros:**
- Fully Cloud Run–native
- No infra changes
- Uses well-tested base (Ubuntu 22.04/24.04) that Cloud Run supports
- No sidecars or extra services

**Cons:**
- Requires source and build pipeline
- If vendor is external, may need coordination

**Implementation:**
- Base image: `ubuntu:22.04` or `ubuntu:24.04`
- Build `kardome_runner` and `libKardome.so` in a container using that base
- Ensure `LD_LIBRARY_PATH` includes bundled deps (e.g. libonnxruntime.so) from the same build

**Source:** [Compile binary for older GLIBC?](https://askubuntu.com/questions/957480/compile-binary-for-older-glibc), [glibc backward compatibility](https://sourceware.org/legacy-ml/libc-help/2015-03/msg00018.html)

---

### B) Stay on Cloud Run — Try Ubuntu 24.04 + Toolchain PPA (If No Source)

**Idea:** Use Ubuntu 24.04 base and add Ubuntu Toolchain PPA for newer `libstdc++6` (GLIBCXX_3.4.32). glibc 2.43 is still unavailable on Ubuntu; this only helps if the failure is libstdc++-related.

**Pros:**
- No source needed
- Quick to try

**Cons:**
- Ubuntu 24.04 has glibc 2.39, not 2.43 — if binary truly needs 2.43, it will fail with "version `GLIBC_2.43' not found"
- PPA adds maintenance and trust surface

**Implementation:**
```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y software-properties-common && \
    add-apt-repository ppa:ubuntu-toolchain-r/test && apt-get update && \
    apt-get install -y --only-upgrade libstdc++6
# ... rest of image
```

---

### C) Stay on Cloud Run — Offload Native Step to Separate Cloud Run Service

**Idea:** Orchestrator (Cloud Run Job) calls a Cloud Run Service that runs `kardome_runner`; service uses a base image known to work.

**Pros:**
- Keeps orchestration on Cloud Run
- Can use different image for native step

**Cons:**
- Not “native” — adds HTTP/gRPC hop, latency, and complexity
- Per-WAV or per-batch calls can be expensive and slow
- Service must be scaled for parallelism

**Verdict:** Workaround, not a first-choice solution.

---

### D) Hybrid — Cloud Run Orchestration + GKE/Batch/Compute for Native Step

**Idea:** Cloud Run Job (or Workflow) triggers a GKE Job, Batch Job, or Compute VM to run the native workload; results written to GCS; orchestrator polls or uses callbacks.

**Pros:**
- Full control over runtime (kernel, glibc, CPU features)
- GKE Autopilot / Batch can scale to zero or near-zero
- Proven for heavy native workloads

**Cons:**
- More infra (GKE cluster or Batch API)
- Eventarc → Workflows → Cloud Run Job flow must be extended
- Operational complexity

**Source:** [GKE Batch](https://cloud.google.com/kubernetes-engine/docs/batch), [Cloud Batch](https://cloud.google.com/batch)

---

### E) Bundle glibc + Dynamic Loader (Not Recommended)

**Idea:** Ship glibc 2.43 and `ld-linux-x86-64.so` with the image and invoke via `LD_LIBRARY_PATH` + custom loader path.

**Cons:**
- Loader path is hardcoded in ELF; `$ORIGIN` does not apply to the loader
- Loader and libc must match exactly; mismatches cause segfaults
- High maintenance and brittle

**Source:** [Portable glibc binary](https://sourceware.org/legacy-ml/libc-help/2015-03/msg00018.html), [make-portable](https://github.com/natanael-b/make-portable)

---

### F) Cloud Run Knobs (Gen1/Gen2, CPU, Volumes, seccomp)

| Knob | Relevance |
|------|-----------|
| **Gen1 vs Gen2** | Jobs always use Gen2; no choice |
| **CPU architecture** | Cloud Run Jobs support only `linux/amd64` |
| **Launch stage** | GA is standard; no impact |
| **Volumes** | GCS FUSE already used; no change for SIGBUS |
| **seccomp** | Cloud Run applies basic profiles; not user-configurable |
| **Memory** | SIGBUS is not OOM; increasing memory unlikely to help |

**Verdict:** No Cloud Run configuration change will fix this.

---

## 3. Native vs Workaround

| Approach | Native Cloud Run? | Notes |
|----------|-------------------|-------|
| Rebuild for older glibc (A) | Yes | Single Cloud Run Job, standard base image |
| Ubuntu + PPA (B) | Yes | If glibc 2.43 is not actually required |
| Separate Service (C) | Partial | Extra service, not a single-job model |
| GKE/Batch (D) | No | Orchestration on Cloud Run, execution elsewhere |
| Bundle glibc (E) | Yes | Technically possible but fragile |

---

## 4. Recommended Strategy

**Primary:** Rebuild vendor binaries for Ubuntu 22.04 or 24.04 (Option A).

**Rationale:**
- Aligns with Cloud Run’s supported stacks (Ubuntu-based buildpacks)
- Removes Fedora-specific behavior as a variable
- glibc backward compatibility is well understood
- No extra services or infra

**Risks:**
- Need source and build pipeline
- Possible feature differences if binary relied on very new glibc behavior

**Fallback:** If source is unavailable, try Option B (Ubuntu 24.04 + PPA) to confirm whether the failure is glibc vs libstdc++. If both are required and unreachable, Option D (GKE/Batch) is the next step.

---

## 5. Implementation Checklist (This Repo)

### Phase 1: Root Cause Validation (< 1 hour)

1. **Minimal crash repro**
   - Add a minimal Cloud Run Job that runs only:
     ```python
     import subprocess
     subprocess.run(["/path/to/kardome_runner", "--help"], check=True)
     ```
   - Or: `CMD ["/opt/kardome/kardome_runner", "--help"]` if the runner supports it.
   - If this fails with SIGBUS, the crash is in the native binary, not Python imports.

2. **Ubuntu 24.04 base test**
   - Build image with `FROM ubuntu:24.04` (or `debian:bookworm`).
   - Install Python 3.12, gcloud, ffmpeg, libsndfile, etc.
   - Copy `kardome_runner` and `libKardome.so` from GCS.
   - Deploy and run.
   - If you see `version 'GLIBC_2.43' not found` → glibc requirement confirmed.
   - If you see SIGBUS → problem is not Fedora-specific.

3. **Local Docker on Ubuntu base**
   - Run the same image locally with `docker run` on an Ubuntu 22.04/24.04 host.
   - If it works locally but fails on Cloud Run → Cloud Run host environment is the cause.

### Phase 2: Rebuild Path (If Source Available)

1. Create build Dockerfile (e.g. `runtime/Dockerfile.runner-build`) using `ubuntu:22.04` or `ubuntu:24.04`.
2. Build `kardome_runner` and `libKardome.so` in that container.
3. Copy artifacts into the main app image (or publish to GCS and download at runtime).
4. Update `bmt_jobs.json` and manager to use the new runner path.
5. Run full BMT locally, then on Cloud Run.

### Phase 3: Fallback (No Source)

1. Try Ubuntu 24.04 + Toolchain PPA for libstdc++.
2. If glibc 2.43 is required and cannot be satisfied, design GKE Batch or Compute VM integration for the native step.

---

## 6. Quick Experiments (< 1 Hour)

| Experiment | Command / Action | Expected Outcome |
|------------|------------------|------------------|
| **1. Is it Python or runner?** | Deploy job with `CMD ["python3", "-c", "import sys; print('ok'); sys.exit(0)"]` | If OK → Python fine; crash is in runner path |
| **2. Is it runner startup?** | `CMD ["/path/to/kardome_runner", "--help"]` (or similar) | If SIGBUS → runner or libs crash on load |
| **3. Ubuntu base** | Switch Dockerfile to `FROM ubuntu:24.04`, minimal deps, same runner | `GLIBC_2.43 not found` or SIGBUS |
| **4. Check symbols** | `objdump -T libKardome.so \| grep GLIBC` | See exact glibc versions required |
| **5. Local vs Cloud Run** | `docker run --rm <image> python -c "import subprocess; subprocess.run(['/path/to/kardome_runner'])` | Compare local vs Cloud Run behavior |

### Symbol Check (Run Locally)

```bash
objdump -T gcp/stage/projects/sk/lib/libKardome.so | grep -E 'GLIBC|GLIBCXX'
objdump -T gcp/stage/projects/sk/kardome_runner | grep -E 'GLIBC|GLIBCXX'
```

**Actual symbol requirements (verified 2026-03-16):**

| Binary | Max GLIBC | Max GLIBCXX |
|--------|-----------|-------------|
| `kardome_runner` | 2.34 | — |
| `libKardome.so` | **2.43** (`sqrtf`) | **3.4.32** (`ios_base_library_init`) |

`kardome_runner` itself is compatible with Ubuntu 22.04/24.04. The blocker is **libKardome.so**, which requires GLIBC_2.43 (one symbol: `sqrtf`) and GLIBCXX_3.4.32 (one symbol: `_ZSt21ios_base_library_initv`). Ubuntu 24.04 has glibc 2.39 and libstdc++ up to ~3.4.30.

---

## 7. References

- [Cloud Run container contract](https://cloud.google.com/run/docs/container-contract) — exit codes, Gen2, constraints
- [Cloud Run execution environments](https://cloud.google.com/run/docs/about-execution-environments) — Gen1 vs Gen2, Jobs always Gen2
- [gVisor syscall compatibility](https://gvisor.dev/docs/user_guide/compatibility/linux/amd64) — N/A for Jobs (Gen2)
- [GLIBC 2.43 release](https://sourceware.org/pipermail/libc-alpha/2026-January/174374.html)
- [Compile for older glibc](https://askubuntu.com/questions/957480/compile-binary-for-older-glibc)
- [Cloud Run base images](https://cloud.google.com/run/docs/configuring/services/runtime-base-images) — google-24-full, Ubuntu stacks
