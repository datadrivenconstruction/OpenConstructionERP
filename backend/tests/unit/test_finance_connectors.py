"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Finance ERP / accounting connectors (TOP-30 #4).

Covers:

* the pure helpers (``to_decimal``, ``SyncResult.status``, the registry),
* the file connector's push (dry-run vs live) against an in-memory storage,
* inbound parsing with header aliases (CSV + JSON),
* the file connector's pull against real PostgreSQL - balancing, the
  multi-leg guard, idempotency and the dry-run side-effect-free contract.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.connector_models import AccountingConnectorConfig
from app.modules.finance.connectors.base import (
    ConnectorConfigError,
    PushPayload,
    SyncResult,
    to_decimal,
)
from app.modules.finance.connectors.file_connector import FileConnector, _parse_inbound
from app.modules.finance.connectors.registry import ConnectorRegistry
from app.modules.finance.models import LedgerEntry
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


class _FakeStorage:
    """Minimal in-memory storage backend for connector tests."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes) -> None:
        self.blobs[key] = content

    async def get(self, key: str) -> bytes:
        if key not in self.blobs:
            raise FileNotFoundError(key)
        return self.blobs[key]

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)


def _config(*, direction: str = "both", settings: dict | None = None, project_id: uuid.UUID | None = None):
    return AccountingConnectorConfig(
        id=uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        name="Test connector",
        connector_type="file_csv",
        direction=direction,
        settings_=settings or {},
    )


# ── Pure helpers ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234.50", Decimal("1234.50")),
        ("1,234.50", Decimal("1234.50")),
        ("1234,50", Decimal("1234.50")),
        ("1 234,50", Decimal("1234.50")),
        ("", Decimal("0")),
        (None, Decimal("0")),
        ("not-a-number", Decimal("0")),
        (Decimal("42"), Decimal("42")),
    ],
)
def test_to_decimal(raw: object, expected: Decimal) -> None:
    assert to_decimal(raw) == expected


def test_sync_result_status() -> None:
    assert SyncResult(direction="push").status == "success"
    assert SyncResult(direction="push", errors=["x"]).status == "failed"
    assert SyncResult(direction="push", errors=["x"], records_out=2).status == "partial"


def test_registry_register_get_list_and_unknown() -> None:
    reg = ConnectorRegistry()
    reg.register(FileConnector)
    assert reg.has("file_csv")
    assert reg.get("file_csv") is FileConnector
    types = reg.list_types()
    assert types and types[0]["connector_type"] == "file_csv"
    assert any(f["key"] == "format" for f in types[0]["fields"])
    with pytest.raises(ConnectorConfigError):
        reg.get("does_not_exist")


# ── Validation ─────────────────────────────────────────────────────────────


async def test_validate_flags_bad_format_and_missing_inbound() -> None:
    conn = FileConnector(
        _config(direction="both", settings={"format": "xml"}),
        storage=_FakeStorage(),
        session=None,
    )
    problems = await conn.validate_config()
    # bad format + pull-without-inbound both surface
    assert any("format" in p.lower() for p in problems)
    assert any("inbound" in p.lower() for p in problems)


async def test_validate_requires_project_scope() -> None:
    cfg = _config(direction="push", settings={"format": "csv"})
    cfg.project_id = None
    conn = FileConnector(cfg, storage=_FakeStorage(), session=None)
    problems = await conn.validate_config()
    assert any("project" in p.lower() for p in problems)


# ── Push ─────────────────────────────────────────────────────────────────────


def _sample_payload() -> PushPayload:
    return PushPayload(
        invoices=[
            {
                "invoice_number": "INV-001",
                "invoice_direction": "payable",
                "invoice_date": "2026-06-01",
                "due_date": "2026-07-01",
                "counterparty": "=cmd|calc",  # formula-injection probe
                "currency_code": "CAD",
                "amount_subtotal": "1000.00",
                "tax_amount": "130.00",
                "retention_amount": "0",
                "amount_total": "1130.00",
                "status": "paid",
                "notes": "ok",
            }
        ],
        payments=[
            {
                "invoice_number": "INV-001",
                "payment_date": "2026-06-15",
                "amount": "1130.00",
                "currency_code": "CAD",
                "exchange_rate_snapshot": "1",
                "reference": "wire",
                "is_refund": False,
            }
        ],
    )


async def test_push_dry_run_writes_nothing() -> None:
    storage = _FakeStorage()
    conn = FileConnector(_config(direction="push", settings={"format": "csv"}), storage=storage, session=None)
    res = await conn.push(_sample_payload(), dry_run=True)
    assert res.status == "success"
    assert res.records_out == 2
    assert res.file_keys == []
    assert storage.blobs == {}
    assert res.details["preview"] == {"invoices": 1, "payments": 1}


async def test_push_live_writes_csv_and_neutralises_formula() -> None:
    storage = _FakeStorage()
    conn = FileConnector(_config(direction="push", settings={"format": "csv"}), storage=storage, session=None)
    res = await conn.push(_sample_payload(), dry_run=False)
    assert res.status == "success"
    assert len(res.file_keys) == 2
    inv_key = next(k for k in res.file_keys if k.endswith("invoices.csv"))
    body = storage.blobs[inv_key].decode("utf-8")
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0][0] == "invoice_number"
    data_row = rows[1]
    assert data_row[0] == "INV-001"
    # the dangerous counterparty cell must be apostrophe-prefixed
    counterparty = data_row[4]
    assert counterparty.startswith("'=")


async def test_push_live_writes_json() -> None:
    storage = _FakeStorage()
    conn = FileConnector(_config(direction="push", settings={"format": "json"}), storage=storage, session=None)
    res = await conn.push(_sample_payload(), dry_run=False)
    inv_key = next(k for k in res.file_keys if k.endswith("invoices.json"))
    parsed = json.loads(storage.blobs[inv_key].decode("utf-8"))
    assert parsed[0]["invoice_number"] == "INV-001"
    assert parsed[0]["amount_total"] == "1130.00"


# ── Inbound parsing ───────────────────────────────────────────────────────────


def test_parse_inbound_csv_with_header_aliases() -> None:
    raw = b"Journal,Account,Debit,Credit,Currency,Date,Memo\nTXN-1,1000,100,0,CAD,2026-06-01,cash\n"
    rows = _parse_inbound(raw, "csv", ",")
    assert rows[0]["transaction_ref"] == "TXN-1"
    assert rows[0]["account_code"] == "1000"
    assert rows[0]["debit_amount"] == "100"
    assert rows[0]["currency_code"] == "CAD"
    assert rows[0]["posted_at"] == "2026-06-01"
    assert rows[0]["description"] == "cash"


def test_parse_inbound_json_list_and_wrapper() -> None:
    rows = _parse_inbound(b'[{"transaction_ref":"T1","account_code":"1000","debit":"5"}]', "json", ",")
    assert rows[0]["transaction_ref"] == "T1"
    wrapped = _parse_inbound(b'{"rows":[{"ref":"T2","gl_account":"2000","credit":"7"}]}', "json", ",")
    assert wrapped[0]["transaction_ref"] == "T2"
    assert wrapped[0]["account_code"] == "2000"


# ── Pull against real PostgreSQL ───────────────────────────────────────────────


def _gl_csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    """rows = [(transaction_ref, account_code, debit, credit), ...]"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["transaction_ref", "account_code", "debit_amount", "credit_amount", "currency_code", "posted_at"])
    for ref, acct, dr, cr in rows:
        w.writerow([ref, acct, dr, cr, "CAD", "2026-06-01"])
    return buf.getvalue().encode("utf-8")


async def test_pull_writes_balanced_pair(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    storage = _FakeStorage()
    storage.blobs["in/gl.csv"] = _gl_csv([("TXN-100", "1000", "500", "0"), ("TXN-100", "2000", "0", "500")])
    cfg = _config(direction="pull", settings={"format": "csv", "inbound_key": "in/gl.csv"}, project_id=project_id)
    conn = FileConnector(cfg, storage=storage, session=session)

    res = await conn.pull(dry_run=False)
    assert res.status == "success", res.errors
    assert res.records_out == 1
    rows = (await session.execute(select(LedgerEntry).where(LedgerEntry.project_id == project_id))).scalars().all()
    assert len(rows) == 2  # one debit + one credit
    by_account = {r.account_code: r for r in rows}
    assert by_account["1000"].debit_amount == Decimal("500")
    assert by_account["2000"].credit_amount == Decimal("500")
    assert all(r.source_type == "erp_connector" for r in rows)


async def test_pull_dry_run_writes_no_ledger(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    storage = _FakeStorage()
    storage.blobs["in/gl.csv"] = _gl_csv([("TXN-200", "1000", "300", "0"), ("TXN-200", "2000", "0", "300")])
    cfg = _config(direction="pull", settings={"format": "csv", "inbound_key": "in/gl.csv"}, project_id=project_id)
    conn = FileConnector(cfg, storage=storage, session=session)

    res = await conn.pull(dry_run=True)
    assert res.records_in == 2
    assert res.records_out == 1  # would-write count
    rows = (await session.execute(select(LedgerEntry).where(LedgerEntry.project_id == project_id))).scalars().all()
    assert rows == []


async def test_pull_rejects_unbalanced(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    storage = _FakeStorage()
    storage.blobs["in/gl.csv"] = _gl_csv([("TXN-300", "1000", "500", "0"), ("TXN-300", "2000", "0", "499")])
    cfg = _config(direction="pull", settings={"format": "csv", "inbound_key": "in/gl.csv"}, project_id=project_id)
    conn = FileConnector(cfg, storage=storage, session=session)

    res = await conn.pull(dry_run=False)
    assert res.records_out == 0
    assert any("unbalanced" in e.lower() for e in res.errors)
    rows = (await session.execute(select(LedgerEntry).where(LedgerEntry.project_id == project_id))).scalars().all()
    assert rows == []


async def test_pull_skips_multi_leg(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    storage = _FakeStorage()
    # balanced overall (600 == 600) but two debit legs -> not a simple pair
    storage.blobs["in/gl.csv"] = _gl_csv(
        [
            ("TXN-400", "1000", "400", "0"),
            ("TXN-400", "1010", "200", "0"),
            ("TXN-400", "2000", "0", "600"),
        ]
    )
    cfg = _config(direction="pull", settings={"format": "csv", "inbound_key": "in/gl.csv"}, project_id=project_id)
    conn = FileConnector(cfg, storage=storage, session=session)

    res = await conn.pull(dry_run=False)
    assert res.records_out == 0
    assert any("multi-leg" in w.lower() for w in res.warnings)


async def test_pull_is_idempotent(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    storage = _FakeStorage()
    storage.blobs["in/gl.csv"] = _gl_csv([("TXN-500", "1000", "750", "0"), ("TXN-500", "2000", "0", "750")])
    cfg = _config(direction="pull", settings={"format": "csv", "inbound_key": "in/gl.csv"}, project_id=project_id)
    conn = FileConnector(cfg, storage=storage, session=session)

    first = await conn.pull(dry_run=False)
    assert first.records_out == 1
    second = await conn.pull(dry_run=False)
    assert second.records_out == 0
    assert second.details["skipped_already_imported"] == 1
    rows = (await session.execute(select(LedgerEntry).where(LedgerEntry.project_id == project_id))).scalars().all()
    assert len(rows) == 2  # not duplicated


async def test_pull_missing_inbound_file(session: AsyncSession) -> None:
    cfg = _config(
        direction="pull",
        settings={"format": "csv", "inbound_key": "in/missing.csv"},
        project_id=uuid.uuid4(),
    )
    conn = FileConnector(cfg, storage=_FakeStorage(), session=session)
    res = await conn.pull(dry_run=False)
    assert res.status == "failed"
    assert any("not found" in e.lower() for e in res.errors)
