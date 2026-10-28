# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: v3304 classifies stock rows that already existed before it ran.

A fresh install never runs this migration. ``env.py`` detects a blank database
on entry and short-circuits to ``create_all`` plus ``stamp heads``, so "empty
database, upgrade head" executes no revision at all and still reports success.
Every signal such a run produces is therefore silent about whether the
migration works, and the only way to find out is to put rows in front of it
that were written under the old schema.

That is what this does. It builds the four tables v3304 touches in their
pre-migration shape inside a schema of its own - ``unit_cost_avg`` and
``unit_cost`` NOT NULL, no currency column anywhere - seeds one balance of each
kind, runs the revision's real ``upgrade()`` against them, and reads back what
it decided.

The four fixtures are the four outcomes, and each one is wrong in a different
way if the classifier slips:

* single      two receipts, both against EUR orders. The stored average was
              right all along and must survive untouched.
* mixed       one EUR receipt and one USD receipt. The stored number is the
              blend of the two, so it must be withdrawn.
* unresolved  a receipt whose ``reference_id`` is NULL. Nothing can say what
              currency it was bought in, so the average cannot be vouched for.
* untouched   a balance with no inbound movements at all. An empty set is not
              agreement, and this must not come out "single".

The single case also carries the join detail that would otherwise fail
silently: its movements store ``batch_lot`` as NULL while the balance stores
``''``, which is exactly what the receipt path writes. If the two stopped
matching, every balance would fall into the unresolved bucket and the migration
would still finish and still print a tidy summary.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

_MIGRATION = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3304_stock_balance_currency.py"

_SCHEMA = "v3304_aged"

# The four tables exactly as they stood before this revision: both money
# columns NOT NULL, and no currency anywhere.
_OLD_SCHEMA_DDL = f"""
CREATE SCHEMA {_SCHEMA};

CREATE TABLE {_SCHEMA}.oe_supplier_catalogs_po (
    id uuid PRIMARY KEY,
    currency varchar(10) NOT NULL DEFAULT 'EUR'
);

CREATE TABLE {_SCHEMA}.oe_supplier_catalogs_gr (
    id uuid PRIMARY KEY,
    po_id uuid NOT NULL
);

CREATE TABLE {_SCHEMA}.oe_supplier_catalogs_stock_balance (
    id uuid PRIMARY KEY,
    warehouse_id uuid NOT NULL,
    catalog_item_id uuid NOT NULL,
    batch_lot varchar(100) NOT NULL DEFAULT '',
    quantity_on_hand numeric(18, 4) NOT NULL DEFAULT 0,
    quantity_reserved numeric(18, 4) NOT NULL DEFAULT 0,
    unit_cost_avg numeric(18, 4) NOT NULL DEFAULT 0,
    last_movement_at varchar(40)
);

CREATE TABLE {_SCHEMA}.oe_supplier_catalogs_stock_movement (
    id uuid PRIMARY KEY,
    warehouse_id uuid NOT NULL,
    catalog_item_id uuid NOT NULL,
    movement_type varchar(20) NOT NULL,
    quantity numeric(18, 4) NOT NULL DEFAULT 0,
    unit_cost numeric(18, 4) NOT NULL DEFAULT 0,
    reference_type varchar(32),
    reference_id varchar(36),
    batch_lot varchar(100),
    project_id uuid,
    performed_by varchar(36),
    performed_at varchar(40)
);
"""


def _load_migration():
    """Import the revision by path; ``alembic/versions`` is not a package."""
    spec = importlib.util.spec_from_file_location("mig_v3304_aged", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_engine(pg_async_url):
    """A synchronous engine on the test cluster, as ``env.py`` builds in production."""
    url = make_url(pg_async_url).set(drivername="postgresql+psycopg2")
    engine = create_engine(url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def aged(sync_engine):
    """An old-shape schema with one balance of each kind, dropped afterwards.

    Yields the mapping of case name to balance id, so the assertions name the
    outcome they expect rather than a bare UUID.
    """
    wh = uuid.uuid4()
    ids: dict[str, uuid.UUID] = {}
    with sync_engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(_OLD_SCHEMA_DDL))

        po_eur, po_eur2, po_usd = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        for po_id, ccy in ((po_eur, "EUR"), (po_eur2, "EUR"), (po_usd, "USD")):
            conn.execute(
                text(f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_po (id, currency) VALUES (:i, :c)"),
                {"i": po_id, "c": ccy},
            )

        def _balance(case: str, avg: str) -> uuid.UUID:
            item = uuid.uuid4()
            bal = uuid.uuid4()
            conn.execute(
                text(
                    f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_stock_balance "
                    "(id, warehouse_id, catalog_item_id, batch_lot, quantity_on_hand, unit_cost_avg) "
                    "VALUES (:b, :w, :i, '', 100, :a)"
                ),
                {"b": bal, "w": wh, "i": item, "a": avg},
            )
            ids[case] = bal
            ids[f"{case}_item"] = item
            return item

        def _receipt(item: uuid.UUID, po_id: uuid.UUID | None, price: str) -> None:
            """One inbound movement. ``po_id`` None means an untraceable one."""
            ref_id = None
            if po_id is not None:
                gr = uuid.uuid4()
                conn.execute(
                    text(f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_gr (id, po_id) VALUES (:g, :p)"),
                    {"g": gr, "p": po_id},
                )
                ref_id = str(gr)
            conn.execute(
                text(
                    f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_stock_movement "
                    "(id, warehouse_id, catalog_item_id, movement_type, quantity, unit_cost, "
                    " reference_type, reference_id, batch_lot) "
                    "VALUES (:m, :w, :i, 'in', 100, :u, 'gr', :r, NULL)"
                ),
                {"m": uuid.uuid4(), "w": wh, "i": item, "u": price, "r": ref_id},
            )

        # Two EUR receipts: the stored average is real and must be kept. Note
        # the movements carry batch_lot NULL against the balance's '', which is
        # what the receipt path actually writes.
        item = _balance("single", "60.0000")
        _receipt(item, po_eur, "50")
        _receipt(item, po_eur2, "70")

        # EUR and USD: the stored 60 is the blend of 50 and 70 and is not money.
        item = _balance("mixed", "60.0000")
        _receipt(item, po_eur, "50")
        _receipt(item, po_usd, "70")

        # Two ways to be untraceable, and the summary tells them apart: one
        # movement never carried a reference, the other names a goods receipt
        # that has since been deleted along with its purchase order.
        item = _balance("unresolved", "50.0000")
        _receipt(item, None, "50")
        conn.execute(
            text(
                f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_stock_movement "
                "(id, warehouse_id, catalog_item_id, movement_type, quantity, unit_cost, "
                " reference_type, reference_id, batch_lot) "
                "VALUES (:m, :w, :i, 'in', 100, 50, 'gr', :r, NULL)"
            ),
            {"m": uuid.uuid4(), "w": wh, "i": item, "r": str(uuid.uuid4())},
        )

        # No inbound movements at all.
        _balance("untouched", "99.0000")

        def _outbound(item: uuid.UUID, mv_type: str, unit_cost: str) -> uuid.UUID:
            """One issue / reservation / adjust, priced from the balance average."""
            mv = uuid.uuid4()
            conn.execute(
                text(
                    f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_stock_movement "
                    "(id, warehouse_id, catalog_item_id, movement_type, quantity, unit_cost, "
                    " reference_type, reference_id, batch_lot) "
                    "VALUES (:m, :w, :i, :t, 10, :u, :rt, NULL, NULL)"
                ),
                {"m": mv, "w": wh, "i": item, "t": mv_type, "u": unit_cost, "rt": mv_type},
            )
            return mv

        # Outbound history on the single-currency balance. These took their
        # cost from an all-EUR average and are derivably EUR.
        ids["out_issue"] = _outbound(ids["single_item"], "out", "50.0000")
        ids["out_reservation"] = _outbound(ids["single_item"], "reservation", "60.0000")
        # A stocktake that ran before the balance had received anything, so it
        # copied the creation default. Zero is denominated in nothing and this
        # row must stay unlabelled even though its balance is single.
        ids["out_zero"] = _outbound(ids["single_item"], "adjust", "0.0000")
        # Outbound history on the mixed balance stays unlabelled: there is no
        # single currency to derive from.
        ids["out_mixed"] = _outbound(ids["mixed_item"], "out", "60.0000")

        conn.commit()

    try:
        yield ids
    finally:
        with sync_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
            conn.commit()


def _run_upgrade(engine) -> None:
    """Run the revision's real ``upgrade()`` against the aged schema."""
    module = _load_migration()
    with engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        ctx = MigrationContext.configure(connection=conn)
        with Operations.context(ctx):
            module.upgrade()
        conn.commit()


def _read(engine) -> dict[uuid.UUID, tuple]:
    with engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        rows = conn.execute(
            text(f"SELECT id, cost_state, currency, unit_cost_avg FROM {_SCHEMA}.oe_supplier_catalogs_stock_balance")
        ).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def test_a_single_currency_balance_keeps_its_average_and_gains_its_label(sync_engine, aged):
    _run_upgrade(sync_engine)
    state, currency, avg = _read(sync_engine)[aged["single"]]
    assert state == "single"
    assert currency == "EUR"
    # Untouched. It was the mean of two EUR prices and still is.
    assert avg is not None
    assert float(avg) == pytest.approx(60.0)


def test_a_mixed_currency_balance_has_its_blended_average_withdrawn(sync_engine, aged):
    _run_upgrade(sync_engine)
    state, currency, avg = _read(sync_engine)[aged["mixed"]]
    assert state == "mixed"
    # Naming either currency would make the blend look like a price in it.
    assert currency is None
    # This is the number the defect produced: the mean of 50 EUR and 70 USD.
    assert avg is None


def test_an_untraceable_receipt_leaves_the_balance_unknown(sync_engine, aged):
    _run_upgrade(sync_engine)
    state, currency, avg = _read(sync_engine)[aged["unresolved"]]
    assert state == "unknown"
    assert currency is None
    assert avg is None


def test_a_balance_with_no_receipts_is_unknown_rather_than_single(sync_engine, aged):
    """An empty set of evidence is not evidence of agreement."""
    _run_upgrade(sync_engine)
    state, currency, avg = _read(sync_engine)[aged["untouched"]]
    assert state == "unknown"
    assert currency is None
    assert avg is None


def test_inbound_movements_are_labelled_from_their_purchase_order(sync_engine, aged):
    """The currency of historical stock was recoverable by join all along."""
    _run_upgrade(sync_engine)
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        rows = conn.execute(
            text(
                f"SELECT currency, count(*) FROM {_SCHEMA}.oe_supplier_catalogs_stock_movement "
                "WHERE movement_type = 'in' GROUP BY currency ORDER BY currency NULLS LAST"
            )
        ).fetchall()
    counts = {r[0]: r[1] for r in rows}
    # Three EUR receipts (two on the single balance, one on the mixed), one
    # USD, and the two untraceable ones which stay NULL.
    assert counts.get("EUR") == 3
    assert counts.get("USD") == 1
    assert counts.get(None) == 2


def test_the_summary_separates_a_deleted_receipt_from_a_missing_reference(sync_engine, aged, capsys):
    """The unresolvable bucket holds two different stories and says so.

    A movement with no reference was never recorded against an order. A
    movement whose goods receipt is gone was resolvable until somebody deleted
    a purchase order: ``po_id`` is ON DELETE CASCADE and ``reference_id`` has
    no foreign key, so the receipt went and the movement stayed. An operator
    reading "unresolvable" deserves to know which of those they have.

    The count is asserted rather than eyeballed because a counter that has
    only ever reported zero is indistinguishable from one that cannot count.
    """
    _run_upgrade(sync_engine)
    summary = capsys.readouterr().out
    assert "movements naming a deleted goods receipt: 1" in summary
    # And the balance carrying it is still unknown, not quietly single.
    assert _read(sync_engine)[aged["unresolved"]][0] == "unknown"


def _seed_one_currency(sync_engine, receipts: int) -> None:
    """A fresh schema with one EUR balance and ``receipts`` EUR receipts."""
    wh, item = uuid.uuid4(), uuid.uuid4()
    with sync_engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(_OLD_SCHEMA_DDL))
        po = uuid.uuid4()
        conn.execute(
            text(f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_po (id, currency) VALUES (:i, 'EUR')"),
            {"i": po},
        )
        conn.execute(
            text(
                f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_stock_balance "
                "(id, warehouse_id, catalog_item_id, batch_lot, quantity_on_hand, unit_cost_avg) "
                "VALUES (:b, :w, :i, '', 100, 50)"
            ),
            {"b": uuid.uuid4(), "w": wh, "i": item},
        )
        for _ in range(receipts):
            gr = uuid.uuid4()
            conn.execute(
                text(f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_gr (id, po_id) VALUES (:g, :p)"),
                {"g": gr, "p": po},
            )
            conn.execute(
                text(
                    f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_stock_movement "
                    "(id, warehouse_id, catalog_item_id, movement_type, quantity, unit_cost, "
                    " reference_type, reference_id, batch_lot) "
                    "VALUES (:m, :w, :i, 'in', 10, 50, 'gr', :r, NULL)"
                ),
                {"m": uuid.uuid4(), "w": wh, "i": item, "r": str(gr)},
            )
        conn.commit()


def _count_update_statements(sync_engine) -> int:
    """Run the upgrade and count the UPDATE statements it issues."""
    seen: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE"):
            seen.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        _run_upgrade(sync_engine)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)
    return len(seen)


def test_the_rewrite_issues_one_statement_per_value_not_one_per_row(sync_engine):
    """The statement count must not grow with the number of rows rewritten.

    This is the shape ``check_migration_data_rewrites.py`` exists to catch, and
    every other test in this file would pass just as happily against a loop
    doing one UPDATE per row. A test of the result is blind to a change of
    mechanism, so this one pins the mechanism: same data, twenty times the
    rows, same number of statements.

    Two EUR receipts and forty EUR receipts both label one currency onto one
    balance, so both are one UPDATE for the movements and one for the balance.
    """
    try:
        _seed_one_currency(sync_engine, receipts=2)
        small = _count_update_statements(sync_engine)

        _seed_one_currency(sync_engine, receipts=40)
        large = _count_update_statements(sync_engine)
    finally:
        with sync_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
            conn.commit()

    assert small == large, f"statement count scaled with rows: {small} for 2 receipts, {large} for 40"
    # One for the movements, one for the balance. Per-row would be 3 and 41.
    assert large == 2


def _movement_currency(engine, mv_id: uuid.UUID) -> str | None:
    with engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        row = conn.execute(
            text(f"SELECT currency FROM {_SCHEMA}.oe_supplier_catalogs_stock_movement WHERE id = :i"),
            {"i": mv_id},
        ).fetchone()
    return row[0]


def test_outbound_history_of_a_single_currency_balance_is_labelled(sync_engine, aged):
    """Issues and reservations copied an all-EUR average, so they are EUR.

    Without this the upgrade splits every history in two: everything before it
    unlabelled and everything after it labelled, in a warehouse where nothing
    about the money ever changed. The two populations would look identical and
    mean different things.
    """
    _run_upgrade(sync_engine)
    assert _movement_currency(sync_engine, aged["out_issue"]) == "EUR"
    assert _movement_currency(sync_engine, aged["out_reservation"]) == "EUR"


def test_a_zero_cost_outbound_row_is_not_labelled_even_on_a_single_balance(sync_engine, aged, capsys):
    """The derivation assumes the balance had already received something.

    A stocktake can write an adjustment against a balance with no receipts at
    all, copying the creation default, which is denominated in nothing. That
    row is exactly the zero, and nothing available says whether a given zero is
    that default or a genuine zero-priced copy, so it stays unlabelled.
    """
    _run_upgrade(sync_engine)
    assert _movement_currency(sync_engine, aged["out_zero"]) is None
    assert "outbound movements left unlabelled on a zero unit cost: 1" in capsys.readouterr().out


def test_outbound_history_of_a_mixed_balance_stays_unlabelled(sync_engine, aged):
    """There is no single currency to derive from, so nothing is claimed."""
    _run_upgrade(sync_engine)
    assert _movement_currency(sync_engine, aged["out_mixed"]) is None


def test_outbound_rows_keep_their_unit_cost_whatever_the_balance_says(sync_engine, aged):
    """A movement is an audit row, not a valuation, and is never withdrawn.

    The balance's average is withdrawn when it is a blend, because a balance is
    a current valuation and a blend is not a price. The movement records what
    the system did at the time and may already have been posted onward into
    project cost, so it is left exactly as it was.
    """
    _run_upgrade(sync_engine)
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        rows = conn.execute(
            text(
                f"SELECT unit_cost FROM {_SCHEMA}.oe_supplier_catalogs_stock_movement "
                "WHERE id IN (:a, :b) ORDER BY unit_cost"
            ),
            {"a": aged["out_mixed"], "b": aged["out_issue"]},
        ).fetchall()
    assert [float(r[0]) for r in rows] == [50.0, 60.0]


def test_a_broken_join_aborts_instead_of_withdrawing_every_average(sync_engine):
    """The failure this guard exists for is silent, so it is provoked here.

    If the movement-to-balance join stops matching, nothing raises. Every
    balance comes back with no inbound movements, every average is withdrawn
    as unresolvable, and the migration prints a tidy summary and succeeds. The
    guard turns that into an abort inside the migration's own transaction.

    Provoked by giving the only balance a different ``catalog_item_id`` from
    the only inbound movement, which is what a mismatched key part looks like
    from the classifier's side.
    """
    wh = uuid.uuid4()
    with sync_engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(_OLD_SCHEMA_DDL))
        po = uuid.uuid4()
        gr = uuid.uuid4()
        conn.execute(
            text(f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_po (id, currency) VALUES (:i, 'EUR')"),
            {"i": po},
        )
        conn.execute(
            text(f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_gr (id, po_id) VALUES (:g, :p)"),
            {"g": gr, "p": po},
        )
        conn.execute(
            text(
                f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_stock_balance "
                "(id, warehouse_id, catalog_item_id, batch_lot, quantity_on_hand, unit_cost_avg) "
                "VALUES (:b, :w, :i, '', 100, 50)"
            ),
            {"b": uuid.uuid4(), "w": wh, "i": uuid.uuid4()},
        )
        conn.execute(
            text(
                f"INSERT INTO {_SCHEMA}.oe_supplier_catalogs_stock_movement "
                "(id, warehouse_id, catalog_item_id, movement_type, quantity, unit_cost, "
                " reference_type, reference_id, batch_lot) "
                "VALUES (:m, :w, :i, 'in', 100, 50, 'gr', :r, NULL)"
            ),
            {"m": uuid.uuid4(), "w": wh, "i": uuid.uuid4(), "r": str(gr)},
        )
        conn.commit()

    try:
        with pytest.raises(RuntimeError, match="join is broken"):
            _run_upgrade(sync_engine)
    finally:
        with sync_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
            conn.commit()


def test_the_widened_columns_actually_accept_null(sync_engine, aged):
    """NOT NULL to NULLABLE is the point; assert the constraint really moved."""
    _run_upgrade(sync_engine)
    with sync_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = :s AND column_name IN ('unit_cost_avg', 'unit_cost')"
            ),
            {"s": _SCHEMA},
        ).fetchall()
    assert {(r[0], r[1]): r[2] for r in rows} == {
        ("oe_supplier_catalogs_stock_balance", "unit_cost_avg"): "YES",
        ("oe_supplier_catalogs_stock_movement", "unit_cost"): "YES",
    }
