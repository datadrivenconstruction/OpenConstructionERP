# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Age of an offline-captured op, judged against the server clock.

A phone that was off for weeks may hold a capture whose facts have moved on
(the punch item was closed, the delivery was invoiced). Past the limit the op is
refused with a reason code and the person re-enters it, rather than the server
replaying a stale write silently. The server clock decides, never the device
clock, so a wrong phone clock cannot widen or narrow the window.
"""

from __future__ import annotations

from datetime import UTC, datetime

MAX_OP_AGE_DAYS = 30
REASON_OP_TOO_OLD = "op_too_old"
WARNING_CAPTURED_AT_MISSING = "captured_at_missing"
WARNING_CAPTURED_AT_UNREADABLE = "captured_at_unreadable"


def parse_captured_at(value: str | None) -> datetime | None:
    """Read an ISO timestamp (``Z`` accepted); ``None`` when absent or unreadable."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def op_age_days(captured_at: str | None, now: datetime | None = None) -> int | None:
    """Whole days between capture and the server clock; ``None`` when unknown. Never negative."""
    captured = parse_captured_at(captured_at)
    if captured is None:
        return None
    current = now or datetime.now(UTC)
    return max(0, (current - captured).days)


def capture_time_warning(captured_at: str | None) -> str | None:
    """Warning code for a capture with no usable time. Such an op is judged as captured now."""
    if not captured_at or not captured_at.strip():
        return WARNING_CAPTURED_AT_MISSING
    return None if parse_captured_at(captured_at) is not None else WARNING_CAPTURED_AT_UNREADABLE
