# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Idempotency keys for ``POST /rulesets/{id}:run`` (Wave 1, RFC 36 W1.1).

A re-posted run with the same idempotency key returns the existing
``EacRun`` instead of starting a fresh execution. This is important for
two flows:

1. **Webhook retries.** A flaky upstream may re-fire the run trigger
   (e.g. on file upload) — without idempotency, every retry burns CPU
   and produces duplicate result rows the user sees as noise.
2. **Client retries on transient errors.** Clients that retry on
   network blips need an at-least-once contract; idempotency makes it
   exactly-once at the persistence layer.

The key is either:

* **Client-supplied** via the ``Idempotency-Key`` HTTP header
  (RFC 9110 ``Idempotency-Key`` semantics) — prefixed with ``client:``
  so it can never collide with an auto-derived key.
* **Auto-derived** from a stable hash of the inputs — prefixed with
  ``auto:``. Useful for the webhook case where the trigger doesn't know
  whether the same input has been submitted before.

Auto-derivation hashes (in order, NUL-separated):

1. ruleset_id
2. ruleset.updated_at (so a re-version of the ruleset starts a fresh
   run even if the elements haven't changed)
3. sorted ``stable_id`` of every element (cheap fingerprint of "the set")
4. JSON-canonical-form of the element list, sorted by stable_id
   (catches changes to property values within the same set)

The result is a 64-hex-char SHA-256 digest plus the ``auto:`` prefix —
71 chars total, comfortably within the 128-char ``idempotency_key``
column width.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Sequence

# Maximum length the column can store. Mirrors the migration so a
# pathological client-supplied key gets truncated rather than rejected
# (keeping retries idempotent in practice).
_MAX_KEY_LENGTH = 128


def compute_idempotency_key(
    *,
    ruleset_id: uuid.UUID,
    ruleset_updated_at: datetime,
    elements: Sequence[dict[str, Any]],
    client_supplied: str | None = None,
) -> str:
    """Return the idempotency key for a ``POST /rulesets/{id}:run`` call.

    See module docstring for the contract.
    """
    if client_supplied:
        # Header values are user-controlled — strip whitespace and clamp
        # length so a malicious caller can't blow the column. Rejecting
        # outright would force them to handle yet another error code; we
        # prefer "best-effort idempotency" over "strict validation".
        cleaned = client_supplied.strip()[: _MAX_KEY_LENGTH - len("client:")]
        return f"client:{cleaned}"

    h = hashlib.sha256()
    h.update(str(ruleset_id).encode("utf-8"))
    h.update(b"\0")
    # ``isoformat`` gives microsecond-precision UTC timestamps which is
    # plenty to discriminate a republished ruleset from a no-op edit.
    h.update(ruleset_updated_at.isoformat().encode("utf-8"))
    h.update(b"\0")

    # Project elements through a stable canonical form so semantically
    # identical inputs hash identically regardless of dict ordering.
    sorted_elements = _canonical_sorted(elements)
    for elem in sorted_elements:
        sid = str(elem.get("stable_id") or "")
        h.update(sid.encode("utf-8"))
        h.update(b"\x01")

    h.update(b"\0")
    payload = json.dumps(sorted_elements, sort_keys=True, default=str)
    h.update(payload.encode("utf-8"))

    return f"auto:{h.hexdigest()}"


def _canonical_sorted(
    elements: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return ``elements`` sorted by ``stable_id`` for deterministic hashing.

    Elements without a ``stable_id`` are still hashed but sorted to the
    end — they shouldn't normally exist (the runner emits a stable id
    for every BIM element), but defensive code keeps the hash defined
    in pathological inputs.
    """

    def _sort_key(elem: dict[str, Any]) -> tuple[int, str]:
        sid = elem.get("stable_id")
        if sid is None or sid == "":
            return (1, json.dumps(elem, sort_keys=True, default=str))
        return (0, str(sid))

    return sorted(elements, key=_sort_key)


__all__ = ["compute_idempotency_key"]
