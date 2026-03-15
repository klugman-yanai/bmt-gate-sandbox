Master Implementation Plan: Hybrid GCS/VM Architecture
Overview & Philosophy

The current workflow downloads all assets (code, runners, and massive .wav datasets) directly to the VM disk before execution. While this ensures everything is local, it causes slow boot times, inflates VM disk costs, and pollutes local developer environments.

This new architecture implements a Hybrid Strategy:

    System Dependencies: Pre-baked into an immutable image (Packer).

    App Code & Runners: Eagerly synced to local disk (for execution stability).

    Large Datasets: Lazy-loaded via network streaming (gcsfuse), with a robust local ingestion pipeline that handles compressed archives automatically.

Phase 1: Smart Data Ingestion Pipeline (bucket_upload_wavs.py)

Objective: Refactor the upload tool to accept compressed archives (.zip, .tar.gz) from developers, but transparently extract and upload them as raw objects to GCS.

    Task 1.1: Archive Type Detection & Routing

        Action: Implement pathlib.Path suffix checks. If the input is a directory, route to the existing rsync logic. If it is an archive, route to the extraction pipeline.

        Why it's better: Developers can keep their local workspace clean by storing a single 10GB .zip file instead of an unzipped 15GB folder containing 10,000 .wav files.

    Task 1.2: Atomic Extraction via Context Managers

        Action: Use Python's tempfile.TemporaryDirectory() within a with block to extract the archive.

        Why it's better: This acts as a strict guardrail. If the upload process is interrupted (Ctrl+C, network crash), Python automatically deletes the temporary directory, preventing massive disk leaks on the developer's machine.

    Task 1.3: Recursive Root Resolution

        Action: Write a helper that "walks" the extracted temporary directory. If the archive contains a single top-level folder (e.g., false_rejects_v2/audio.wav), the script must set the rsync source directly to that inner folder.

        Why it's better: Prevents redundant nesting in the bucket. Without this, users uploading dataset.zip might accidentally create gs://[BUCKET]/sk/inputs/false_rejects/dataset/audio.wav instead of the expected flat structure.

    Task 1.4: Robust Subprocess & Error Handling

        Action: Wrap gcloud storage rsync in try...except subprocess.CalledProcessError. Explicitly capture and print stderr to surface network connection issues immediately.

        Why it's better: FUSE mounts fail silently or hang during large writes if the network drops. gcloud storage rsync has built-in retry logic, chunking, and MD5 validation, making it the safest way to ingest data.

Phase 2: Immutable Infrastructure Provisioning (Packer)

Objective: Move away from "startup scripts installing dependencies" to a pre-baked Golden Image.

    Task 2.1: Define packer.pkr.hcl Builder

        Action: Create a Google Compute builder using the ubuntu-2204-lts base. Define variables for project_id and zone.

        Why it's better: Treats infrastructure as code. Creating a versioned image ensures that if the Ubuntu Apt repositories go down, your CI/CD pipeline doesn't break.

    Task 2.2: Deterministic System Provisioning

        Action: Write a shell provisioner to run apt-get update, install ffmpeg, gnupg, curl, and add the official GCS FUSE repository. Install gcsfuse.

        Why it's better: Booting a VM from this image takes seconds rather than minutes. BMT (Benchmarking/Testing) runs become significantly cheaper because you aren't paying GCE per-minute rates just to download FFmpeg.

    Task 2.3: Pre-configure Mount Topologies

        Action: Create /app/code, /app/runtime, and /mnt/audio_data directories via the provisioner, applying chown -R to the runtime user.

        Why it's better: Solves the classic "Permission Denied" errors that occur when a startup script tries to mount a drive to a folder owned by root.

Phase 3: Runtime Orchestration & Validation (GCP VM)

Objective: Write the VM entry point that bridges the streaming data with the verified code.

    Task 3.1: FUSE Mount with Implicit Directories

        Action: In startup_entrypoint.sh, execute gcsfuse --only-dir sk/inputs/false_rejects --implicit-dirs [BUCKET] /mnt/audio_data.

        Why it's better: GCS doesn't have real folders. --implicit-dirs allows the OS to infer directory structures from object keys, meaning os.walk() in your Python orchestrator will work exactly as if the files were local.

    Task 3.2: Eager Code Synchronization

        Action: Execute your existing bucket_sync_gcp.py to pull the code to /app/code.

        Why it's better: We stream data, but we download code. If the network blips while a .wav is streaming, a single audio test fails. If the network blips while Python is importing a module over FUSE, the entire application crashes.

    Task 3.3: Contract Validation Enforcement

        Action: Execute bucket_validate_contract.py. If the exit code is non-zero, trigger a sudo poweroff command.

        Why it's better: Acts as an automated circuit breaker. If the GitHub Workflow deploys a VM but the bucket is missing required BMT configurations, the VM destroys itself immediately rather than hanging infinitely.

Phase 4: Local Developer Experience (WSL2)

Objective: Give developers safe, local access to the cloud data without duplicating it.

    Task 4.1: Read-Only FUSE Script

        Action: Create a developer utility script (tools/local/mount_remote_data.sh) that executes gcsfuse -o ro --implicit-dirs ....

        Why it's better: The -o ro (read-only) flag is a critical safety mechanism. It allows the developer to play audio in VLC or view waveforms in their IDE, but makes it impossible for them to accidentally delete or corrupt the central truth in the bucket.
