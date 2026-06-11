# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure-logic unit tests for the GAAP general ledger (task #77).

These tests touch no database and no event loop. They pin the exact Decimal
arithmetic and sign conventions of the GAAP layer:

* a balanced journal posts; an unbalanced one is rejected;
* currency blending is rejected;
* the trial balance ties out (total debits == total credits);
* the income statement = revenue - expenses on seeded entries;
* the balance sheet ties out (assets == liabilities + equity);
* a reversal produces the inverse, netting the ledger to zero.

Money is asserted as exact ``Decimal`` (never float) - a silent drift here would
mis-state every financial statement.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.finance import gaap
from app.modules.finance.gaap import (
    AccountType,
    CashMovement,
    LedgerLine,
    NormalBalance,
    balance_sheet,
    cash_flow_direct,
    default_chart_of_accounts,
    income_statement,
    normal_balance_for,
    signed_balance,
    trial_balance,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _dr(code: str, amount: str, ccy: str = "USD", posted_at: str = "2026-01-15") -> LedgerLine:
    return LedgerLine(account_code=code, debit=Decimal(amount), currency_code=ccy, posted_at=posted_at)


def _cr(code: str, amount: str, ccy: str = "USD", posted_at: str = "2026-01-15") -> LedgerLine:
    return LedgerLine(account_code=code, credit=Decimal(amount), currency_code=ccy, posted_at=posted_at)


def _is_balanced_journal(lines: list[LedgerLine]) -> bool:
    """A journal posts iff sum(debit) == sum(credit) and value > 0.

    This mirrors the invariant ``FinanceService.post_journal_entry`` enforces
    before writing any row, expressed against the same pure ``LedgerLine``.
    """
    total_dr = sum((ln.debit for ln in lines), Decimal("0"))
    total_cr = sum((ln.credit for ln in lines), Decimal("0"))
    return total_dr == total_cr and total_dr > 0


CHART = default_chart_of_accounts()


# ── Normal-balance / sign conventions ────────────────────────────────────────


def test_normal_balance_by_type() -> None:
    assert normal_balance_for(AccountType.ASSET) is NormalBalance.DEBIT
    assert normal_balance_for(AccountType.EXPENSE) is NormalBalance.DEBIT
    assert normal_balance_for(AccountType.LIABILITY) is NormalBalance.CREDIT
    assert normal_balance_for(AccountType.EQUITY) is NormalBalance.CREDIT
    assert normal_balance_for(AccountType.REVENUE) is NormalBalance.CREDIT
    # str form accepted too
    assert normal_balance_for("asset") is NormalBalance.DEBIT


def test_signed_balance_debit_normal_asset() -> None:
    # An asset with more debits than credits is positive (a real asset).
    assert signed_balance(Decimal("1000"), Decimal("300"), NormalBalance.DEBIT) == Decimal("700")


def test_signed_balance_credit_normal_liability() -> None:
    # A liability with more credits than debits is positive (a real claim).
    assert signed_balance(Decimal("300"), Decimal("1000"), NormalBalance.CREDIT) == Decimal("700")


def test_default_chart_has_expected_roots() -> None:
    # The seed must carry the construction-specific accounts the task names.
    assert "1000" in CHART and CHART["1000"].is_cash  # cash
    assert CHART["1100"].account_type is AccountType.ASSET  # AR
    assert CHART["1110"].name.lower().startswith("retention")  # retention receivable
    assert CHART["1200"].account_type is AccountType.ASSET  # under-billings (CIE)
    assert CHART["1300"].account_type is AccountType.ASSET  # WIP / contract costs
    assert CHART["2000"].account_type is AccountType.LIABILITY  # AP
    assert CHART["2200"].account_type is AccountType.LIABILITY  # over-billings (BIE)
    assert CHART["3000"].account_type is AccountType.EQUITY  # equity
    assert CHART["4000"].account_type is AccountType.REVENUE  # contract revenue
    assert CHART["5000"].account_type is AccountType.EXPENSE  # COGS


def test_default_chart_normal_balances_consistent() -> None:
    # Every seed account's normal balance must agree with its type.
    for acc in CHART.values():
        assert acc.normal_balance is normal_balance_for(acc.account_type)


# ── Journal posting: balanced vs unbalanced ──────────────────────────────────


def test_balanced_journal_posts() -> None:
    # Owner injects 50,000 cash as equity: Dr Cash / Cr Equity.
    lines = [_dr("1000", "50000"), _cr("3000", "50000")]
    assert _is_balanced_journal(lines) is True


def test_unbalanced_journal_rejected() -> None:
    # Debits 50,000 but credits only 40,000 - must be rejected.
    lines = [_dr("1000", "50000"), _cr("3000", "40000")]
    assert _is_balanced_journal(lines) is False


def test_zero_value_journal_rejected() -> None:
    lines = [_dr("1000", "0"), _cr("3000", "0")]
    assert _is_balanced_journal(lines) is False


def test_multi_line_balanced_journal_posts() -> None:
    # A 3-line entry: bill a client 100,000 (gross) splitting revenue + tax.
    # Dr AR 110,000 / Cr Revenue 100,000 / Cr Taxes Payable 10,000.
    lines = [_dr("1100", "110000"), _cr("4000", "100000"), _cr("2300", "10000")]
    assert _is_balanced_journal(lines) is True


# ── Currency blending is rejected ────────────────────────────────────────────


def test_trial_balance_rejects_blended_currency() -> None:
    lines = [_dr("1000", "100", ccy="USD"), _cr("4000", "100", ccy="EUR")]
    with pytest.raises(ValueError, match="blended currencies"):
        trial_balance(lines, CHART)


def test_trial_balance_blank_currency_is_base_not_a_conflict() -> None:
    # A blank code is "base" and must not conflict with a stamped one.
    lines = [_dr("1000", "100", ccy=""), _cr("4000", "100", ccy="USD")]
    tb = trial_balance(lines, CHART)
    assert tb.currency == "USD"
    assert tb.is_balanced


# ── Unknown account is caught ────────────────────────────────────────────────


def test_trial_balance_unknown_account_raises() -> None:
    lines = [_dr("9999", "100"), _cr("4000", "100")]
    with pytest.raises(KeyError, match="9999"):
        trial_balance(lines, CHART)


# ── Trial balance ties out ───────────────────────────────────────────────────


def _seed_ledger() -> list[LedgerLine]:
    """A small but realistic set of balanced transactions in USD.

    1. Owner funds the company:        Dr Cash 100,000 / Cr Equity 100,000
    2. Bill a client for work:         Dr AR  60,000  / Cr Revenue 60,000
    3. Incur subcontractor cost:       Dr COGS 25,000 / Cr AP 25,000
    4. Pay overhead salaries in cash:  Dr G&A 8,000   / Cr Cash 8,000
    5. Client pays part of the invoice:Dr Cash 40,000 / Cr AR 40,000
    """
    return [
        # 1
        _dr("1000", "100000", posted_at="2026-01-01"),
        _cr("3000", "100000", posted_at="2026-01-01"),
        # 2
        _dr("1100", "60000", posted_at="2026-01-10"),
        _cr("4000", "60000", posted_at="2026-01-10"),
        # 3
        _dr("5030", "25000", posted_at="2026-01-12"),
        _cr("2000", "25000", posted_at="2026-01-12"),
        # 4
        _dr("5110", "8000", posted_at="2026-01-20"),
        _cr("1000", "8000", posted_at="2026-01-20"),
        # 5
        _dr("1000", "40000", posted_at="2026-01-25"),
        _cr("1100", "40000", posted_at="2026-01-25"),
    ]


def test_trial_balance_ties_out() -> None:
    tb = trial_balance(_seed_ledger(), CHART)
    assert tb.total_debits == Decimal("233000.00")
    assert tb.total_credits == Decimal("233000.00")
    assert tb.is_balanced is True
    assert tb.out_of_balance == Decimal("0.00")


def test_trial_balance_account_balances_correct() -> None:
    tb = trial_balance(_seed_ledger(), CHART)
    by_code = {ab.code: ab for ab in tb.accounts}
    # Cash: 100,000 + 40,000 in, 8,000 out = 132,000 debit-normal.
    assert by_code["1000"].signed_balance == Decimal("132000.00")
    # AR: 60,000 billed - 40,000 collected = 20,000 debit-normal.
    assert by_code["1100"].signed_balance == Decimal("20000.00")
    # AP: 25,000 credit-normal (positive liability).
    assert by_code["2000"].signed_balance == Decimal("25000.00")
    # Equity: 100,000 credit-normal.
    assert by_code["3000"].signed_balance == Decimal("100000.00")
    # Revenue: 60,000 credit-normal.
    assert by_code["4000"].signed_balance == Decimal("60000.00")


# ── Income statement = revenue - expenses ────────────────────────────────────


def test_income_statement_revenue_minus_expenses() -> None:
    tb = trial_balance(_seed_ledger(), CHART)
    inc = income_statement(tb, CHART)
    # Revenue 60,000; expenses 25,000 (COGS) + 8,000 (G&A) = 33,000.
    assert inc.total_revenue == Decimal("60000.00")
    assert inc.total_expenses == Decimal("33000.00")
    assert inc.net_income == Decimal("27000.00")
    # Net income is literally revenue minus expenses.
    assert inc.net_income == inc.total_revenue - inc.total_expenses


def test_income_statement_loss_is_negative() -> None:
    # Expenses exceed revenue -> a loss (negative net income).
    lines = [
        _dr("1100", "10000"),
        _cr("4000", "10000"),
        _dr("5000", "15000"),
        _cr("2000", "15000"),
    ]
    tb = trial_balance(lines, CHART)
    inc = income_statement(tb, CHART)
    assert inc.net_income == Decimal("-5000.00")


# ── Balance sheet ties out (assets == liabilities + equity) ──────────────────


def test_balance_sheet_ties_out() -> None:
    tb = trial_balance(_seed_ledger(), CHART)
    bs = balance_sheet(tb, CHART)
    # Assets: Cash 132,000 + AR 20,000 = 152,000.
    assert bs.total_assets == Decimal("152000.00")
    # Liabilities: AP 25,000.
    assert bs.total_liabilities == Decimal("25000.00")
    # Equity: 100,000 paid-in + 27,000 retained (period net income) = 127,000.
    assert bs.total_equity == Decimal("127000.00")
    assert bs.liabilities_plus_equity == Decimal("152000.00")
    assert bs.is_balanced is True
    assert bs.out_of_balance == Decimal("0.00")


def test_balance_sheet_without_fold_is_out_of_balance_by_net_income() -> None:
    # Before a year-end close (net income not folded into equity) a live ledger
    # is out of balance by exactly net income - documenting the design choice.
    tb = trial_balance(_seed_ledger(), CHART)
    bs_raw = balance_sheet(tb, CHART, fold_net_income_into_equity=False)
    assert bs_raw.is_balanced is False
    # Assets 152,000 vs (L+E) 125,000 -> off by the 27,000 net income.
    assert bs_raw.out_of_balance == Decimal("27000.00")


# ── Reversal produces the inverse ────────────────────────────────────────────


def test_reversal_nets_ledger_to_zero() -> None:
    # Original: Dr AR 60,000 / Cr Revenue 60,000.
    original = [_dr("1100", "60000"), _cr("4000", "60000")]
    # Reversal swaps the sides: Dr Revenue 60,000 / Cr AR 60,000.
    reversal = [_cr("1100", "60000"), _dr("4000", "60000")]
    tb = trial_balance(original + reversal, CHART)
    by_code = {ab.code: ab for ab in tb.accounts}
    # Both accounts net to zero after the reversal.
    assert by_code["1100"].signed_balance == Decimal("0.00")
    assert by_code["4000"].signed_balance == Decimal("0.00")
    # And the whole trial balance is still balanced and empty of value.
    assert tb.is_balanced
    assert tb.total_debits == Decimal("120000.00")
    assert tb.total_credits == Decimal("120000.00")


def test_reversal_inverts_income_statement() -> None:
    original = [_dr("1100", "60000"), _cr("4000", "60000")]
    reversal = [_cr("1100", "60000"), _dr("4000", "60000")]
    inc = income_statement(trial_balance(original + reversal, CHART), CHART)
    assert inc.total_revenue == Decimal("0.00")
    assert inc.net_income == Decimal("0.00")


# ── Cash flow (direct method) ────────────────────────────────────────────────


def test_cash_flow_direct_buckets_and_ties_out() -> None:
    # Operating: client pays 40,000 (counter = revenue/AR), pay salaries -8,000.
    # Financing: owner funds 100,000 (counter = equity).
    movements = [
        CashMovement(amount=Decimal("100000"), counter_type=AccountType.EQUITY, counter_section="financing"),
        CashMovement(amount=Decimal("40000"), counter_type=AccountType.ASSET, counter_section="current_asset"),
        CashMovement(amount=Decimal("-8000"), counter_type=AccountType.EXPENSE, counter_section="operating_expense"),
    ]
    cf = cash_flow_direct(movements, currency="USD", opening_cash=Decimal("0"))
    assert cf.financing == Decimal("100000.00")
    assert cf.operating == Decimal("32000.00")  # 40,000 - 8,000
    assert cf.investing == Decimal("0.00")
    assert cf.net_change == Decimal("132000.00")
    assert cf.closing_cash == Decimal("132000.00")
    assert cf.ties_out is True


def test_cash_flow_investing_bucket() -> None:
    # Buy equipment for cash: -20,000 against a non-current asset (capex).
    movements = [
        CashMovement(amount=Decimal("-20000"), counter_type=AccountType.ASSET, counter_section="investing"),
    ]
    cf = cash_flow_direct(movements, currency="USD", opening_cash=Decimal("50000"))
    assert cf.investing == Decimal("-20000.00")
    assert cf.operating == Decimal("0.00")
    assert cf.net_change == Decimal("-20000.00")
    assert cf.closing_cash == Decimal("30000.00")
    assert cf.ties_out is True


def test_cash_flow_opening_plus_net_equals_closing() -> None:
    movements = [CashMovement(amount=Decimal("5000"), counter_type=AccountType.REVENUE)]
    cf = cash_flow_direct(movements, currency="USD", opening_cash=Decimal("1000"))
    assert cf.closing_cash == cf.opening_cash + cf.net_change


# ── q2 rounding (accounting half-up) ─────────────────────────────────────────


def test_q2_rounds_half_up() -> None:
    assert gaap.q2(Decimal("1666.665")) == Decimal("1666.67")
    assert gaap.q2(Decimal("1666.664")) == Decimal("1666.66")
