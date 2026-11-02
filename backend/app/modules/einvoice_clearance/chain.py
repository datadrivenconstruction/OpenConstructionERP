# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Invoice hash chain and TLV QR payload, both driven by pack data.

A country whose mandate file declares ``hash_chain`` links every invoice to the
hash of the one before it; one that declares ``qr`` with ``format: tlv_base64``
prints a QR whose payload is tag-length-value records, base64 encoded. The tag
numbers and what each carries are data. Signing (the tags that need the
tenant's certificate) happens in the signing step, not here.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any


def invoice_hash(payload: bytes | str) -> str:
    """Base64 of the SHA-256 digest of the document bytes."""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def previous_hash_or_genesis(previous: str | None, chain: dict[str, Any]) -> str:
    """The hash the next invoice must carry: the last one, or the chain's genesis value."""
    return (previous or "").strip() or str(chain.get("genesis") or "")


def tlv_encode(records: list[tuple[int, str]]) -> bytes:
    """Encode ``(tag, text)`` pairs as TLV with one-byte tag and length (UTF-8 values)."""
    out = bytearray()
    for tag, text in records:
        value = text.encode("utf-8")
        if not 0 < tag < 256 or len(value) > 255:
            raise ValueError(f"TLV record {tag} does not fit one-byte tag and length")
        out += bytes((tag, len(value))) + value
    return bytes(out)


def tlv_decode(data: bytes) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    i = 0
    while i + 2 <= len(data):
        tag, length = data[i], data[i + 1]
        out.append((tag, data[i + 2 : i + 2 + length].decode("utf-8")))
        i += 2 + length
    return out


def qr_payload(qr: dict[str, Any], values: dict[str, str]) -> str:
    """Build the base64 TLV QR from a pack ``qr`` block and named values.

    Tags whose value is missing are skipped; the caller's validation decides
    whether a missing value blocks the invoice.
    """
    tags = qr.get("tags") or {}
    records = [
        (int(tag), str(values[name]))
        for tag, name in sorted(tags.items(), key=lambda kv: int(kv[0]))
        if str(values.get(name) or "")
    ]
    return base64.b64encode(tlv_encode(records)).decode("ascii")


__all__ = ["invoice_hash", "previous_hash_or_genesis", "qr_payload", "tlv_decode", "tlv_encode"]
