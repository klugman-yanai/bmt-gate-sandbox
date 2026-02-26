"""Pytest configuration: add devtools, repo root, and remote/code/sk to sys.path so scripts are importable."""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "devtools"))
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "remote" / "code"))
sys.path.insert(0, str(_ROOT / "remote" / "code" / "sk"))
sys.path.insert(0, str(_ROOT / "remote"))
