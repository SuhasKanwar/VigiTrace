"""Integrity and chain-of-custody primitives.

Hashes here are validation aids, not proof that an acquisition was performed
correctly. They establish that a stored artifact is byte-identical to what was
received, which is a narrower claim and the only one the software can support.
"""

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

CHUNK_SIZE = 1024 * 1024


def hash_file(path: str) -> dict[str, Any]:
    """Compute MD5 and SHA-256 over a stored artifact in a single pass."""
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            md5.update(chunk)
            sha256.update(chunk)
            size += len(chunk)
    return {
        "path": path,
        "size_bytes": size,
        "md5": md5.hexdigest(),
        "sha256": sha256.hexdigest(),
        "hashed_at": datetime.now(timezone.utc).isoformat(),
    }


def verify_file(path: str, expected_sha256: str) -> dict[str, Any]:
    """Re-hash a stored artifact and compare against a recorded digest."""
    if not os.path.exists(path):
        return {"verified": False, "reason": "Artifact is missing from storage.", "path": path}
    actual = hash_file(path)
    matches = actual["sha256"] == expected_sha256
    return {
        "verified": matches,
        "path": path,
        "expected_sha256": expected_sha256,
        "actual_sha256": actual["sha256"],
        "size_bytes": actual["size_bytes"],
        "reason": None if matches else "Stored artifact does not match its recorded digest.",
    }


def evidence_digest(payloads: list[str]) -> str:
    """Order-independent digest over a set of retained vendor payloads.

    Sorting before hashing means the digest depends on the content collected,
    not on the order the endpoints happened to answer in.
    """
    digest = hashlib.sha256()
    for payload in sorted(payloads):
        digest.update(hashlib.sha256(payload.encode("utf-8", "replace")).digest())
    return digest.hexdigest()
