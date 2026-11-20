# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: ``tmm01_tender_canonical_model`` upgrades a 19.9.0 database without losing a row.

The schema is put back into its 19.9.0 shape inside a rolled-back transaction:
the columns and tables this revision adds are dropped, and so are the tendering
columns and tables that arrived after 19.9.0, because the copy must read an old
install that never had them. All three old models carry data: a tendering
package with bids, an RFQ with priced lines and an award, and a native
bid-management package. After the upgrade every source row is still there,
every old package has exactly one canonical copy, the reconcile is clean, and a
second run changes nothing.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.modules.bid_management import legacy_mirror
from app.modules.bid_management.legacy_copy import reconcile

_REVISION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "tmm01_tender_canonical_model.py"

#: Added to tendering after 19.9.0; an old install has none of them.
_TENDERING_AFTER_1990 = {
    "oe_tendering_package": [
        "legal_entity_id",
        "trade",
        "cost_line_id",
        "issue_date",
        "questions_until",
        "bids_due",
        "award_planned",
        "buyer_id",
        "estimator_id",
        "site_manager_id",
        "approver_id",
    ],
    "oe_tendering_bid_invitation": ["declined_at", "decline_reason"],
}
_TABLES_AFTER_1990 = ("oe_tendering_bid_file", "oe_tendering_package_document")

_SOURCES = (
    "oe_tendering_package",
    "oe_tendering_bid",
    "oe_rfq_rfq",
    "oe_rfq_line",
    "oe_rfq_bid",
    "oe_rfq_bid_line",
    "oe_rfq_award",
)


def _revision() -> Any:
    spec = importlib.util.spec_from_file_location("tmm01_under_test", _REVISION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pg_conn(pg_async_url: str) -> Iterator[Connection]:
    """A synchronous connection whose transaction (DDL included) is always rolled back."""
    was_installed = legacy_mirror.is_installed()
    legacy_mirror.uninstall()  # the seed must not be mirrored before the old shape exists
    engine = create_engine(make_url(pg_async_url).set(drivername="postgresql+psycopg2"))
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()
        if was_installed:
            legacy_mirror.install()


def _seed(connection: Connection) -> dict[str, str]:
    from app.modules.bid_management.models import Bidder, BidPackage
    from app.modules.projects.models import Project
    from app.modules.rfq_bidding.models import RFQ, RFQAward, RFQBid, RFQBidLine, RFQLine
    from app.modules.tendering.models import TenderBid, TenderPackage
    from app.modules.users.models import User

    sfx = uuid.uuid4().hex[:8]
    with Session(bind=connection, join_transaction_mode="create_savepoint") as s:
        owner = User(email=f"upgrade-{sfx}@example.test", hashed_password="x", full_name="Buyer")
        s.add(owner)
        s.flush()
        project = Project(name="Upgrade from 19.9.0", owner_id=owner.id, currency="EUR")
        s.add(project)
        s.flush()

        tender = TenderPackage(project_id=project.id, name="Drywall", status="awarded", metadata_={})
        s.add(tender)
        s.flush()
        bids = [
            TenderBid(
                package_id=tender.id,
                company_name=name,
                total_amount=total,
                currency="EUR",
                status=status,
                line_items=[
                    {
                        "position_id": str(uuid.uuid4()),
                        "description": "Partition",
                        "unit": "m2",
                        "quantity": 10.0,
                        "unit_rate": total,
                        "total": total,
                    }
                ],
            )
            for name, total, status in (("Nord", "148200.00", "accepted"), ("Sued", "151999.99", "rejected"))
        ]
        s.add_all(bids)
        s.flush()
        tender.metadata_ = {"awarded_bid_id": str(bids[0].id)}

        rfq = RFQ(
            project_id=project.id,
            rfq_number=f"RFQ-{sfx}",
            title="Ready-mix",
            currency_code="USD",
            status="awarded",
            issued_to_contacts=[],
        )
        s.add(rfq)
        s.flush()
        line = RFQLine(rfq_id=rfq.id, line_no=1, description="Concrete", unit="CY", quantity=Decimal("1800"))
        s.add(line)
        s.flush()
        bid = RFQBid(
            rfq_id=rfq.id,
            bidder_contact_id=str(uuid.uuid4()),
            bid_amount="302400.00",
            currency_code="USD",
            metadata_={"company_name": "Lone Star"},
        )
        s.add(bid)
        s.flush()
        s.add(
            RFQBidLine(
                bid_id=bid.id,
                rfq_line_id=line.id,
                quantity=Decimal("1800"),
                unit_rate=Decimal("168"),
                amount=Decimal("302400.00"),
            )
        )
        s.add(
            RFQAward(
                rfq_id=rfq.id,
                bid_id=bid.id,
                awarded_at="2027-01-10T09:00:00+00:00",
                awarded_amount=Decimal("302400.00"),
                awarded_currency="USD",
            )
        )

        native = BidPackage(project_id=project.id, code=f"BP-{sfx}", title="Roofing", currency="EUR")
        s.add(native)
        s.flush()
        s.add(Bidder(package_id=native.id, company_name="Dach GmbH"))
        s.commit()
        return {"project": str(project.id), "tender": str(tender.id), "rfq": str(rfq.id), "native": str(native.id)}


def _back_to_19_9_0(connection: Connection) -> None:
    rev = _revision()
    insp = inspect(connection)
    for table in (rev._MAP, rev._ADJUSTMENT, *_TABLES_AFTER_1990):
        connection.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
    for table, columns in rev._NEW_COLUMNS.items():
        present = {c["name"] for c in insp.get_columns(table)}
        for name, _type in columns:
            if name in present:
                connection.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{name}" CASCADE'))
    connection.execute(text(f'ALTER TABLE "{rev._SUB_LINE}" ALTER COLUMN line_item_id SET NOT NULL'))
    for table, columns in _TENDERING_AFTER_1990.items():
        present = {c["name"] for c in insp.get_columns(table)}
        for name in columns:
            if name in present:
                connection.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{name}" CASCADE'))


def _upgrade(connection: Connection) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        _revision().upgrade()


def _count(connection: Connection, table: str, where: str = "", **params: Any) -> int:
    sql = f'SELECT count(*) FROM "{table}"' + (f" WHERE {where}" if where else "")  # noqa: S608
    return connection.execute(text(sql), params).scalar_one()


def _snapshot(connection: Connection, project: str) -> dict[str, int]:
    out = {t: _count(connection, t) for t in _SOURCES}
    out["packages"] = _count(connection, "oe_bid_management_package", "project_id = :p", p=project)
    out["bidders"] = _count(connection, "oe_bid_management_bidder")
    out["submissions"] = _count(connection, "oe_bid_management_submission")
    out["awards"] = _count(connection, "oe_bid_management_award")
    out["map"] = _count(connection, "oe_tender_legacy_map")
    return out


def test_tmm01_upgrades_a_19_9_0_database_with_every_row_kept(pg_conn: Connection) -> None:
    ids = _seed(pg_conn)
    before = {t: _count(pg_conn, t) for t in _SOURCES}
    native_before = _count(pg_conn, "oe_bid_management_package", "project_id = :p", p=ids["project"])
    _back_to_19_9_0(pg_conn)
    assert "legacy_source" not in {c["name"] for c in inspect(pg_conn).get_columns("oe_bid_management_package")}
    assert not inspect(pg_conn).has_table("oe_tender_legacy_map")

    _upgrade(pg_conn)

    after = _snapshot(pg_conn, ids["project"])
    assert {t: after[t] for t in _SOURCES} == before  # nothing in the old modules was touched
    assert after["packages"] == native_before + 2  # one copy per old package, the native one kept
    for table, source in (("oe_tendering_package", ids["tender"]), ("oe_rfq_rfq", ids["rfq"])):
        assert _count(pg_conn, "oe_tender_legacy_map", "source_table = :t AND source_id = :s", t=table, s=source) == 1
    assert _count(pg_conn, "oe_bid_management_package", "id = :i AND legacy_source IS NULL", i=ids["native"]) == 1
    copies = pg_conn.execute(
        text(
            "SELECT legacy_source, package_type, status FROM oe_bid_management_package "
            "WHERE project_id = :p AND legacy_source IS NOT NULL ORDER BY legacy_source"
        ),
        {"p": ids["project"]},
    ).all()
    assert [tuple(r) for r in copies] == [("rfq_bidding", "supply", "awarded"), ("tendering", "subcontract", "awarded")]

    report = reconcile(pg_conn, reflect=True)
    mine = [p for p in report.packages if p.source_id in (ids["tender"], ids["rfq"])]
    assert len(mine) == 2 and all(p.ok for p in mine), [p.line() for p in mine]
    totals = {p.source_table: (p.bids_target, str(p.total_target)) for p in mine}
    assert totals == {"oe_tendering_package": (2, "300199.99"), "oe_rfq_rfq": (1, "302400.00")}

    _upgrade(pg_conn)
    assert _snapshot(pg_conn, ids["project"]) == after
