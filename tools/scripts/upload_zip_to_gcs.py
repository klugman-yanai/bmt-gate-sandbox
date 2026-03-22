"""Extract WAV files from a zip one at a time and upload each to GCS, then delete."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def upload_zip_wavs(zip_path: str, gcs_dest: str, tmp_dir: str | None = None) -> None:
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".wav")]
        print(f"Found {len(members)} WAV files in {zip_path.name}", flush=True)

        for name in members:
            info = zf.getinfo(name)
            size_gb = info.file_size / 1e9
            base = os.path.basename(name)
            dest = gcs_dest.rstrip("/") + "/" + base
            print(f"\n[{base}] {size_gb:.2f}GB → {dest}", flush=True)

            # Extract to a temp file (on same filesystem as tmp_dir for space)
            extract_dir = tmp_dir or str(zip_path.parent)
            with tempfile.NamedTemporaryFile(
                dir=extract_dir,
                suffix=".wav",
                delete=False,
                prefix="bmt_upload_",
            ) as tf:
                tmp_path = tf.name

            try:
                print(f"  Extracting...", end=" ", flush=True)
                with zf.open(name) as src, open(tmp_path, "wb") as dst:
                    while chunk := src.read(4 * 1024 * 1024):  # 4MB chunks
                        dst.write(chunk)
                print("done", flush=True)

                print(f"  Uploading...", end=" ", flush=True)
                result = subprocess.run(
                    ["gcloud", "storage", "cp", tmp_path, dest],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    print(f"FAILED\n  stderr: {result.stderr[:500]}", flush=True)
                    sys.exit(1)
                print("done", flush=True)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    print("\nAll files uploaded successfully.", flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path")
    parser.add_argument("gcs_dest")
    parser.add_argument("--tmp-dir", default=None)
    args = parser.parse_args()
    upload_zip_wavs(args.zip_path, args.gcs_dest, args.tmp_dir)
