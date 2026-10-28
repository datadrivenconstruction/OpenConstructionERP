# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The change order audit trail says who submitted and approved it.

``submitted_by``, ``approved_by`` and ``rejected_by`` are free-text columns and
the demo estate writes a user id into all three. The audit cards under a change
order printed the column as it stood, so the line under "Submitted" read
``3f2b8c1e-9a44-...`` - on the one screen whose whole job is to show who signed
off a cost change.

These cases hold the resolved names on the wire. They also hold the two things
that are easy to lose while adding them: a page must not cost a query per row,
and an id nobody answers to must not come back as though the order was never
submitted.

Run:
    python -m pytest tests/unit/test_change_order_party_names.py -q
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.modules.changeorders.router import (
    _order_response,
    _order_responses,
    _order_to_response,
    _order_to_with_items,
    _order_with_items_response,
)

FIRM = uuid.uuid4()
USER = uuid.uuid4()
STRANGER = uuid.uuid4()


# ── Stubs ────────────────────────────────────────────────────────────────


class _Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _Nested:
    async def __aenter__(self) -> _Nested:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _StubSession:
    """Answers the two lookups the resolver makes, and counts the asking.

    Which table a statement is against is read off the compiled SQL rather than
    off call order, so a test cannot pass by accident when the order of the two
    lookups changes.
    """

    def __init__(
        self,
        rows: list[tuple[Any, ...]] | None = None,
        users: list[tuple[Any, ...]] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.rows = rows if rows is not None else [(FIRM, "Bauunternehmung Keller", None, None, None)]
        self.users = users if users is not None else [(USER, "Tom Fischer", "t.fischer@example.com")]
        self.raises = raises
        self.queries = 0

    def begin_nested(self) -> _Nested:
        return _Nested()

    async def execute(self, stmt: object) -> _Rows:
        self.queries += 1
        if self.raises is not None:
            raise self.raises
        return _Rows(self.users if "oe_users_user" in str(stmt) else self.rows)


def _order(**over: Any) -> SimpleNamespace:
    """A change order with the attributes the response builders read."""
    now = datetime.now(UTC)
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "code": "CO-004",
        "title": "Additional ground beams at grid C",
        "description": "",
        "reason_category": "design_change",
        "status": "approved",
        "submitted_by": None,
        "approved_by": None,
        "rejected_by": None,
        "submitted_at": now.isoformat(),
        "approved_at": now.isoformat(),
        "rejected_at": None,
        "cost_impact": "18400.00",
        "schedule_impact_days": 6,
        "currency": "EUR",
        "metadata_": {},
        "created_at": now,
        "updated_at": now,
        "items": [],
        "linked_po_ids": [],
        "linked_rfi_ids": [],
        "current_approval_step": None,
    }
    fields.update(over)
    return SimpleNamespace(**fields)


# ── The wire ─────────────────────────────────────────────────────────────


class TestOneOrder:
    def test_a_contact_id_comes_back_as_the_firm(self) -> None:
        session = _StubSession()
        order = _order(submitted_by=str(FIRM))
        out = asyncio.run(_order_response(session, order))  # type: ignore[arg-type]
        assert out.submitted_by_name == "Bauunternehmung Keller"

    def test_a_user_id_comes_back_as_the_person(self) -> None:
        # The approval control on the screen is a list of platform users, so
        # the same column holds a user id where the seeder holds a contact id.
        session = _StubSession()
        out = asyncio.run(_order_response(session, _order(approved_by=str(USER))))  # type: ignore[arg-type]
        assert out.approved_by_name == "Tom Fischer"

    def test_all_three_milestones_are_resolved(self) -> None:
        # A rejection writes its own column and is the one milestone a reader
        # most wants a name against.
        session = _StubSession()
        order = _order(submitted_by=str(USER), approved_by=str(FIRM), rejected_by=str(USER))
        out = asyncio.run(_order_response(session, order))  # type: ignore[arg-type]
        assert (out.submitted_by_name, out.approved_by_name, out.rejected_by_name) == (
            "Tom Fischer",
            "Bauunternehmung Keller",
            "Tom Fischer",
        )

    def test_a_typed_name_is_never_sent_to_the_database(self) -> None:
        # Somebody typed a name into the column. That name is already the
        # answer, and looking it up is a query that can only fail.
        session = _StubSession()
        out = asyncio.run(_order_response(session, _order(submitted_by="Anna Schmidt")))  # type: ignore[arg-type]
        assert session.queries == 0
        assert out.submitted_by == "Anna Schmidt"
        assert out.submitted_by_name is None

    def test_an_id_nobody_answers_to_leaves_the_raw_value_standing(self) -> None:
        # The order WAS submitted; we merely cannot name who by. Blanking the
        # column would say it was never submitted at all.
        session = _StubSession()
        out = asyncio.run(_order_response(session, _order(submitted_by=str(STRANGER))))  # type: ignore[arg-type]
        assert out.submitted_by == str(STRANGER)
        assert out.submitted_by_name is None

    def test_an_unsubmitted_order_asks_nothing(self) -> None:
        session = _StubSession()
        out = asyncio.run(_order_response(session, _order()))  # type: ignore[arg-type]
        assert session.queries == 0
        assert out.submitted_by_name is None


class TestAPage:
    def test_a_page_resolves_every_row_in_one_pass(self) -> None:
        # Two queries for the whole page - one per register - however long the
        # page is. A lookup per row is what this exists to avoid.
        session = _StubSession()
        page = [_order(submitted_by=str(FIRM), approved_by=str(USER)) for _ in range(25)]
        out = asyncio.run(_order_responses(session, page))  # type: ignore[arg-type]
        assert session.queries == 2
        assert {o.submitted_by_name for o in out} == {"Bauunternehmung Keller"}
        assert {o.approved_by_name for o in out} == {"Tom Fischer"}

    def test_the_detail_view_answers_the_same_as_the_list(self) -> None:
        # Two builders, one register. They drifted apart once already, which is
        # how the detail card kept an id after the list had a name.
        session = _StubSession()
        order = _order(submitted_by=str(FIRM), approved_by=str(USER))
        listed = asyncio.run(_order_responses(session, [order]))[0]  # type: ignore[arg-type]
        detail = asyncio.run(_order_with_items_response(session, order))  # type: ignore[arg-type]
        assert (detail.submitted_by_name, detail.approved_by_name) == (
            listed.submitted_by_name,
            listed.approved_by_name,
        )


class TestFailSoft:
    def test_a_missing_contacts_table_costs_a_name_and_not_the_page(self) -> None:
        # Contacts is an optional module. Without it the order still lists,
        # carrying the id it stored.
        session = _StubSession(raises=RuntimeError("relation does not exist"))
        out = asyncio.run(_order_response(session, _order(submitted_by=str(FIRM))))  # type: ignore[arg-type]
        assert out.submitted_by == str(FIRM)
        assert out.submitted_by_name is None

    def test_a_builder_called_without_names_still_builds(self) -> None:
        # The synchronous builders are called from places that have no session
        # to hand. They must degrade to the raw value, not raise.
        out = _order_to_response(_order(submitted_by=str(FIRM)))
        assert out.submitted_by_name is None
        assert _order_to_with_items(_order(approved_by=str(USER))).approved_by_name is None
