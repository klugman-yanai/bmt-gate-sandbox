"""BMT timeout defaults: re-exported from gcp/code/lib/bmt_config (single source of truth).

Use get_config() or constants from gcp.code.config.bmt_config in new code.
Kept for backward compatibility with existing imports."""

from __future__ import annotations

from gcp.code.config.bmt_config import VM_STOP_WAIT_TIMEOUT_SEC

# Backward-compat names (BmtConfig holds handshake default; VM stop is constant).
DEFAULT_HANDSHAKE_TIMEOUT_SEC: int = (
    420  # BmtConfig default; use get_config().bmt_handshake_timeout_sec
)
DEFAULT_VM_START_TIMEOUT_SEC: int = 420  # VM_START_TIMEOUT_SEC in bmt_config
DEFAULT_VM_STOP_WAIT_TIMEOUT_SEC: int = VM_STOP_WAIT_TIMEOUT_SEC
