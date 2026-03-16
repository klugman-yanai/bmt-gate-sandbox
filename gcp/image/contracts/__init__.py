"""Contributor API contracts for BMT managers.

Exports the Protocol (structural contract) and the ABC base class (runtime contract).
"""

from gcp.image.contracts.bmt_manager import BaseBmtManager, BmtManagerProtocol

__all__ = ["BaseBmtManager", "BmtManagerProtocol"]
