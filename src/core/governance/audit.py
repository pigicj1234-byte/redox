"""
Tamper-evident Audit Log for Symbioz Governance.

Every governance decision is recorded in an append-only, hash-chained log.
Each entry contains the hash of the previous entry, forming a tamper-evident
chain (similar to blockchain block headers, but simpler).

If any entry is modified or deleted, the chain breaks and verification fails.

Features:
  - Append-only writes (no update, no delete)
  - SHA-256 hash chaining: entry[n].prev_hash = sha256(entry[n-1])
  - Policy integrity hash: tracks config file changes
  - Verification: detect tampering at any point in the chain
"""

import hashlib
import json
import os
import time
import logging
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AuditEntry:
    """Single entry in the tamper-evident audit chain."""
    sequence: int
    timestamp: float
    event_type: str           # "decision", "policy_reload", "panic", "override"
    data: dict
    prev_hash: str            # SHA-256 of the previous entry (or "genesis")
    entry_hash: str = ""      # Computed after creation

    def compute_hash(self) -> str:
        """Compute SHA-256 of this entry's content."""
        content = json.dumps({
            "seq": self.sequence,
            "ts": self.timestamp,
            "type": self.event_type,
            "data": self.data,
            "prev": self.prev_hash,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()


class AuditChain:
    """Append-only, hash-chained audit log."""

    GENESIS_HASH = "0" * 64  # Initial hash for the first entry

    def __init__(self, log_path: str = "data/audit_chain.jsonl") -> None:
        self.log_path = log_path
        self.logger = logging.getLogger("AuditChain")
        self._chain: List[AuditEntry] = []
        self._last_hash: str = self.GENESIS_HASH
        self._sequence: int = 0
        self._load_existing()

    def append(self, event_type: str, data: dict) -> AuditEntry:
        """Append a new entry to the audit chain."""
        entry = AuditEntry(
            sequence=self._sequence,
            timestamp=time.time(),
            event_type=event_type,
            data=data,
            prev_hash=self._last_hash,
        )
        entry.entry_hash = entry.compute_hash()

        self._chain.append(entry)
        self._last_hash = entry.entry_hash
        self._sequence += 1

        self._persist(entry)
        return entry

    def log_decision(self, trace_dict: dict) -> AuditEntry:
        """Log a governance decision trace."""
        return self.append("decision", trace_dict)

    def log_policy_reload(self, policy_hash: str, mode: str) -> AuditEntry:
        """Log a policy reload event with the policy file's integrity hash."""
        return self.append("policy_reload", {
            "policy_hash": policy_hash,
            "mode": mode,
        })

    def log_panic(self, reason: str) -> AuditEntry:
        """Log a panic switch activation."""
        return self.append("panic", {"reason": reason})

    def log_manual_override(self, operator: str, action: str, justification: str) -> AuditEntry:
        """Log a human override with justification."""
        return self.append("override", {
            "operator": operator,
            "action": action,
            "justification": justification,
        })

    def verify_chain(self) -> tuple[bool, Optional[int]]:
        """Verify the entire chain integrity.

        Returns (True, None) if valid, or (False, broken_index) if tampered.
        """
        if not self._chain:
            return True, None

        # Check genesis
        if self._chain[0].prev_hash != self.GENESIS_HASH:
            return False, 0

        for i, entry in enumerate(self._chain):
            # Verify self-hash
            expected = entry.compute_hash()
            if entry.entry_hash != expected:
                self.logger.error(
                    "Audit chain TAMPERED at entry %d: hash mismatch", i
                )
                return False, i

            # Verify chain link
            if i > 0 and entry.prev_hash != self._chain[i - 1].entry_hash:
                self.logger.error(
                    "Audit chain BROKEN at entry %d: prev_hash mismatch", i
                )
                return False, i

        return True, None

    def get_entry(self, sequence: int) -> Optional[AuditEntry]:
        """Retrieve an entry by sequence number."""
        if 0 <= sequence < len(self._chain):
            return self._chain[sequence]
        return None

    @property
    def length(self) -> int:
        return len(self._chain)

    @property
    def last_hash(self) -> str:
        return self._last_hash

    def _persist(self, entry: AuditEntry) -> None:
        """Append entry to the on-disk log file."""
        os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
        record = json.dumps({
            "seq": entry.sequence,
            "ts": entry.timestamp,
            "type": entry.event_type,
            "data": entry.data,
            "prev_hash": entry.prev_hash,
            "hash": entry.entry_hash,
        })
        try:
            with open(self.log_path, "a") as f:
                f.write(record + "\n")
        except OSError as e:
            self.logger.error("Failed to persist audit entry: %s", e)

    def _load_existing(self) -> None:
        """Load existing chain from disk on startup."""
        if not os.path.exists(self.log_path):
            return

        try:
            with open(self.log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    entry = AuditEntry(
                        sequence=record["seq"],
                        timestamp=record["ts"],
                        event_type=record["type"],
                        data=record["data"],
                        prev_hash=record["prev_hash"],
                        entry_hash=record["hash"],
                    )
                    self._chain.append(entry)
                    self._last_hash = entry.entry_hash
                    self._sequence = entry.sequence + 1

            valid, broken_at = self.verify_chain()
            if valid:
                self.logger.info(
                    "Audit chain loaded: %d entries, integrity OK", len(self._chain)
                )
            else:
                self.logger.error(
                    "AUDIT CHAIN COMPROMISED at entry %d — investigate immediately",
                    broken_at,
                )
        except Exception as e:
            self.logger.error("Failed to load audit chain: %s", e)


def compute_file_hash(path: str) -> str:
    """Compute SHA-256 hash of a file for policy integrity verification."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "file_not_found"
