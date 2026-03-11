"""Canonical default values for BMT timeouts and behavioral vars.

Single source of truth: change these when you need to adjust defaults. Keep
infra/terraform/variables.tf, Justfile, and infra/bootstrap/.env.example in sync
(see comments there)."""

# Handshake: wait for VM ack after trigger (cold start can be slow).
DEFAULT_HANDSHAKE_TIMEOUT_SEC: int = 420

# VM start: time to wait for RUNNING after issuing start (includes stabilization).
DEFAULT_VM_START_TIMEOUT_SEC: int = 420

# VM stop: time to wait for TERMINATED after issuing stop (e.g. in select-available-vm).
DEFAULT_VM_STOP_WAIT_TIMEOUT_SEC: int = 420
