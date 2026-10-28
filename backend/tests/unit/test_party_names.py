# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The core party resolver, tested where it lives rather than through a caller.

``test_punch_assignee_names.py`` covers this logic through the punch list,
which is where it was written. It now serves inspections and deadlines as well,
and a rule tested only at one caller is tested at the caller that was already
right. So the guarantees every caller depends on are pinned here, against the
helper itself.

What is pinned:

* an id resolves against contacts and platform users both, because the column
  receives both, and the result is keyed by the value as it is *stored*, so a
  caller can look a row up without re-normalising;
* text that is not an id never reaches the database - a typed-in name is
  already the answer, and on PostgreSQL a name compared against a uuid column
  raises, which would turn a cosmetic lookup into a failed list request;
* an id that answers to nobody is absent from the result rather than present
  and empty, so the caller prints the record as having an owner it cannot name
  instead of blanking the cell or claiming it is unassigned;
* a whole page costs a fixed number of lookups whatever its length;
* each lookup runs in its own savepoint, so one that fails costs a name and not
  the caller's transaction. A bare try/except cannot give that back: a failed
  statement poisons the session until something rolls it back.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.party_names import canonical_id, contact_display_name, resolve_party_names

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
    def __init__(self, session: _StubSession) -> None:
        self._session = session

    async def __aenter__(self) -> _Nested:
        self._session.savepoints += 1
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _StubSession:
    """Answers both lookups and counts the asking and the savepoints.

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
        self.savepoints = 0

    def begin_nested(self) -> _Nested:
        return _Nested(self)

    async def execute(self, stmt: object) -> _Rows:
        self.queries += 1
        if self.raises is not None:
            raise self.raises
        return _Rows(self.users if "oe_users_user" in str(stmt) else self.rows)


# ── The resolution ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_id_resolves_against_both_registers() -> None:
    session = _StubSession()
    names = await resolve_party_names(session, [str(FIRM), str(USER)])  # type: ignore[arg-type]
    assert names[str(FIRM)] == "Bauunternehmung Keller"
    assert names[str(USER)] == "Tom Fischer"


@pytest.mark.asyncio
async def test_the_key_is_the_value_as_stored() -> None:
    # A column holds whatever was written into it, and the caller looks the row
    # up by that exact string. An id stored upper-cased comes back under the
    # key it was passed rather than under a re-normalised one.
    session = _StubSession()
    stored = str(FIRM).upper()
    names = await resolve_party_names(session, [stored])  # type: ignore[arg-type]
    assert names.get(stored) == "Bauunternehmung Keller"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["Jane Cooper", "", "   ", None, "not-an-id"])
async def test_a_value_that_cannot_be_an_id_is_never_queried(value: str | None) -> None:
    session = _StubSession()
    assert await resolve_party_names(session, [value]) == {}  # type: ignore[arg-type]
    assert session.queries == 0, "a typed-in name must not reach the database"


@pytest.mark.asyncio
async def test_an_id_matching_nothing_is_absent_rather_than_empty() -> None:
    # Absent, not "": the caller prints the stored value, which on a deleted
    # party is the only trace left. An empty string blanks the cell, and
    # "unassigned" invites a second assignment over a record that has an owner.
    session = _StubSession(rows=[], users=[])
    orphan = str(uuid.uuid4())
    assert orphan not in await resolve_party_names(session, [orphan])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_nameless_contact_does_not_become_a_blank_name() -> None:
    # A contact whose every name column is blank must not shadow the id with an
    # empty string. Note the trading name here is a single space, which an
    # ``or`` chain on the raw column would happily return as the answer.
    session = _StubSession(rows=[(FIRM, " ", None, None, None)], users=[])
    assert await resolve_party_names(session, [str(FIRM)]) == {}  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_page_costs_a_fixed_number_of_lookups() -> None:
    session = _StubSession()
    await resolve_party_names(session, [str(FIRM), str(PERSON), str(USER)] * 50)  # type: ignore[arg-type]
    assert session.queries == 2, "the cost of a page must not grow with its length"


@pytest.mark.asyncio
async def test_users_are_asked_only_about_what_contacts_could_not_name() -> None:
    # A register whose rows all carry seeded contact ids has no question left
    # for the users table, and asking anyway doubles the cost of every page in
    # the product. The saving leaves no trace in the result, so the count of
    # the asking is the only thing that can hold it in place.
    session = _StubSession()
    names = await resolve_party_names(session, [str(FIRM), str(PERSON)])  # type: ignore[arg-type]
    assert set(names) == {str(FIRM), str(PERSON)}
    assert session.queries == 1, "every id was a contact, so there was nothing to ask users"


@pytest.mark.asyncio
async def test_a_contact_wins_a_collision_with_a_user() -> None:
    # Generated ids cannot collide, so this is about what the order means
    # rather than about a case anybody will meet: the contacts register is the
    # more specific answer. Asking users second is what implements the
    # tie-break, which is why the two claims are tested apart - restoring the
    # eager version keeps this test green and breaks the one above it.
    session = _StubSession(
        rows=[(FIRM, "Bauunternehmung Keller", None, None, None)],
        users=[(FIRM, "Tom Fischer", "t.fischer@example.com")],
    )
    names = await resolve_party_names(session, [str(FIRM)])  # type: ignore[arg-type]
    assert names[str(FIRM)] == "Bauunternehmung Keller"


# ── Failing soft ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_lookup_runs_in_its_own_savepoint() -> None:
    session = _StubSession()
    await resolve_party_names(session, [str(FIRM), str(USER)])  # type: ignore[arg-type]
    assert session.savepoints == 2, "a lookup outside a savepoint can poison the caller's transaction"


@pytest.mark.asyncio
async def test_an_unreadable_table_costs_the_names_and_nothing_else() -> None:
    session = _StubSession(raises=RuntimeError("relation contacts does not exist"))
    assert await resolve_party_names(session, [str(FIRM), str(USER)]) == {}  # type: ignore[arg-type]


# ── The name itself ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("company", "legal", "first", "last", "expected"),
    [
        ("Keller", "Keller GmbH", "Anna", "Schmidt", "Keller"),
        # The person outranks the legal entity: that is the order the contacts
        # register uses for its own row label (``Contact.__repr__``).
        (None, "Keller GmbH", "Anna", "Schmidt", "Anna Schmidt"),
        # A firm entered from a contract carries a legal name and nobody's name.
        (" ", "Keller GmbH & Co. KG", None, None, "Keller GmbH & Co. KG"),
        (None, None, "Anna", "Schmidt", "Anna Schmidt"),
        (None, None, None, "Schmidt", "Schmidt"),
        (None, None, None, None, ""),
    ],
)
def test_a_contact_is_named_trading_then_person_then_legal(
    company: str | None, legal: str | None, first: str | None, last: str | None, expected: str
) -> None:
    assert contact_display_name(company, legal, first, last) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (str(FIRM), str(FIRM)),
        (str(FIRM).upper(), str(FIRM)),
        (FIRM, str(FIRM)),
        # Not an id at all: handed back as it came rather than raising, so the
        # caller's lookup simply misses instead of failing the request.
        ("Jane Cooper", "Jane Cooper"),
    ],
)
def test_two_shapes_of_the_same_id_compare_equal(value: object, expected: str) -> None:
    assert canonical_id(value) == expected
