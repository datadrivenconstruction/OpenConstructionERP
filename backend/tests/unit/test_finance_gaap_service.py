# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service-layer unit tests for the GAAP general ledger (task #77).

These exercise :class:`FinanceService`'s GAAP methods with in-memory stub
repositories (no database, no event loop fixtures beyond ``pytest.mark.asyncio``)
so the ORM-to-pure-function wiring is verified: account resolution, the balanced
/ single-currency journal invariants raised as HTTP 400, and the statement
derivations computed over loaded ledger rows.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.finance import gaap
from app.modules.finance.schemas import JournalEntryCreate, JournalLineInput
from app.modules.finance.service import FinanceService

PROJECT_ID = uuid.uuid4()


# ── Stub repositories ─────────────────────────────────────────────────────────


class _StubSession:
    """No-op AsyncSession: ``begin_nested`` is the only thing post_journal needs."""

    def begin_nested(self) -> _NestedCtx:
        return _NestedCtx()

    def add(self, _obj: Any) -> None:  # pragma: no cover - trivial
        pass

    async def flush(self) -> None:  # pragma: no cover - trivial
        pass


class _NestedCtx:
    async def __aenter__(self) -> _NestedCtx:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class _StubAccountRepo:
    """Serves the default chart as if it were persisted, scoped to PROJECT_ID."""

    def __init__(self) -> None:
        self._chart = gaap.default_chart_of_accounts()

    async def get_by_code(self, code: str, *, project_id: uuid.UUID | None = None) -> Any:
        acc = self._chart.get(code)
        if acc is None:
            return None
        return SimpleNamespace(
            account_code=acc.code,
            name=acc.name,
            account_type=acc.account_type.value,
            statement_section=acc.statement_section,
            is_cash=acc.is_cash,
            is_active=True,
            project_id=project_id,
        )

    async def list(self, *, project_id: uuid.UUID | None = None, **_kw: Any) -> tuple[list[Any], int]:
        rows = [
            SimpleNamespace(
                account_code=a.code,
                name=a.name,
                account_type=a.account_type.value,
                statement_section=a.statement_section,
                is_cash=a.is_cash,
                project_id=None,
            )
            for a in self._chart.values()
        ]
        return rows, len(rows)


class _StubLedgerRepo:
    """Captures posted rows and replays them for the statement queries."""

    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def list_entries(self, **_kw: Any) -> list[Any]:
        return list(self.rows)


def _make_service() -> FinanceService:
    svc = FinanceService.__new__(FinanceService)
    svc.session = _StubSession()
    svc.accounts = _StubAccountRepo()
    svc.ledger = _StubLedgerRepo()
    return svc


def _line(code: str, debit: str = "0", credit: str = "0") -> JournalLineInput:
    return JournalLineInput(account_code=code, debit=debit, credit=credit)


def _capture_posted_rows(svc: FinanceService, rows: list[Any]) -> None:
    """Mirror posted ORM rows into the stub ledger so statements can read them."""
    svc.ledger.rows.extend(
        SimpleNamespace(
            account_code=r.account_code,
            debit_amount=r.debit_amount,
            credit_amount=r.credit_amount,
            currency_code=r.currency_code,
            posted_at=r.posted_at,
            transaction_ref=r.transaction_ref,
        )
        for r in rows
    )


# ── Journal posting: balanced vs unbalanced ──────────────────────────────────


@pytest.mark.asyncio
async def test_post_balanced_journal_succeeds() -> None:
    svc = _make_service()
    data = JournalEntryCreate(
        project_id=PROJECT_ID,
        transaction_ref="JE-1",
        currency_code="USD",
        posted_at="2026-01-01",
        lines=[_line("1000", debit="50000"), _line("3000", credit="50000")],
    )
    rows, total_dr, total_cr = await svc.post_journal_entry(data)
    assert len(rows) == 2
    assert total_dr == Decimal("50000.00")
    assert total_cr == Decimal("50000.00")
    assert rows[0].account_code == "1000"
    assert rows[0].debit_amount == Decimal("50000")


@pytest.mark.asyncio
async def test_post_unbalanced_journal_rejected() -> None:
    svc = _make_service()
    data = JournalEntryCreate(
        project_id=PROJECT_ID,
        transaction_ref="JE-2",
        currency_code="USD",
        lines=[_line("1000", debit="50000"), _line("3000", credit="40000")],
    )
    with pytest.raises(HTTPException) as exc:
        await svc.post_journal_entry(data)
    assert exc.value.status_code == 400
    assert "Unbalanced" in exc.value.detail


@pytest.mark.asyncio
async def test_post_journal_line_with_both_sides_rejected() -> None:
    svc = _make_service()
    data = JournalEntryCreate(
        project_id=PROJECT_ID,
        transaction_ref="JE-3",
        currency_code="USD",
        lines=[_line("1000", debit="100", credit="100"), _line("3000", credit="100")],
    )
    with pytest.raises(HTTPException) as exc:
        await svc.post_journal_entry(data)
    assert exc.value.status_code == 400
    assert "exactly one side" in exc.value.detail


@pytest.mark.asyncio
async def test_post_journal_unknown_account_rejected() -> None:
    svc = _make_service()
    data = JournalEntryCreate(
        project_id=PROJECT_ID,
        transaction_ref="JE-4",
        currency_code="USD",
        lines=[_line("9999", debit="100"), _line("3000", credit="100")],
    )
    with pytest.raises(HTTPException) as exc:
        await svc.post_journal_entry(data)
    assert exc.value.status_code == 400
    assert "not in the" in exc.value.detail


# ── End-to-end: post then derive statements ──────────────────────────────────


async def _seed_via_service(svc: FinanceService) -> None:
    """Post the same balanced transactions the pure test uses, through the service."""
    entries = [
        ("JE-A", [_line("1000", debit="100000"), _line("3000", credit="100000")]),
        ("JE-B", [_line("1100", debit="60000"), _line("4000", credit="60000")]),
        ("JE-C", [_line("5030", debit="25000"), _line("2000", credit="25000")]),
        ("JE-D", [_line("5110", debit="8000"), _line("1000", credit="8000")]),
        ("JE-E", [_line("1000", debit="40000"), _line("1100", credit="40000")]),
    ]
    for ref, lines in entries:
        data = JournalEntryCreate(
            project_id=PROJECT_ID,
            transaction_ref=ref,
            currency_code="USD",
            posted_at="2026-01-15",
            lines=lines,
        )
        rows, _, _ = await svc.post_journal_entry(data)
        _capture_posted_rows(svc, rows)


@pytest.mark.asyncio
async def test_trial_balance_ties_out_through_service() -> None:
    svc = _make_service()
    await _seed_via_service(svc)
    tb = await svc.trial_balance(project_id=PROJECT_ID, currency_code="USD")
    assert tb.total_debits == Decimal("233000.00")
    assert tb.total_credits == Decimal("233000.00")
    assert tb.is_balanced is True


@pytest.mark.asyncio
async def test_income_statement_through_service() -> None:
    svc = _make_service()
    await _seed_via_service(svc)
    inc = await svc.income_statement(project_id=PROJECT_ID, currency_code="USD")
    assert inc.total_revenue == Decimal("60000.00")
    assert inc.total_expenses == Decimal("33000.00")
    assert inc.net_income == Decimal("27000.00")


@pytest.mark.asyncio
async def test_balance_sheet_ties_out_through_service() -> None:
    svc = _make_service()
    await _seed_via_service(svc)
    bs = await svc.balance_sheet(project_id=PROJECT_ID, currency_code="USD")
    assert bs.total_assets == Decimal("152000.00")
    assert bs.total_liabilities == Decimal("25000.00")
    assert bs.total_equity == Decimal("127000.00")
    assert bs.is_balanced is True


@pytest.mark.asyncio
async def test_cash_flow_through_service() -> None:
    svc = _make_service()
    await _seed_via_service(svc)
    cf = await svc.cash_flow(project_id=PROJECT_ID, currency_code="USD")
    # Cash moved: +100,000 (equity, financing), -8,000 (expense, operating),
    # +40,000 (AR collection, operating). Net = 132,000.
    assert cf.financing == Decimal("100000.00")
    assert cf.operating == Decimal("32000.00")
    assert cf.net_change == Decimal("132000.00")
    assert cf.ties_out is True
