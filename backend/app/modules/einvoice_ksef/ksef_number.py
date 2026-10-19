# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The KSeF number: its shape and its checksum.

``9999999999-RRRRMMDD-FFFFFFFFFFFF-FF``: the seller's NIP, the day KSeF took the
invoice in, twelve hex digits KSeF assigns, and a CRC-8 (polynomial 0x07, initial
value 0x00) over the 32 characters before the last dash, as two upper-case hex
digits. Source: https://github.com/CIRFMF/ksef-docs/blob/main/faktury/numer-ksef.md
(read 2026-10-19).

The FA(3) schema's ``TNumerKSeF`` pattern is wider than the document: it lets the
first segment be an internal identifier and lets the twelve hex digits carry a
dash in the middle. :func:`problems` accepts what the schema accepts and checks
the CRC over whatever the number holds before its checksum.
"""

from __future__ import annotations

import re
from datetime import date

# The FA(3) TNumerKSeF pattern, anchored.
_PATTERN = re.compile(
    r"^([1-9]((\d[1-9])|([1-9]\d))\d{7}|M\d{9}|[A-Z]{3}\d{7})"
    r"-(20[2-9][0-9]|2[1-9][0-9]{2}|[3-9][0-9]{3})(0[1-9]|1[0-2])(0[1-9]|[1-2][0-9]|3[0-1])"
    r"-([0-9A-F]{6})-?([0-9A-F]{6})-([0-9A-F]{2})$"
)

# The handle a clearance document carries while KSeF is still processing it.
# Deliberately not number-shaped: nothing that starts with it can pass the check.
PENDING_HANDLE_PREFIX = "ksef-ref:"


def crc8(data: bytes) -> int:
    """CRC-8 with polynomial 0x07 and initial value 0x00, no reflection, no final XOR."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def checksum(data_part: str) -> str:
    """The two hex digits KSeF appends to ``data_part``."""
    return f"{crc8(data_part.encode('ascii')):02X}"


def problems(value: str) -> list[str]:
    """What is wrong with ``value`` as a KSeF number. Empty when it is one."""
    text = (value or "").strip()
    if not text:
        return ["the KSeF number is empty"]
    if text.startswith(PENDING_HANDLE_PREFIX):
        return ["this is a processing reference, not a KSeF number: KSeF has not assigned the number yet"]
    match = _PATTERN.match(text)
    if not match:
        return [f"{text!r} does not have the shape of a KSeF number (NIP-YYYYMMDD-hex-checksum)"]
    stamp = text.split("-")[1]
    try:
        date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
    except ValueError:
        return [f"{text!r} carries {stamp}, which is not a calendar date"]
    data_part, _, given = text.rpartition("-")
    expected = checksum(data_part)
    if given != expected:
        return [f"the checksum of {text!r} is {given}, but its digits give {expected}"]
    return []


def is_valid(value: str) -> bool:
    """Whether ``value`` is a well-formed KSeF number with a correct checksum."""
    return not problems(value)


def seller_nip(value: str) -> str:
    """The first segment of a KSeF number: the seller's NIP (or internal identifier)."""
    return (value or "").strip().split("-", 1)[0]


def pending_handle(session_reference: str, invoice_reference: str) -> str:
    """The identifier a document carries while KSeF processes it."""
    return f"{PENDING_HANDLE_PREFIX}{session_reference}/{invoice_reference}"


def parse_pending_handle(value: str) -> tuple[str, str] | None:
    """``(session_reference, invoice_reference)`` from a handle, or ``None``."""
    text = (value or "").strip()
    if not text.startswith(PENDING_HANDLE_PREFIX):
        return None
    session, sep, invoice = text[len(PENDING_HANDLE_PREFIX) :].partition("/")
    if not sep or not session or not invoice:
        return None
    return session, invoice


__all__ = [
    "PENDING_HANDLE_PREFIX",
    "checksum",
    "crc8",
    "is_valid",
    "parse_pending_handle",
    "pending_handle",
    "problems",
    "seller_nip",
]
