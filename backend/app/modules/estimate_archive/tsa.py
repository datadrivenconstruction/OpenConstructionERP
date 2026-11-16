# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Optional RFC 3161 timestamp over a seal's fingerprint.

Off unless ``ESTIMATE_ARCHIVE_TSA_URL`` names a timestamp authority. The
request is hand-encoded DER (no new dependency): a TimeStampReq with the
SHA-256 message imprint, a nonce and certReq true. The authority's response is
stored as returned, base64, so anyone can verify it later with standard tools
(``openssl ts -reply -in``). A failure never blocks sealing: a seal without a
timestamp is still a seal, sealed at the server's UTC time.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets

logger = logging.getLogger(__name__)

ENV_URL = "ESTIMATE_ARCHIVE_TSA_URL"
_SHA256_OID = bytes.fromhex("0609608648016503040201")  # OBJECT IDENTIFIER 2.16.840.1.101.3.4.2.1


def tsa_url() -> str:
    """The configured authority URL, or ``""`` when timestamps are off."""
    return os.environ.get(ENV_URL, "").strip()


def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _len(len(value)) + value


def _int(value: int) -> bytes:
    body = value.to_bytes((value.bit_length() + 8) // 8 or 1, "big")
    return _tlv(0x02, body)


def build_request(sha256_hex: str, nonce: int | None = None) -> bytes:
    """DER TimeStampReq for a SHA-256 digest (RFC 3161 section 2.4.1)."""
    digest = bytes.fromhex(sha256_hex)
    algorithm = _tlv(0x30, _SHA256_OID + b"\x05\x00")
    imprint = _tlv(0x30, algorithm + _tlv(0x04, digest))
    nonce_value = nonce if nonce is not None else secrets.randbits(63)
    return _tlv(0x30, _int(1) + imprint + _int(nonce_value) + _tlv(0x01, b"\xff"))


async def request_timestamp(sha256_hex: str) -> tuple[str | None, str | None]:
    """Ask the configured authority to timestamp a digest.

    Returns:
        ``(base64 token, authority URL)``, or ``(None, None)`` when no
        authority is configured or it did not answer with a granted token.
    """
    url = tsa_url()
    if not url:
        return None, None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url, content=build_request(sha256_hex), headers={"Content-Type": "application/timestamp-query"}
            )
        if resp.status_code != 200 or not resp.content:
            logger.warning("Timestamp authority %s answered %s; sealing without a timestamp", url, resp.status_code)
            return None, None
        return base64.b64encode(resp.content).decode("ascii"), url
    except Exception:
        logger.warning("Timestamp authority %s unreachable; sealing without a timestamp", url, exc_info=True)
        return None, None
