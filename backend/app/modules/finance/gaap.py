# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GAAP general-ledger primitives: chart of accounts + statement derivations.

This module is the *pure* core of the GAAP layer. It owns:

* the account-type taxonomy and normal-balance rules,
* the default construction chart of accounts seed,
* the trial-balance / income-statement / balance-sheet / cash-flow
  derivations expressed as **side-effect-free functions** over plain
  ``LedgerLine`` records.

Keeping the maths here (and out of the async service) means the correctness
suite can assert every sign convention and balancing check against exact
``Decimal`` values with no database, no event loop and no fixtures. The async
:class:`app.modules.finance.service.FinanceService` simply loads
:class:`app.modules.finance.models.LedgerEntry` rows, maps them to
``LedgerLine`` and calls these functions.

Sign conventions (GAAP, double-entry)
-------------------------------------
Every account has a *normal balance* - the side on which a positive balance
sits::

    asset      normal DEBIT   -> balance = debits - credits
    expense    normal DEBIT   -> balance = debits - credits
    liability  normal CREDIT  -> balance = credits - debits
    equity     normal CREDIT  -> balance = credits - debits
    revenue    normal CREDIT  -> balance = credits - debits

``signed_balance`` always returns the value in the account's *natural*
direction, so a healthy asset is positive, a healthy liability is positive,
revenue is positive and an expense is positive. The accounting identity then
reads cleanly: ``assets = liabilities + equity`` and
``net_income = revenue - expenses``.

Currency
--------
A single statement is computed in one currency. Currency is never blended in
a sum: callers filter ledger lines to one currency (or the project base
currency, FX-converted upstream) before calling these functions, and the
helpers assert a single currency to fail loudly on a mixed feed rather than
silently adding USD to EUR.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

# ── Quantisation ────────────────────────────────────────────────────────────

_CENTS = Decimal("0.01")
_ZERO = Decimal("0")


def q2(value: Decimal) -> Decimal:
    """Quantise a money ``Decimal`` to two places, half-up (accounting default)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


# ── Account taxonomy ────────────────────────────────────────────────────────


class AccountType(StrEnum):
    """The five GAAP account roots."""

    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class NormalBalance(StrEnum):
    """The side on which an account carries a positive balance."""

    DEBIT = "debit"
    CREDIT = "credit"


# The canonical normal balance for each account type. Assets and expenses are
# debit-normal; liabilities, equity and revenue are credit-normal. This single
# map is the source of truth for every sign decision in the module.
NORMAL_BALANCE_BY_TYPE: dict[AccountType, NormalBalance] = {
    AccountType.ASSET: NormalBalance.DEBIT,
    AccountType.EXPENSE: NormalBalance.DEBIT,
    AccountType.LIABILITY: NormalBalance.CREDIT,
    AccountType.EQUITY: NormalBalance.CREDIT,
    AccountType.REVENUE: NormalBalance.CREDIT,
}


def normal_balance_for(account_type: AccountType | str) -> NormalBalance:
    """Return the normal balance for an account type, accepting the enum or str."""
    if isinstance(account_type, str):
        account_type = AccountType(account_type)
    return NORMAL_BALANCE_BY_TYPE[account_type]


# ── Lightweight value objects ───────────────────────────────────────────────


@dataclass(frozen=True)
class AccountDef:
    """An account definition in the chart of accounts (seed + lookups).

    A plain value object so the seed table and the statement derivations can
    share one description of an account without importing the ORM model.
    """

    code: str
    name: str
    account_type: AccountType
    # Optional parent code for the hierarchy (None for roots).
    parent_code: str | None = None
    # Statement-line grouping hint (e.g. "current_asset", "cogs"). Optional;
    # the statements fall back to the account_type when absent.
    statement_section: str | None = None
    # Whether movements on this account represent cash for the direct cash-flow
    # statement. True only for the cash/bank accounts.
    is_cash: bool = False

    @property
    def normal_balance(self) -> NormalBalance:
        return normal_balance_for(self.account_type)


@dataclass(frozen=True)
class LedgerLine:
    """A single posted ledger row, reduced to what the statements need.

    Mirrors the load-bearing columns of
    :class:`app.modules.finance.models.LedgerEntry`. ``debit`` and ``credit``
    are mutually exclusive (one is zero) by the double-entry invariant, but the
    derivations never rely on that - they always net ``debit - credit``.
    """

    account_code: str
    debit: Decimal = _ZERO
    credit: Decimal = _ZERO
    currency_code: str = ""
    # Optional period anchor (ISO date/datetime string). The service filters by
    # period before constructing lines, so the derivations are period-agnostic.
    posted_at: str = ""


# ── Account-balance computation ─────────────────────────────────────────────


def signed_balance(
    debit_total: Decimal,
    credit_total: Decimal,
    normal: NormalBalance,
) -> Decimal:
    """Return the account balance in its natural (normal-balance) direction.

    Debit-normal accounts (assets, expenses) read ``debits - credits``;
    credit-normal accounts (liabilities, equity, revenue) read
    ``credits - debits``. The result is positive when the account holds a
    healthy balance on its normal side and negative when it is contra.
    """
    if normal is NormalBalance.DEBIT:
        return debit_total - credit_total
    return credit_total - debit_total


@dataclass
class AccountBalance:
    """Per-account aggregation produced by :func:`trial_balance`."""

    code: str
    name: str
    account_type: AccountType
    normal_balance: NormalBalance
    debit_total: Decimal
    credit_total: Decimal

    @property
    def signed_balance(self) -> Decimal:
        """Balance in the account's natural direction (see :func:`signed_balance`)."""
        return signed_balance(self.debit_total, self.credit_total, self.normal_balance)


# ── Currency guard ──────────────────────────────────────────────────────────


def _assert_single_currency(lines: list[LedgerLine]) -> str:
    """Return the single currency in *lines*, or raise on a blended feed.

    The never-blend-currencies rule is enforced here: if more than one
    non-empty currency code appears, we raise ``ValueError`` rather than add
    amounts denominated in different currencies. A blank code is treated as the
    base currency and never conflicts with another blank.
    """
    codes = {(ln.currency_code or "").strip().upper() for ln in lines}
    codes.discard("")
    if len(codes) > 1:
        raise ValueError(
            f"Cannot compute a statement across blended currencies {sorted(codes)}; "
            f"filter or FX-convert to a single currency first."
        )
    return next(iter(codes), "")


# ── Trial balance ───────────────────────────────────────────────────────────


@dataclass
class TrialBalance:
    """The trial balance: per-account totals plus the grand debit/credit check."""

    currency: str
    accounts: list[AccountBalance]
    total_debits: Decimal
    total_credits: Decimal

    @property
    def is_balanced(self) -> bool:
        """True when total debits equal total credits (the books tie out)."""
        return q2(self.total_debits) == q2(self.total_credits)

    @property
    def out_of_balance(self) -> Decimal:
        """Signed debit-minus-credit residual (zero when balanced)."""
        return q2(self.total_debits - self.total_credits)


def trial_balance(
    lines: list[LedgerLine],
    accounts: dict[str, AccountDef],
) -> TrialBalance:
    """Aggregate ledger *lines* into a trial balance keyed by account.

    Args:
        lines: posted ledger lines, already filtered to one period / scope.
        accounts: chart-of-accounts lookup ``{code: AccountDef}``. Every line's
            ``account_code`` must resolve here - an unknown code raises
            ``KeyError`` so posting against a non-existent account is caught.

    Returns:
        A :class:`TrialBalance` whose ``total_debits`` and ``total_credits`` are
        the raw column sums (they are equal whenever the ledger is internally
        consistent - the double-entry invariant guarantees it).

    Accounts are emitted in chart order (by code) and only when they carry a
    movement, so the trial balance lists exactly the accounts that moved.
    """
    currency = _assert_single_currency(lines)

    debit_by_code: dict[str, Decimal] = {}
    credit_by_code: dict[str, Decimal] = {}
    total_debits = _ZERO
    total_credits = _ZERO

    for ln in lines:
        code = ln.account_code
        if code not in accounts:
            raise KeyError(
                f"Ledger line references unknown account_code {code!r} - it is not in the chart of accounts."
            )
        debit_by_code[code] = debit_by_code.get(code, _ZERO) + ln.debit
        credit_by_code[code] = credit_by_code.get(code, _ZERO) + ln.credit
        total_debits += ln.debit
        total_credits += ln.credit

    touched = sorted(set(debit_by_code) | set(credit_by_code), key=lambda c: accounts[c].code)
    rows: list[AccountBalance] = []
    for code in touched:
        acc = accounts[code]
        rows.append(
            AccountBalance(
                code=acc.code,
                name=acc.name,
                account_type=acc.account_type,
                normal_balance=acc.normal_balance,
                debit_total=q2(debit_by_code.get(code, _ZERO)),
                credit_total=q2(credit_by_code.get(code, _ZERO)),
            )
        )

    return TrialBalance(
        currency=currency,
        accounts=rows,
        total_debits=q2(total_debits),
        total_credits=q2(total_credits),
    )


# ── Statement line + base container ──────────────────────────────────────────


@dataclass
class StatementLine:
    """One line on a financial statement (an account or a subtotal group)."""

    code: str
    name: str
    amount: Decimal
    account_type: str = ""
    section: str = ""


# ── Income statement (P&L) ──────────────────────────────────────────────────


@dataclass
class IncomeStatement:
    """Profit & loss for a period: revenue, expenses and net income."""

    currency: str
    revenue_lines: list[StatementLine]
    expense_lines: list[StatementLine]
    total_revenue: Decimal
    total_expenses: Decimal

    @property
    def net_income(self) -> Decimal:
        """Net income = total revenue - total expenses (positive is profit)."""
        return q2(self.total_revenue - self.total_expenses)


def income_statement(
    tb: TrialBalance,
    accounts: dict[str, AccountDef],
) -> IncomeStatement:
    """Derive the income statement from a trial balance.

    Revenue accounts are credit-normal, so their ``signed_balance`` is the
    revenue earned (positive). Expense accounts are debit-normal, so their
    ``signed_balance`` is the cost incurred (positive). Net income is the
    difference. Only revenue/expense accounts participate; balance-sheet
    accounts are ignored.
    """
    revenue_lines: list[StatementLine] = []
    expense_lines: list[StatementLine] = []
    total_revenue = _ZERO
    total_expenses = _ZERO

    for ab in tb.accounts:
        if ab.account_type is AccountType.REVENUE:
            amount = ab.signed_balance
            total_revenue += amount
            revenue_lines.append(
                StatementLine(
                    code=ab.code,
                    name=ab.name,
                    amount=q2(amount),
                    account_type=ab.account_type.value,
                    section=_section_for(accounts, ab.code, "revenue"),
                )
            )
        elif ab.account_type is AccountType.EXPENSE:
            amount = ab.signed_balance
            total_expenses += amount
            expense_lines.append(
                StatementLine(
                    code=ab.code,
                    name=ab.name,
                    amount=q2(amount),
                    account_type=ab.account_type.value,
                    section=_section_for(accounts, ab.code, "expense"),
                )
            )

    return IncomeStatement(
        currency=tb.currency,
        revenue_lines=revenue_lines,
        expense_lines=expense_lines,
        total_revenue=q2(total_revenue),
        total_expenses=q2(total_expenses),
    )


# ── Balance sheet ────────────────────────────────────────────────────────────


@dataclass
class BalanceSheet:
    """Statement of financial position as of a date.

    ``retained_earnings`` folds period net income into equity so the identity
    ``assets = liabilities + equity`` ties out even before a formal year-end
    close has moved P&L into retained earnings. Without this, a live ledger
    (revenue/expense not yet closed to equity) would always appear out of
    balance by exactly net income.
    """

    currency: str
    asset_lines: list[StatementLine]
    liability_lines: list[StatementLine]
    equity_lines: list[StatementLine]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal

    @property
    def liabilities_plus_equity(self) -> Decimal:
        return q2(self.total_liabilities + self.total_equity)

    @property
    def is_balanced(self) -> bool:
        """True when assets == liabilities + equity (the sheet ties out)."""
        return q2(self.total_assets) == self.liabilities_plus_equity

    @property
    def out_of_balance(self) -> Decimal:
        """Signed residual assets - (liabilities + equity); zero when balanced."""
        return q2(self.total_assets - self.liabilities_plus_equity)


# The synthetic line code/name used to fold current-period net income into
# equity so a live (pre-close) ledger still balances.
RETAINED_EARNINGS_CODE = "3900"
RETAINED_EARNINGS_NAME = "Retained Earnings (current period)"


def balance_sheet(
    tb: TrialBalance,
    accounts: dict[str, AccountDef],
    *,
    fold_net_income_into_equity: bool = True,
) -> BalanceSheet:
    """Derive the balance sheet from a trial balance.

    Assets are debit-normal (positive ``signed_balance`` = a real asset);
    liabilities and equity are credit-normal (positive = a real claim). When
    ``fold_net_income_into_equity`` is True the period net income (revenue -
    expenses, from the same trial balance) is added as a synthetic retained
    earnings equity line so the accounting identity holds on a live ledger that
    has not yet been closed. Set it False to see equity exactly as posted (which
    only balances after a year-end close).
    """
    asset_lines: list[StatementLine] = []
    liability_lines: list[StatementLine] = []
    equity_lines: list[StatementLine] = []
    total_assets = _ZERO
    total_liabilities = _ZERO
    total_equity = _ZERO
    period_revenue = _ZERO
    period_expense = _ZERO

    for ab in tb.accounts:
        amount = ab.signed_balance
        if ab.account_type is AccountType.ASSET:
            total_assets += amount
            asset_lines.append(_bs_line(accounts, ab, "asset"))
        elif ab.account_type is AccountType.LIABILITY:
            total_liabilities += amount
            liability_lines.append(_bs_line(accounts, ab, "liability"))
        elif ab.account_type is AccountType.EQUITY:
            total_equity += amount
            equity_lines.append(_bs_line(accounts, ab, "equity"))
        elif ab.account_type is AccountType.REVENUE:
            period_revenue += amount
        elif ab.account_type is AccountType.EXPENSE:
            period_expense += amount

    if fold_net_income_into_equity:
        net_income = period_revenue - period_expense
        if net_income != _ZERO or equity_lines:
            total_equity += net_income
            equity_lines.append(
                StatementLine(
                    code=RETAINED_EARNINGS_CODE,
                    name=RETAINED_EARNINGS_NAME,
                    amount=q2(net_income),
                    account_type=AccountType.EQUITY.value,
                    section="retained_earnings",
                )
            )

    return BalanceSheet(
        currency=tb.currency,
        asset_lines=asset_lines,
        liability_lines=liability_lines,
        equity_lines=equity_lines,
        total_assets=q2(total_assets),
        total_liabilities=q2(total_liabilities),
        total_equity=q2(total_equity),
    )


# ── Cash flow (direct method from cash-account movements) ─────────────────────


@dataclass
class CashFlowStatement:
    """Direct-method cash flow derived from cash-account ledger movements.

    Honest scope (see module/service docstrings): this is the *direct* method
    built purely from movements on accounts flagged ``is_cash`` in the chart.
    Net change in cash = sum of debits (cash in) minus credits (cash out) on the
    cash accounts. The counter-account of each cash movement classifies it into
    operating / investing / financing using a coarse account-type heuristic; a
    full indirect statement (working-capital roll-forward, non-cash add-backs)
    is intentionally NOT attempted here because it needs an opening balance
    sheet and an accrual close that the live ledger alone does not pin down.
    """

    currency: str
    operating: Decimal
    investing: Decimal
    financing: Decimal
    opening_cash: Decimal
    net_change: Decimal

    @property
    def closing_cash(self) -> Decimal:
        return q2(self.opening_cash + self.net_change)

    @property
    def ties_out(self) -> bool:
        """True when the three activity buckets sum to the net change in cash."""
        return q2(self.operating + self.investing + self.financing) == q2(self.net_change)


def _classify_activity(counter_type: AccountType | None) -> str:
    """Map the counter-account type of a cash movement to a cash-flow bucket.

    Coarse but defensible direct-method classification:
      * revenue / expense / current liabilities & assets  -> operating
      * non-current assets (capex)                         -> investing
      * equity / long-term liabilities (loans, capital)    -> financing

    The chart's ``statement_section`` refines this (e.g. a non-current asset is
    tagged ``investing``); absent a hint we fall back to the type. ``None``
    (cash-to-cash transfer) nets to zero and lands in operating by convention.
    """
    if counter_type is None:
        return "operating"
    if counter_type is AccountType.EQUITY:
        return "financing"
    if counter_type is AccountType.REVENUE or counter_type is AccountType.EXPENSE:
        return "operating"
    # Assets and liabilities default to operating; the section hint upgrades
    # capex/long-term-debt movements to investing/financing in cash_flow().
    return "operating"


@dataclass(frozen=True)
class CashMovement:
    """One cash leg with its paired counter-account, for direct cash flow.

    The service pairs the cash leg of a transaction with the non-cash leg
    (same ``transaction_ref``) so the counter-account type/section can classify
    the movement. ``amount`` is signed: positive = cash in, negative = cash out.
    """

    amount: Decimal
    counter_type: AccountType | None = None
    counter_section: str | None = None


def cash_flow_direct(
    movements: list[CashMovement],
    *,
    currency: str = "",
    opening_cash: Decimal = _ZERO,
) -> CashFlowStatement:
    """Build a direct-method cash flow from classified cash *movements*.

    Each movement's signed ``amount`` is bucketed into operating / investing /
    financing by its counter-account. The buckets sum to the net change in cash,
    which is asserted via :attr:`CashFlowStatement.ties_out`.
    """
    operating = _ZERO
    investing = _ZERO
    financing = _ZERO

    for mv in movements:
        section = (mv.counter_section or "").strip().lower()
        if section in ("investing", "financing", "operating"):
            bucket = section
        else:
            bucket = _classify_activity(mv.counter_type)
        if bucket == "investing":
            investing += mv.amount
        elif bucket == "financing":
            financing += mv.amount
        else:
            operating += mv.amount

    net_change = operating + investing + financing
    return CashFlowStatement(
        currency=currency,
        operating=q2(operating),
        investing=q2(investing),
        financing=q2(financing),
        opening_cash=q2(opening_cash),
        net_change=q2(net_change),
    )


# ── Section helpers ──────────────────────────────────────────────────────────


def _section_for(accounts: dict[str, AccountDef], code: str, fallback: str) -> str:
    acc = accounts.get(code)
    if acc and acc.statement_section:
        return acc.statement_section
    return fallback


def _bs_line(accounts: dict[str, AccountDef], ab: AccountBalance, fallback: str) -> StatementLine:
    return StatementLine(
        code=ab.code,
        name=ab.name,
        amount=q2(ab.signed_balance),
        account_type=ab.account_type.value,
        section=_section_for(accounts, ab.code, fallback),
    )


# ── Default construction chart of accounts ───────────────────────────────────
#
# A pragmatic GAAP chart tuned for a construction / project business. Codes use
# the classic 1xxx-5xxx ranges:
#   1xxx assets, 2xxx liabilities, 3xxx equity, 4xxx revenue, 5xxx expense.
# Over/under-billings (contract assets/liabilities) and retention are first
# class because they dominate construction balance sheets.

_DEFAULT_ACCOUNTS: tuple[AccountDef, ...] = (
    # ── Assets (1xxx) ────────────────────────────────────────────────────────
    AccountDef("1000", "Cash and Cash Equivalents", AccountType.ASSET, None, "current_asset", is_cash=True),
    AccountDef("1010", "Operating Bank Account", AccountType.ASSET, "1000", "current_asset", is_cash=True),
    AccountDef("1100", "Accounts Receivable", AccountType.ASSET, None, "current_asset"),
    AccountDef("1110", "Retention Receivable", AccountType.ASSET, "1100", "current_asset"),
    AccountDef(
        "1200",
        "Costs and Estimated Earnings in Excess of Billings",
        AccountType.ASSET,
        None,
        "current_asset",
    ),
    AccountDef("1300", "Work in Progress (Contract Costs)", AccountType.ASSET, None, "current_asset"),
    AccountDef("1400", "Materials Inventory", AccountType.ASSET, None, "current_asset"),
    AccountDef("1500", "Prepaid Expenses", AccountType.ASSET, None, "current_asset"),
    AccountDef("1700", "Property, Plant and Equipment", AccountType.ASSET, None, "investing"),
    AccountDef("1710", "Construction Equipment", AccountType.ASSET, "1700", "investing"),
    AccountDef("1790", "Accumulated Depreciation", AccountType.ASSET, "1700", "investing"),
    # ── Liabilities (2xxx) ───────────────────────────────────────────────────
    AccountDef("2000", "Accounts Payable", AccountType.LIABILITY, None, "current_liability"),
    AccountDef("2010", "Retention Payable", AccountType.LIABILITY, "2000", "current_liability"),
    AccountDef("2100", "Accrued Liabilities", AccountType.LIABILITY, None, "current_liability"),
    AccountDef(
        "2200",
        "Billings in Excess of Costs and Estimated Earnings",
        AccountType.LIABILITY,
        None,
        "current_liability",
    ),
    AccountDef("2300", "Taxes Payable", AccountType.LIABILITY, None, "current_liability"),
    AccountDef("2400", "Deferred Revenue", AccountType.LIABILITY, None, "current_liability"),
    AccountDef("2700", "Long-Term Debt", AccountType.LIABILITY, None, "financing"),
    AccountDef("2710", "Notes Payable", AccountType.LIABILITY, "2700", "financing"),
    # ── Equity (3xxx) ────────────────────────────────────────────────────────
    AccountDef("3000", "Owner's Capital / Common Stock", AccountType.EQUITY, None, "financing"),
    AccountDef("3100", "Additional Paid-In Capital", AccountType.EQUITY, None, "financing"),
    AccountDef("3200", "Retained Earnings", AccountType.EQUITY, None, "retained_earnings"),
    AccountDef("3300", "Distributions / Dividends", AccountType.EQUITY, None, "financing"),
    # ── Revenue (4xxx) ───────────────────────────────────────────────────────
    AccountDef("4000", "Contract Revenue", AccountType.REVENUE, None, "revenue"),
    AccountDef("4100", "Change Order Revenue", AccountType.REVENUE, None, "revenue"),
    AccountDef("4200", "Service Revenue", AccountType.REVENUE, None, "revenue"),
    AccountDef("4900", "Other Income", AccountType.REVENUE, None, "other_income"),
    # ── Expenses (5xxx) ──────────────────────────────────────────────────────
    AccountDef("5000", "Cost of Construction (COGS)", AccountType.EXPENSE, None, "cogs"),
    AccountDef("5010", "Direct Labor", AccountType.EXPENSE, "5000", "cogs"),
    AccountDef("5020", "Direct Materials", AccountType.EXPENSE, "5000", "cogs"),
    AccountDef("5030", "Subcontractor Costs", AccountType.EXPENSE, "5000", "cogs"),
    AccountDef("5040", "Equipment Costs", AccountType.EXPENSE, "5000", "cogs"),
    AccountDef("5100", "General and Administrative", AccountType.EXPENSE, None, "operating_expense"),
    AccountDef("5110", "Salaries and Wages (Overhead)", AccountType.EXPENSE, "5100", "operating_expense"),
    AccountDef("5200", "Depreciation Expense", AccountType.EXPENSE, None, "operating_expense"),
    AccountDef("5300", "Interest Expense", AccountType.EXPENSE, None, "operating_expense"),
    AccountDef("5900", "Other Expense", AccountType.EXPENSE, None, "operating_expense"),
)


def default_chart_of_accounts() -> OrderedDict[str, AccountDef]:
    """Return the default construction chart of accounts as ``{code: AccountDef}``.

    Ordered by code so callers that iterate get a stable, readable layout. The
    returned mapping is freshly built on each call so a caller mutating it (e.g.
    adding custom accounts) cannot corrupt the module-level seed.
    """
    chart: OrderedDict[str, AccountDef] = OrderedDict()
    for acc in sorted(_DEFAULT_ACCOUNTS, key=lambda a: a.code):
        chart[acc.code] = acc
    return chart


# Frozen module-level view for read-only callers (tests, validation).
DEFAULT_CHART: dict[str, AccountDef] = dict(default_chart_of_accounts())

# Re-export the cash account codes for the direct cash-flow derivation.
CASH_ACCOUNT_CODES: frozenset[str] = frozenset(a.code for a in _DEFAULT_ACCOUNTS if a.is_cash)


__all__ = [
    "CASH_ACCOUNT_CODES",
    "DEFAULT_CHART",
    "RETAINED_EARNINGS_CODE",
    "AccountBalance",
    "AccountDef",
    "AccountType",
    "BalanceSheet",
    "CashFlowStatement",
    "CashMovement",
    "IncomeStatement",
    "LedgerLine",
    "NormalBalance",
    "StatementLine",
    "TrialBalance",
    "balance_sheet",
    "cash_flow_direct",
    "default_chart_of_accounts",
    "income_statement",
    "normal_balance_for",
    "q2",
    "signed_balance",
    "trial_balance",
]
