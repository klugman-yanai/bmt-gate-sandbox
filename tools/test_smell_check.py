from __future__ import annotations

from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    tests_dir = repo / "tests"
    forbidden_patterns = [
        ".gcloud",
        "deploy/code",
        "bucket_sync_remote.py",
        "bucket_verify_remote_sync.py",
    ]

    hits: list[tuple[Path, str]] = []
    for path in tests_dir.rglob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            if pattern in text:
                hits.append((path.relative_to(repo), pattern))

    if not hits:
        print("Test smell check passed.")
        return 0

    print("Test smell check failed. Forbidden patterns found:")
    for rel, pat in hits:
        print(f"  - {rel}: {pat}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
