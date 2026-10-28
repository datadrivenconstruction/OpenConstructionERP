# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A punch item names its owner rather than quoting an id at the reader.

``assigned_to`` and ``verified_by`` are free-text columns, and a typed-in name,
a contact id and a user id are all legitimate contents. The seeder writes a
contact id and the assignment control on the screen writes a user id, and every
screen printed whichever it got, so a row read "Assigned To 3f2b8c1e-9a44-..."
and the avatar beside it took its initial from a hex digit.

What is pinned here:

* an id resolves to the name its register holds - contacts and platform users
  both, since the column receives both - keyed by the value as it is stored, so
  the caller can look it up without re-normalising;
* text that is not an id is never queried, because a typed-in name is already
  the answer;
* a whole page costs two lookups whatever its length, which is why this lives
  in the router rather than on the page: the punch list is the slowest screen
  in the module and a per-row request would be felt;
* contacts is an optional module and a row can be deleted, so a failed or empty
  lookup returns nothing rather than raising or inventing a name, and each runs
  inside a savepoint so it cannot abort the caller's transaction.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

# Naming a party is now one rule for every register that stores one, so the
# helper is imported from where it lives rather than from the module that
# happened to write it first. Every assertion below is unchanged, which is the
# point: they are the guard that the move changed none of the answers.
from app.core.party_names import contact_display_name as _contact_display_name
from app.modules.punchlist.router import _item_response, _item_responses, _item_to_response
from app.modules.punchlist.service import (
    PunchListService,
    _render_punchlist_text,
)

FIRM = uuid.uuid4()
PERSON = uuid.uuid4()
USER = uuid.uuid4()


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

    Which table a statement is against is read off the compiled SQL rather
    than off call order, so a test cannot pass by accident when the order of
    the two lookups changes.
    """

    def __init__(
        self,
        rows: list[tuple[Any, ...]] | None = None,
        users: list[tuple[Any, ...]] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.rows = (
            rows
            if rows is not None
            else [
                (FIRM, "Bauunternehmung Keller", "Keller GmbH & Co. KG", None, None),
                (PERSON, None, None, "Anna", "Schmidt"),
            ]
        )
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


def _service(**kwargs: Any) -> tuple[PunchListService, _StubSession]:
    session = _StubSession(**kwargs)
    return PunchListService(session), session  # type: ignore[arg-type]


def _item(**over: Any) -> SimpleNamespace:
    """A punch row with the attributes the response builder reads."""
    now = datetime.now(UTC)
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "title": "Sealant missing at window reveal",
        "description": "",
        "document_id": None,
        "page": None,
        "location_x": None,
        "location_y": None,
        "priority": "medium",
        "status": "open",
        "assigned_to": None,
        "due_date": None,
        "category": None,
        "trade": None,
        "photos": [],
        "geo_lat": None,
        "geo_lon": None,
        "rework_cost": None,
        "rework_cost_currency": "EUR",
        "resolution_notes": None,
        "resolved_at": None,
        "verified_at": None,
        "verified_by": None,
        "created_by": None,
        "metadata_": {},
        "reopen_history": [],
        "created_at": now,
        "updated_at": now,
    }
    fields.update(over)
    return SimpleNamespace(**fields)


# ── The lookup ───────────────────────────────────────────────────────────


class TestResolvePartyNames:
    def test_an_id_becomes_the_name_the_register_holds(self) -> None:
        service, session = _service()
        found = asyncio.run(service.resolve_party_names([str(FIRM), str(PERSON)]))
        assert found == {str(FIRM): "Bauunternehmung Keller", str(PERSON): "Anna Schmidt"}
        # One: both ids were contacts, so nothing was left to ask users about.
        assert session.queries == 1

    def test_a_typed_in_name_is_never_looked_up(self) -> None:
        # Someone wrote a name into the field. That name is the answer, and
        # asking the database about it would be one query per page for nothing.
        service, session = _service()
        assert asyncio.run(service.resolve_party_names(["Anna Schmidt", "", None, "   "])) == {}
        assert session.queries == 0

    def test_the_key_is_the_value_as_stored(self) -> None:
        # An id written in upper case still has to be findable by the caller,
        # which holds the raw column value and nothing else.
        service, _session = _service()
        stored = str(FIRM).upper()
        assert asyncio.run(service.resolve_party_names([stored])) == {stored: "Bauunternehmung Keller"}

    def test_a_whole_page_costs_one_query(self) -> None:
        service, session = _service()
        page = [str(FIRM), str(PERSON)] * 25 + ["Anna Schmidt", None]
        assert len(asyncio.run(service.resolve_party_names(page))) == 2
        # The same count for a page of any length, which is the claim. Fifty-two
        # values here: a per-row lookup would show as fifty-two.
        assert session.queries == 1

    def test_an_unreadable_table_resolves_to_nothing(self) -> None:
        # Contacts is an optional module and the row may have been deleted.
        # Neither is a reason to fail a punch list read.
        service, _session = _service(raises=RuntimeError("relation contacts does not exist"))
        assert asyncio.run(service.resolve_party_names([str(FIRM)])) == {}

    def test_a_platform_user_is_named_too(self) -> None:
        # The assignment control on the screen lists users, so a snag assigned
        # through the UI carries a user id in the same column as a contact id.
        service, _session = _service()
        assert asyncio.run(service.resolve_party_names([str(USER)])) == {str(USER): "Tom Fischer"}

    def test_a_user_with_no_name_falls_back_to_the_address(self) -> None:
        # full_name defaults to an empty string, and an address still tells a
        # foreman who to call.
        service, _session = _service(users=[(USER, "   ", "t.fischer@example.com")])
        assert asyncio.run(service.resolve_party_names([str(USER)])) == {str(USER): "t.fischer@example.com"}

    def test_an_id_matching_nothing_stays_unresolved(self) -> None:
        service, _session = _service(rows=[], users=[])
        assert asyncio.run(service.resolve_party_names([str(uuid.uuid4())])) == {}

    def test_the_shape_the_driver_returns_does_not_decide_the_answer(self) -> None:
        # The id column is a type decorator over VARCHAR(36) that parses back
        # into a UUID, and it falls through to the raw string for anything it
        # cannot parse. Comparing one shape against the other would resolve
        # nothing and say nothing, which reads on screen as "every owner is
        # unknown" - strictly worse than the id it replaced. Both sides go
        # through the same normalisation, so either shape has to work.
        service, _session = _service(rows=[(str(FIRM), "Bauunternehmung Keller", None, None, None)])
        assert asyncio.run(service.resolve_party_names([str(FIRM)])) == {str(FIRM): "Bauunternehmung Keller"}

    def test_a_nameless_contact_is_not_a_blank_name(self) -> None:
        service, _session = _service(rows=[(FIRM, "", None, None, "  ")], users=[])
        assert asyncio.run(service.resolve_party_names([str(FIRM)])) == {}


class TestContactDisplayName:
    """The order the contacts register itself uses, mirrored."""

    def test_the_trading_name_comes_first(self) -> None:
        assert _contact_display_name("Keller", "Keller GmbH", "Anna", "Schmidt") == "Keller"

    def test_a_person_when_there_is_no_firm(self) -> None:
        assert _contact_display_name(None, None, "Anna", "Schmidt") == "Anna Schmidt"

    def test_half_a_person_is_still_a_name(self) -> None:
        assert _contact_display_name(None, None, None, "Schmidt") == "Schmidt"

    def test_the_legal_entity_is_the_last_resort(self) -> None:
        assert _contact_display_name(" ", "Keller GmbH & Co. KG", None, None) == "Keller GmbH & Co. KG"

    def test_a_contact_with_no_name_at_all(self) -> None:
        assert _contact_display_name(None, None, None, None) == ""


# ── The response ─────────────────────────────────────────────────────────


class TestResponseCarriesTheName:
    def test_both_party_columns_are_resolved(self) -> None:
        service, session = _service()
        item = _item(assigned_to=str(FIRM), verified_by=str(PERSON))
        response = asyncio.run(_item_response(service, item))
        assert response.assigned_to == str(FIRM)
        assert response.assigned_to_name == "Bauunternehmung Keller"
        assert response.verified_by_name == "Anna Schmidt"
        # One lookup for both columns together, not one per column.
        assert session.queries == 1

    def test_a_typed_in_name_leaves_the_resolved_field_empty(self) -> None:
        # Null here is what the screen reads as "print the column".
        service, _session = _service()
        response = asyncio.run(_item_response(service, _item(assigned_to="Anna Schmidt")))
        assert response.assigned_to == "Anna Schmidt"
        assert response.assigned_to_name is None

    def test_an_unassigned_item_asks_nothing(self) -> None:
        service, session = _service()
        response = asyncio.run(_item_response(service, _item()))
        assert response.assigned_to is None
        assert response.assigned_to_name is None
        assert session.queries == 0

    def test_a_page_resolves_every_row_in_one_query(self) -> None:
        service, session = _service()
        items = [_item(assigned_to=str(FIRM)) for _ in range(20)]
        items.append(_item(assigned_to=str(PERSON), verified_by=str(FIRM)))
        responses = asyncio.run(_item_responses(service, items))
        assert [r.assigned_to_name for r in responses[:20]] == ["Bauunternehmung Keller"] * 20
        assert responses[20].assigned_to_name == "Anna Schmidt"
        assert responses[20].verified_by_name == "Bauunternehmung Keller"
        assert session.queries == 1

    def test_the_exported_list_names_the_same_party_the_screen_names(self) -> None:
        # The export is the artefact that leaves the building. A screen saying
        # "Bauunternehmung Keller" over a spreadsheet saying "3f2b8c1e-..." is
        # one concept rendered twice and disagreeing, which is the shape this
        # whole change exists to remove.
        item = _item(assigned_to=str(FIRM))
        text = _render_punchlist_text(uuid.uuid4(), [item], {str(FIRM): "Bauunternehmung Keller"})
        assert "Assigned to: Bauunternehmung Keller" in text
        assert str(FIRM) not in text

    def test_an_export_still_prints_an_unresolved_id_rather_than_a_blank(self) -> None:
        # A name we cannot resolve is worse as an empty cell: the id can at
        # least be looked up by whoever receives the sheet.
        item = _item(assigned_to=str(FIRM))
        assert str(FIRM) in _render_punchlist_text(uuid.uuid4(), [item], {})

    def test_the_builder_is_usable_without_any_names(self) -> None:
        # The pure builder keeps working for callers that have no session to
        # spend, which is what makes the resolution opt-in rather than a
        # dependency of the schema.
        response = _item_to_response(_item(assigned_to=str(FIRM)))
        assert response.assigned_to_name is None
