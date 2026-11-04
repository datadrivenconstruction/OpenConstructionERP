"""PG: bulk and list paths read their rows with a constant number of statements.

Covers change-order standalone preflight, change-order code generation,
punch-list bulk close and the bid/no-bid ledger. Each used to issue one SELECT
per row (or per retry); the counts below must not grow with the row count.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event

from app.modules.bid_no_bid.models import BidNoBidScorecard
from app.modules.bid_no_bid.service import BidNoBidService
from app.modules.changeorders.models import ChangeOrder
from app.modules.changeorders.service import ChangeOrderService
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.punchlist.service import PunchListService
from app.modules.tendering.models import TenderPackage
from app.modules.users.models import User
from app.modules.variations.models import VariationOrder


@contextmanager
def _statements(session) -> Iterator[list[str]]:
    seen: list[str] = []
    engine = session.bind.engine.sync_engine

    def _record(_conn, _cursor, statement, _params, _context, _many) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _selects_from(statements: list[str], table: str) -> list[str]:
    pat = re.compile(rf"\bFROM\s+{table}\b", re.IGNORECASE)
    return [s for s in statements if s.lstrip().upper().startswith("SELECT") and pat.search(s)]


async def _project(session) -> Project:
    owner = User(email=f"n1-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="N plus one")
    session.add(owner)
    await session.flush()
    project = Project(name="N plus one", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


async def test_standalone_preflight_loads_linked_orders_in_one_query(pg_session) -> None:
    project = await _project(pg_session)
    orders = [ChangeOrder(project_id=project.id, code=f"CO-{i:03d}", title=f"CO {i}") for i in range(1, 6)]
    pg_session.add_all(orders)
    await pg_session.flush()
    for i, order in enumerate(orders):
        pg_session.add(VariationOrder(project_id=project.id, code=f"VO-{i:03d}", reference_change_order_id=order.id))
    pg_session.add(VariationOrder(project_id=project.id, code="VO-999", reference_change_order_id=uuid.uuid4()))
    await pg_session.flush()
    pg_session.expunge_all()  # get() would otherwise answer from the identity map

    with _statements(pg_session) as seen:
        rows = await ChangeOrderService(pg_session).standalone_preflight(project.id)

    assert len(rows) == 6
    assert len(_selects_from(seen, "oe_changeorders_order")) == 1
    dangling = next(r for r in rows if r["code"] == "VO-999")
    assert dangling["linked_change_order_status"] is None
    assert dangling["can_link"] is True


async def test_create_order_counts_the_project_once_even_after_a_collision(pg_session, monkeypatch) -> None:
    project = await _project(pg_session)
    pg_session.add(ChangeOrder(project_id=project.id, code="CO-001", title="first"))
    await pg_session.flush()
    from app.modules.changeorders.schemas import ChangeOrderCreate

    service = ChangeOrderService(pg_session)
    # Force two collisions: the code the first two attempts want already exists.
    for code in ("CO-002", "CO-003"):
        pg_session.add(ChangeOrder(project_id=project.id, code=code, title=code))
    await pg_session.flush()
    # Count is now 3 -> first attempt wants CO-004; pre-seed it plus CO-005 to collide twice.
    for code in ("CO-004", "CO-005"):
        pg_session.add(ChangeOrder(project_id=project.id, code=code, title=code))
    await pg_session.flush()
    real_count = service.repo.count_for_project
    calls = 0

    async def stale_count(pid):
        nonlocal calls
        calls += 1
        return min(await real_count(pid), 3)  # a count taken before the rival rows landed

    monkeypatch.setattr(service.repo, "count_for_project", stale_count)
    order = await service.create_order(ChangeOrderCreate(project_id=project.id, title="retry"))

    assert order.code == "CO-006"
    assert calls == 1


async def test_bulk_close_loads_all_items_in_one_query_and_reports_missing(pg_session) -> None:
    project = await _project(pg_session)
    items = [PunchItem(project_id=project.id, title=f"item {i}", status="verified") for i in range(6)]
    pg_session.add_all(items)
    await pg_session.flush()
    ids = [i.id for i in items]
    ghost = uuid.uuid4()
    pg_session.expunge_all()

    with _statements(pg_session) as seen:
        result = await PunchListService(pg_session).bulk_close(project.id, [*ids, ghost], user_id=str(uuid.uuid4()))

    assert [e for e in result["errors"] if e["error"] == "not_found"] == [{"id": str(ghost), "error": "not_found"}]
    assert result["closed"] == 6
    assert len(_selects_from(seen, "oe_punchlist_item")) == 1


async def test_ledger_names_every_tender_in_one_query(pg_session) -> None:
    project = await _project(pg_session)
    for i in range(5):
        tender = TenderPackage(project_id=project.id, name=f"Tender {i}")
        pg_session.add(tender)
        await pg_session.flush()
        pg_session.add(BidNoBidScorecard(project_id=project.id, tender_id=tender.id))
    await pg_session.flush()

    with _statements(pg_session) as seen:
        ledger = await BidNoBidService(pg_session).ledger(project.id)

    assert sorted(r["tender_name"] for r in ledger["rows"]) == [f"Tender {i}" for i in range(5)]
    assert len(_selects_from(seen, "oe_tendering_package")) == 1
