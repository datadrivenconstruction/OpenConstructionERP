# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ZATCA QR code: tag-length-value bytes, base64 encoded.

Security Features standard v1.2 §4: one byte tag, one byte length, the value;
the whole base64 encoded, at most 700 characters. The tags:

1. seller name, 2. seller VAT number, 3. timestamp (``IssueDate`` and
``IssueTime`` joined by ``T``), 4. invoice total with VAT, 5. VAT total,
6. invoice hash, 7. the ECDSA signature, 8. the ECDSA public key,
9. the signature of the stamp's certificate by ZATCA's CA (simplified
documents only).

Tags 6 and 7 carry the base64 *text* of the hash and the signature, not their
raw bytes. The standard says "32 bytes" for tag 6; every signed sample in the
official SDK and the SDK's own QR check use the text. The package follows the
SDK and the spec records the discrepancy (D5). Tags 8 and 9 are raw DER bytes
(the SubjectPublicKeyInfo, and the certificate's signature).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

MAX_LENGTH = 700

TAG_SELLER_NAME = 1
TAG_VAT_NUMBER = 2
TAG_TIMESTAMP = 3
TAG_TOTAL_WITH_VAT = 4
TAG_VAT_TOTAL = 5
TAG_INVOICE_HASH = 6
TAG_SIGNATURE = 7
TAG_PUBLIC_KEY = 8
TAG_CERTIFICATE_SIGNATURE = 9


class QrError(ValueError):
    """A QR value that cannot be written or read."""


@dataclass(frozen=True)
class QrFields:
    """The QR contents of one document."""

    seller_name: str
    vat_number: str
    timestamp: str
    total_with_vat: str
    vat_total: str
    invoice_hash: str = ""
    signature: str = ""
    public_key: bytes = b""
    certificate_signature: bytes = b""

    def tags(self) -> list[tuple[int, bytes]]:
        values: list[tuple[int, bytes]] = [
            (TAG_SELLER_NAME, self.seller_name.encode("utf-8")),
            (TAG_VAT_NUMBER, self.vat_number.encode("utf-8")),
            (TAG_TIMESTAMP, self.timestamp.encode("utf-8")),
            (TAG_TOTAL_WITH_VAT, self.total_with_vat.encode("utf-8")),
            (TAG_VAT_TOTAL, self.vat_total.encode("utf-8")),
        ]
        if self.invoice_hash:
            values.append((TAG_INVOICE_HASH, self.invoice_hash.encode("ascii")))
        if self.signature:
            values.append((TAG_SIGNATURE, self.signature.encode("ascii")))
        if self.public_key:
            values.append((TAG_PUBLIC_KEY, self.public_key))
        if self.certificate_signature:
            values.append((TAG_CERTIFICATE_SIGNATURE, self.certificate_signature))
        return values


def encode(fields: QrFields) -> str:
    """The base64 QR text. Refuses a value over 255 bytes or a result over 700 characters."""
    out = bytearray()
    for tag, value in fields.tags():
        if len(value) > 255:
            raise QrError(f"QR tag {tag} is {len(value)} bytes; one tag holds at most 255.")
        out += bytes((tag, len(value))) + value
    text = base64.b64encode(bytes(out)).decode("ascii")
    if len(text) > MAX_LENGTH:
        raise QrError(f"The QR is {len(text)} characters; ZATCA allows at most {MAX_LENGTH}.")
    return text


def decode(text: str) -> dict[int, bytes]:
    """Tag to raw value. Raises :class:`QrError` on anything that is not well-formed TLV."""
    try:
        raw = base64.b64decode("".join((text or "").split()), validate=True)
    except ValueError as exc:
        raise QrError("The QR is not base64.") from exc
    tags: dict[int, bytes] = {}
    index = 0
    while index < len(raw):
        if index + 2 > len(raw):
            raise QrError("The QR ends inside a tag header.")
        tag, length = raw[index], raw[index + 1]
        value = raw[index + 2 : index + 2 + length]
        if len(value) != length:
            raise QrError(f"QR tag {tag} is shorter than its length says.")
        if tag in tags:
            raise QrError(f"QR tag {tag} appears twice.")
        tags[tag] = value
        index += 2 + length
    return tags


__all__ = [
    "MAX_LENGTH",
    "TAG_CERTIFICATE_SIGNATURE",
    "TAG_INVOICE_HASH",
    "TAG_PUBLIC_KEY",
    "TAG_SELLER_NAME",
    "TAG_SIGNATURE",
    "TAG_TIMESTAMP",
    "TAG_TOTAL_WITH_VAT",
    "TAG_VAT_NUMBER",
    "TAG_VAT_TOTAL",
    "QrError",
    "QrFields",
    "decode",
    "encode",
]
