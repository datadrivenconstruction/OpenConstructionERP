"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the RFI router-computed UX fields the new chips rely on.

The frontend ball-in-court chip ("With you / With them / Answered /
Closed"), the "+N" overdue pill, and the "Awaiting me" quick-view chip
all depend on the **server-side** ``RFIResponse`` shape exposing:

    1. ``is_overdue: bool``         — only true for actionable
       (draft/open) RFIs whose ``response_due_date`` is past today.
       Answered / closed rows must **never** show as overdue, otherwise
       the quick-filter chip would over-report.
    2. ``days_open: int >= 0``      — for the "Days" column. Caps at
       responded_at for answered/closed so the number stops climbing
       after the response landed.
    3. ``ball_in_court: str | null``— what the BIC badge keys on. Must
       reflect the server's authoritative value (not the client's last
       cached snapshot).

We test the **router-level** ``_compute_rfi_fields`` helper directly
because it is the single source of truth for both ``GET /rfi/`` and
``GET /rfi/{id}``. If it ever drifts, every consumer (list page, detail
page, mobile cards, Excel export) drifts with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.rfi.router import _compute_rfi_fields


@dataclass
class _Item:
    """Bare minimum shape ``_compute_rfi_fields`` reads off the ORM row."""

    status: str
    created_at: datetime
    response_due_date: str | None = None
    responded_at: str | None = None


class TestComputeRFIFields:
    def test_open_overdue_when_due_date_in_past(self) -> None:
        """A still-open RFI past its due date is overdue."""
        item = _Item(
            status="open",
            created_at=datetime.now(UTC) - timedelta(days=10),
            response_due_date=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
        )
        is_overdue, days_open = _compute_rfi_fields(item)
        assert is_overdue is True
        assert days_open >= 9  # might be 9 or 10 depending on rounding

    def test_open_not_overdue_when_due_date_in_future(self) -> None:
        item = _Item(
            status="open",
            created_at=datetime.now(UTC) - timedelta(days=2),
            response_due_date=(datetime.now(UTC) + timedelta(days=5)).isoformat(),
        )
        is_overdue, _ = _compute_rfi_fields(item)
        assert is_overdue is False

    def test_answered_rfi_is_never_overdue(self) -> None:
        """BUG-RFI-OVERDUE-LEAK: a past-due answered RFI must report
        ``is_overdue=False`` so the 'Overdue' quick filter and the
        red days-open colouring don't keep flagging RFIs that have
        already been answered. Drove the front-end pill logic — if
        this regresses, every answered RFI screams red in the table."""
        item = _Item(
            status="answered",
            created_at=datetime.now(UTC) - timedelta(days=15),
            response_due_date=(datetime.now(UTC) - timedelta(days=3)).isoformat(),
            responded_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )
        is_overdue, _ = _compute_rfi_fields(item)
        assert is_overdue is False

    def test_closed_rfi_is_never_overdue(self) -> None:
        item = _Item(
            status="closed",
            created_at=datetime.now(UTC) - timedelta(days=30),
            response_due_date=(datetime.now(UTC) - timedelta(days=5)).isoformat(),
            responded_at=(datetime.now(UTC) - timedelta(days=3)).isoformat(),
        )
        is_overdue, _ = _compute_rfi_fields(item)
        assert is_overdue is False

    def test_days_open_stops_at_responded_at_for_answered(self) -> None:
        """``days_open`` must freeze at the response date so the chip
        stops climbing after the answer lands. This is what makes the
        avg-days-to-response stat meaningful."""
        created = datetime.now(UTC) - timedelta(days=20)
        responded = datetime.now(UTC) - timedelta(days=5)
        item = _Item(
            status="answered",
            created_at=created,
            responded_at=responded.isoformat(),
        )
        _, days_open = _compute_rfi_fields(item)
        # 20 - 5 = 15 days from creation to response.
        assert 14 <= days_open <= 15

    def test_days_open_is_never_negative(self) -> None:
        """Robustness — a wonky ``responded_at`` earlier than
        ``created_at`` must not produce a negative number that breaks
        the tabular-nums rendering on the row."""
        item = _Item(
            status="answered",
            created_at=datetime.now(UTC),
            responded_at=(datetime.now(UTC) - timedelta(days=5)).isoformat(),
        )
        _, days_open = _compute_rfi_fields(item)
        assert days_open >= 0

    def test_no_due_date_means_not_overdue(self) -> None:
        item = _Item(
            status="open",
            created_at=datetime.now(UTC) - timedelta(days=30),
        )
        is_overdue, _ = _compute_rfi_fields(item)
        assert is_overdue is False

    def test_draft_status_is_overdue_eligible(self) -> None:
        """Drafts shouldn't sit forever — if a draft has a due date
        that's already past, the overdue pill should still flag it
        so a sloppy "saved as draft and forgot" RFI surfaces in the
        Overdue quick view."""
        item = _Item(
            status="draft",
            created_at=datetime.now(UTC) - timedelta(days=10),
            response_due_date=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )
        is_overdue, _ = _compute_rfi_fields(item)
        assert is_overdue is True

    @pytest.mark.parametrize("status", ["void", "closed"])
    def test_terminal_states_never_overdue(self, status: str) -> None:
        item = _Item(
            status=status,
            created_at=datetime.now(UTC) - timedelta(days=30),
            response_due_date=(datetime.now(UTC) - timedelta(days=10)).isoformat(),
        )
        is_overdue, _ = _compute_rfi_fields(item)
        assert is_overdue is False
