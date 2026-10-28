"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: schedule activities list in code order, not in text order (internal #167).

``ActivityRepository.list_for_schedule`` ordered by ``sort_order`` then
``wbs_code``. ``wbs_code`` is a ``String(50)``, so the second term compared
text: ``"10"`` sorted before ``"2"``. That only bites when the first term
fails to separate the rows - and it separates nothing at all in a schedule
whose rows carry the column's default of 0, which is exactly what the demo
seeder writes (it never passes ``sort_order``). A 35-activity programme
therefore listed as 1, 10, 11 ... 19, 2, 20 ...

The order has to be settled in SQL because the read is paginated: sorting a
page after it arrives only rearranges that page, so the list looks fixed on
page one and is still wrong at the boundary.
:func:`test_natural_order_holds_across_a_pagination_boundary` is the test
that would have caught a client-side "fix".

Real PostgreSQL because the sort key is a ``regexp_replace`` pair evaluated
by the database, and an ORM-level assertion could not observe it.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, literal, select

from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.schedule.ordering import natural_sort_key
from app.modules.schedule.repository import ActivityRepository
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


# ── Seeding ────────────────────────────────────────────────────────────────


async def _seed_schedule(session) -> Schedule:
    """Insert an owner, a project and one empty schedule."""
    owner = User(email=f"sched-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(name="Ordering project", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    schedule = Schedule(project_id=project.id, name="Programme", status="active")
    session.add(schedule)
    await session.flush()
    return schedule


async def _add_activities(
    session,
    schedule: Schedule,
    codes: list[str],
    *,
    sort_orders: list[int] | None = None,
) -> None:
    """Add one activity per code.

    ``sort_orders`` defaults to all zeros - the value every row gets when the
    writer omits the column, which is the state the demo estate is in.
    """
    orders = sort_orders if sort_orders is not None else [0] * len(codes)
    for code, order in zip(codes, orders, strict=True):
        session.add(
            Activity(
                schedule_id=schedule.id,
                name=f"Activity {code}",
                wbs_code=code,
                start_date="2026-04-01",
                end_date="2026-04-30",
                sort_order=order,
            )
        )
    await session.flush()


async def _listed_codes(session, schedule: Schedule, *, offset: int = 0, limit: int = 1000) -> list[str]:
    """The wbs_codes the repository hands back, in the order it hands them back."""
    rows, _total = await ActivityRepository(session).list_for_schedule(schedule.id, offset=offset, limit=limit)
    return [a.wbs_code for a in rows]


# ── The reported defect ────────────────────────────────────────────────────


async def test_unpadded_codes_list_in_numeric_order(pg_session) -> None:
    """1 ... 12 lists as 1 ... 12, not as 1, 10, 11, 12, 2, 3 ...

    These are the literal codes ``demo_projects`` writes for a template with
    no explicit schedule activities (``wbs_code=sec.ordinal or str(i + 1)``)
    and no ``sort_order``.
    """
    schedule = await _seed_schedule(pg_session)
    codes = [str(i) for i in range(1, 13)]
    await _add_activities(pg_session, schedule, codes)

    listed = await _listed_codes(pg_session, schedule)

    assert listed == codes
    # Name the specific wrong answer, so a regression is unambiguous.
    assert listed != sorted(codes), "codes came back in plain text order"


async def test_natural_order_holds_across_a_pagination_boundary(pg_session) -> None:
    """Walking the pages in order reproduces the full order, with nothing lost.

    The endpoint pages with offset/limit, so an order applied after the fetch
    would sort within each page only: page one would look plausible while the
    concatenation stayed wrong. Thirty-five activities over pages of ten is
    the shipped ``retail-market-*`` programme size.
    """
    schedule = await _seed_schedule(pg_session)
    codes = [str(i) for i in range(1, 36)]
    await _add_activities(pg_session, schedule, codes)

    page_size = 10
    walked: list[str] = []
    for page in range(4):
        walked.extend(await _listed_codes(pg_session, schedule, offset=page * page_size, limit=page_size))

    assert walked == codes
    assert len(walked) == len(set(walked)), "a row was served on two pages"


# ── The order the user set must still win ──────────────────────────────────


async def test_sort_order_outranks_the_code(pg_session) -> None:
    """An explicit sort_order beats the code.

    The natural key is a tie-breaker, not the primary term. If it were
    primary, an importer's numbering - or a PATCH that set ``sort_order`` -
    would appear to take and then snap back to code order on the next read.
    """
    schedule = await _seed_schedule(pg_session)
    codes = ["1", "2", "3"]
    # Deliberately the reverse of code order.
    await _add_activities(pg_session, schedule, codes, sort_orders=[30, 20, 10])

    assert await _listed_codes(pg_session, schedule) == ["3", "2", "1"]


async def test_one_explicit_sort_order_among_defaults_moves_only_that_row(pg_session) -> None:
    """The mixed state a real schedule reaches, not the all-or-nothing one.

    Nothing rewrites the whole schedule's ``sort_order``: ``create_activity``
    appends at ``max + 1`` and a ``PATCH`` sets a single row, so a schedule
    seeded at the column default ends up with one row carrying a value and
    the rest still on 0. The rows left at 0 must keep their natural code
    order among themselves, and the row that was given a higher value must
    sit after all of them rather than at its code position.
    """
    schedule = await _seed_schedule(pg_session)
    codes = ["1", "2", "3", "10", "11"]
    # "2" is the row someone moved; every other row is untouched.
    await _add_activities(pg_session, schedule, codes, sort_orders=[0, 7, 0, 0, 0])

    assert await _listed_codes(pg_session, schedule) == ["1", "3", "10", "11", "2"]


# ── The shapes real WBS codes come in ──────────────────────────────────────


@pytest.mark.parametrize(
    "codes",
    [
        # Zero-padded ordinals were already correct under text ordering and
        # must stay correct - the fix must not disturb what it did not break.
        ["01", "02", "03", "10", "11", "12"],
        # DIN 276 cost groups (residential-berlin, office-frankfurt).
        ["300", "320", "410", "500"],
        # MasterFormat two-digit divisions (tower-abudhabi, warehouse-dubai).
        ["03", "05", "21", "31", "32"],
        # Dotted multi-segment: "2.10" must follow "2.9", and a deeper level
        # must not outrank a shallower difference.
        ["2.1", "2.9", "2.10", "10.1"],
        ["1.9.1", "1.10.2"],
        # Alphanumeric (modular-housing "F1"/"S1", solar-bess-epc "34A"/"48F").
        ["F1", "F2", "F10", "S1", "S10"],
        ["01", "01E", "25", "34A", "48A", "48F"],
        # Four-digit chapter/section pairs (residential-shenzhen).
        ["0101", "0109", "0113", "0205", "0304"],
    ],
)
async def test_real_world_code_shapes_sort_as_written(pg_session, codes: list[str]) -> None:
    """Every code shape in the shipped demo estate lists in its written order.

    Each case is given already in the order a human reads it, so the
    assertion is that the database hands it back unchanged.
    """
    schedule = await _seed_schedule(pg_session)
    await _add_activities(pg_session, schedule, codes)

    assert await _listed_codes(pg_session, schedule) == codes


async def test_padded_and_unpadded_spellings_of_one_number_stay_together(pg_session) -> None:
    """ "1" and "01" are the same number, so neither may straddle "2".

    They tie on the sort key, so which of the two comes first is settled by
    the primary-key tie-breaker and is not asserted here - only that the tie
    does not let "2" fall between them.
    """
    schedule = await _seed_schedule(pg_session)
    await _add_activities(pg_session, schedule, ["1", "01", "2"])

    listed = await _listed_codes(pg_session, schedule)

    assert set(listed[:2]) == {"1", "01"}
    assert listed[2] == "2"


# ── The relationship, which is a fourth read of the same list ──────────────


async def test_the_activities_relationship_uses_the_same_order(pg_session) -> None:
    """``Schedule.activities`` agrees with the paginated list.

    The relationship is ``lazy="selectin"``, so every load of a Schedule
    anywhere in the app materialises this collection. It used to order by
    ``sort_order`` alone, which on a schedule of all-zero rows is no order at
    all: the same schedule could read one way through the repository and
    another way through the relationship.

    The rows are inserted in reverse on purpose. Ordering by a column that
    holds one value for every row leaves PostgreSQL free to return them in
    whatever order it likes, and for a freshly written table that is normally
    insertion order - so seeding in the expected order would let this test
    pass against the very bug it exists to catch.
    """
    schedule = await _seed_schedule(pg_session)
    codes = [str(i) for i in range(1, 13)]
    await _add_activities(pg_session, schedule, list(reversed(codes)))

    # Drop the identity map so the collection is loaded from the database
    # rather than handed back from the instance we just populated.
    pg_session.expunge_all()
    reloaded = await pg_session.get(Schedule, schedule.id)

    assert [a.wbs_code for a in reloaded.activities] == codes


async def test_deleting_a_schedule_still_cascades_to_its_activities(pg_session) -> None:
    """The delete-orphan cascade survives the new ``order_by``.

    ``Schedule.activities`` carries ``cascade="all, delete-orphan"``, and the
    ordering fix replaced its ``order_by`` with a ``regexp_replace``
    expression. Deleting the parent loads that collection through an internal
    path, so a change to how the collection is ordered is worth exercising
    against the delete as well as against the read.
    """
    schedule = await _seed_schedule(pg_session)
    await _add_activities(pg_session, schedule, ["3", "1", "10", "2"])

    await pg_session.delete(schedule)
    await pg_session.flush()

    remaining = await pg_session.execute(
        select(func.count()).select_from(Activity).where(Activity.schedule_id == schedule.id)
    )
    assert remaining.scalar_one() == 0


# ── The sort key itself ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "expected_key"),
    [
        ("2", "000000000002"),
        ("02", "000000000002"),
        ("10", "000000000010"),
        ("2.10A", "000000000002.000000000010A"),
        ("F1", "F000000000001"),
        ("", ""),
    ],
)
async def test_natural_sort_key_left_pads_every_digit_run(pg_session, code: str, expected_key: str) -> None:
    """The key is the code with each run of digits left-padded to a fixed width."""
    key = (await pg_session.execute(select(natural_sort_key(literal(code))))).scalar_one()

    assert key == expected_key
