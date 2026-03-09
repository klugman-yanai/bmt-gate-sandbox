"""Pytest configuration: add tools, repo root, and deploy/code/sk to sys.path so scripts are importable."""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "packages" / "bmt-cli"))
sys.path.insert(0, str(_ROOT / "tools"))
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "deploy" / "code"))
sys.path.insert(0, str(_ROOT / "deploy" / "code" / "sk"))
sys.path.insert(0, str(_ROOT / "deploy"))
