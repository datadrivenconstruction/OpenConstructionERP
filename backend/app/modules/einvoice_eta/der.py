# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The few DER encodings a CAdES-BES signature needs, and a reader for them.

Small on purpose. The platform already depends on ``cryptography``, which can
parse a certificate but cannot add the ``signingCertificateV2`` attribute that
CAdES-BES requires, and pulling in an ASN.1 library for a dozen fixed shapes is
the kind of dependency the lightweight principle asks to justify. The output
is pinned byte for byte to ETA's own signed sample in the tests, which is a
stronger check than any library would give.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

TAG_INTEGER = 0x02
TAG_OCTET_STRING = 0x04
TAG_NULL = 0x05
TAG_OID = 0x06
TAG_UTC_TIME = 0x17
TAG_SEQUENCE = 0x30
TAG_SET = 0x31


def _length(size: int) -> bytes:
    if size < 0x80:
        return bytes([size])
    body = size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def tlv(tag: int, content: bytes) -> bytes:
    """One DER element."""
    return bytes([tag]) + _length(len(content)) + content


def integer(value: int) -> bytes:
    """A DER INTEGER, two's complement, minimal length."""
    if value == 0:
        return tlv(TAG_INTEGER, b"\x00")
    # One spare bit for the sign, so a positive value with its top bit set gets
    # the leading zero byte DER requires.
    size = (value.bit_length() + 8) // 8
    return tlv(TAG_INTEGER, value.to_bytes(size, "big", signed=True))


def oid(dotted: str) -> bytes:
    """A DER OBJECT IDENTIFIER from its dotted form."""
    parts = [int(p) for p in dotted.split(".")]
    body = bytearray([parts[0] * 40 + parts[1]])
    for part in parts[2:]:
        chunk = [part & 0x7F]
        part >>= 7
        while part:
            chunk.append(0x80 | (part & 0x7F))
            part >>= 7
        body.extend(reversed(chunk))
    return tlv(TAG_OID, bytes(body))


def octet_string(value: bytes) -> bytes:
    return tlv(TAG_OCTET_STRING, value)


def sequence(*items: bytes) -> bytes:
    return tlv(TAG_SEQUENCE, b"".join(items))


def set_of(*items: bytes) -> bytes:
    """A DER SET OF: elements sorted by their encoding, as DER requires."""
    return tlv(TAG_SET, b"".join(sorted(items)))


def context(number: int, content: bytes, *, constructed: bool = True) -> bytes:
    """A context specific tag ``[number]`` around already encoded content."""
    return tlv((0xA0 if constructed else 0x80) | number, content)


def utc_time(moment: datetime) -> bytes:
    """A UTCTime ``YYMMDDHHMMSSZ`` (valid for 1950-2049)."""
    stamp = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
    return tlv(TAG_UTC_TIME, stamp.strftime("%y%m%d%H%M%SZ").encode("ascii"))


# ── Reading ──────────────────────────────────────────────────────────────────


class DerError(ValueError):
    """The bytes are not the DER structure that was expected."""


@dataclass(frozen=True)
class Element:
    tag: int
    # The whole element, header included, exactly as it appears in the input.
    raw: bytes
    content: bytes

    @property
    def constructed(self) -> bool:
        return bool(self.tag & 0x20)

    def children(self) -> list[Element]:
        return read_all(self.content)


def read_one(data: bytes, offset: int = 0) -> tuple[Element, int]:
    """One element at ``offset`` and the offset just past it."""
    if offset + 2 > len(data):
        raise DerError("truncated DER header")
    tag = data[offset]
    first = data[offset + 1]
    pos = offset + 2
    if first < 0x80:
        size = first
    else:
        count = first & 0x7F
        if count == 0 or count > 4 or pos + count > len(data):
            raise DerError("unsupported DER length")
        size = int.from_bytes(data[pos : pos + count], "big")
        pos += count
    end = pos + size
    if end > len(data):
        raise DerError("truncated DER content")
    return Element(tag=tag, raw=data[offset:end], content=data[pos:end]), end


def read_all(data: bytes) -> list[Element]:
    """Every element in a run of concatenated DER elements."""
    out: list[Element] = []
    offset = 0
    while offset < len(data):
        element, offset = read_one(data, offset)
        out.append(element)
    return out


def read(data: bytes) -> Element:
    """Exactly one element; trailing bytes are an error."""
    element, end = read_one(data, 0)
    if end != len(data):
        raise DerError("trailing bytes after the DER element")
    return element


__all__ = [
    "DerError",
    "Element",
    "context",
    "integer",
    "octet_string",
    "oid",
    "read",
    "read_all",
    "read_one",
    "sequence",
    "set_of",
    "tlv",
    "utc_time",
]
