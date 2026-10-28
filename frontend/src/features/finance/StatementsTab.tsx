// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  FileSpreadsheet,
  Scale,
  ArrowRightLeft,
  BookOpen,
  Lock,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';
import clsx from 'clsx';
import { Card, Badge, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet, ApiError } from '@/shared/lib/api';

/* ── Types (mirror backend finance/schemas.py GAAP responses) ───────────── */

interface StatementLine {
  code: string;
  name: string;
  amount: string; // Decimal-as-string
  account_type: string;
  section: string;
}

interface IncomeStatement {
  currency: string;
  date_from: string | null;
  date_to: string | null;
  revenue_lines: StatementLine[];
  expense_lines: StatementLine[];
  total_revenue: string;
  total_expenses: string;
  net_income: string;
}

interface BalanceSheet {
  currency: string;
  as_of: string | null;
  asset_lines: StatementLine[];
  liability_lines: StatementLine[];
  equity_lines: StatementLine[];
  total_assets: string;
  total_liabilities: string;
  total_equity: string;
  liabilities_plus_equity: string;
  is_balanced: boolean;
  out_of_balance: string;
}

interface CashFlow {
  currency: string;
  date_from: string | null;
  date_to: string | null;
  method: string;
  operating: string;
  investing: string;
  financing: string;
  opening_cash: string;
  net_change: string;
  closing_cash: string;
  ties_out: boolean;
}

interface TrialBalanceRow {
  account_code: string;
  name: string;
  account_type: string;
  normal_balance: string;
  debit_total: string;
  credit_total: string;
  balance: string;
}

interface TrialBalance {
  currency: string;
  as_of: string | null;
  date_from: string | null;
  rows: TrialBalanceRow[];
  total_debits: string;
  total_credits: string;
  is_balanced: boolean;
  out_of_balance: string;
}

type StatementKey = 'income' | 'balance' | 'cashflow' | 'trial';

/* ── Constants / helpers ────────────────────────────────────────────────── */

const inputCls =
  'h-10 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

// Construction-market currency shortlist for the statement filter. The active
// project currency (resolved from the finance dashboard) is merged in, so a
// project priced in any ISO code always has its own currency selectable. This
// is only a filter over the ledger — the statement itself is rendered in the
// currency the backend echoes back (``data.currency``).
const CURRENCY_SHORTLIST = [
  'EUR', 'USD', 'GBP', 'CHF', 'BRL', 'PLN', 'CZK', 'SEK', 'NOK', 'DKK', 'AED', 'SAR',
];

/** A forbidden (403) error means the caller lacks ``finance.gl.read``. */
function isForbidden(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403;
}

/** Local YYYY-MM-DD for today (avoids a UTC off-by-one at the day boundary). */
function todayLocal(): string {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

/** First day of the current calendar year (year-to-date default). */
function startOfYearLocal(): string {
  return `${new Date().getFullYear()}-01-01`;
}

/**
 * True when a Decimal-as-string amount is zero ("0", "0.00", "-0.0", "").
 * Regex, not parseFloat — we never coerce the wire value for display, and this
 * emptiness check must not drop precision either.
 */
function isZeroAmount(s: string | null | undefined): boolean {
  return /^-?0*(\.0*)?$/.test((s ?? '').trim());
}

/* ── Small presentational pieces ────────────────────────────────────────── */

/** One statement line: code + name on the left, right-aligned money. */
function LineRow({
  line,
  currency,
}: {
  line: StatementLine;
  currency: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-1.5">
      <span className="min-w-0 text-sm text-content-secondary">
        {line.code ? (
          <span className="mr-2 font-mono text-2xs text-content-tertiary">{line.code}</span>
        ) : null}
        {line.name}
      </span>
      <span className="shrink-0 text-right text-sm tabular-nums text-content-primary">
        <MoneyDisplay amount={line.amount} currency={currency} />
      </span>
    </div>
  );
}

/** A titled group of statement lines closed by a subtotal row. */
function StatementSection({
  title,
  lines,
  total,
  totalLabel,
  currency,
}: {
  title: string;
  lines: StatementLine[];
  total: string;
  totalLabel: string;
  currency: string;
}) {
  const { t } = useTranslation();
  return (
    <section>
      <h4 className="mb-1 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
        {title}
      </h4>
      <div className="divide-y divide-border-light">
        {lines.length > 0 ? (
          lines.map((line) => (
            <LineRow key={`${line.code}-${line.name}`} line={line} currency={currency} />
          ))
        ) : (
          <div className="py-1.5 text-sm text-content-tertiary">
            {t('finance.stmt_no_lines', { defaultValue: 'No entries in this period' })}
          </div>
        )}
      </div>
      <div className="mt-1 flex items-center justify-between gap-4 border-t border-border pt-2">
        <span className="text-sm font-medium text-content-secondary">{totalLabel}</span>
        <span className="shrink-0 text-right text-sm font-semibold tabular-nums text-content-primary">
          <MoneyDisplay amount={total} currency={currency} />
        </span>
      </div>
    </section>
  );
}

/** A scalar row (label + amount), optionally emphasised or muted. */
function AmountRow({
  label,
  amount,
  currency,
  variant = 'normal',
  colorize,
}: {
  label: ReactNode;
  amount: string;
  currency: string;
  variant?: 'normal' | 'muted' | 'total';
  colorize?: boolean;
}) {
  const total = variant === 'total';
  return (
    <div
      className={clsx(
        'flex items-center justify-between gap-4',
        total ? 'border-t-2 border-border pt-2.5 mt-1' : 'py-1.5',
      )}
    >
      <span
        className={clsx(
          'text-sm',
          total
            ? 'font-semibold text-content-primary'
            : variant === 'muted'
              ? 'text-content-tertiary'
              : 'text-content-secondary',
        )}
      >
        {label}
      </span>
      <span
        className={clsx(
          'shrink-0 text-right tabular-nums',
          total ? 'text-base font-bold text-content-primary' : 'text-sm text-content-primary',
        )}
      >
        <MoneyDisplay amount={amount} currency={currency} colorize={colorize} />
      </span>
    </div>
  );
}

/** Green/red tie-out badge; shows the out-of-balance delta when it fails. */
function TieOutBadge({
  ok,
  delta,
  currency,
  okLabel,
}: {
  ok: boolean;
  delta?: string;
  currency: string;
  okLabel: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2">
      <Badge variant={ok ? 'success' : 'error'} size="sm">
        {ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
        {ok ? okLabel : t('finance.stmt_out_of_balance', { defaultValue: 'Out of balance' })}
      </Badge>
      {!ok && delta != null && (
        <span className="text-xs font-medium tabular-nums text-semantic-error">
          <MoneyDisplay amount={delta} currency={currency} />
        </span>
      )}
    </div>
  );
}

/** "Period" / "As of" caption line under a statement header. */
function StatementCaption({
  as_of,
  from,
  to,
  extra,
}: {
  as_of?: string;
  from?: string;
  to?: string;
  extra?: string;
}) {
  const { t } = useTranslation();
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-content-tertiary">
      {as_of ? (
        <>
          <span>{t('finance.stmt_as_of', { defaultValue: 'As of' })}</span>
          <DateDisplay value={as_of} className="font-medium text-content-secondary" />
        </>
      ) : (
        <>
          <span>{t('finance.stmt_period_label', { defaultValue: 'Period' })}</span>
          {from && <DateDisplay value={from} className="font-medium text-content-secondary" />}
          <span>–</span>
          {to && <DateDisplay value={to} className="font-medium text-content-secondary" />}
        </>
      )}
      {extra && <span className="text-content-tertiary">· {extra}</span>}
    </p>
  );
}

/**
 * Loading / error / 403 / empty wrapper shared by every statement panel. A 403
 * (no ``finance.gl.read``) renders a friendly access-required empty state
 * rather than crashing; any other error falls back to the recovery card.
 */
function StatementFrame({
  loading,
  isError,
  error,
  empty,
  onRetry,
  children,
}: {
  loading: boolean;
  isError: boolean;
  error: unknown;
  empty: boolean;
  onRetry: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();

  if (isError && isForbidden(error)) {
    return (
      <EmptyState
        icon={<Lock size={26} strokeWidth={1.5} />}
        title={t('finance.stmt_forbidden_title', {
          defaultValue: 'General ledger access required',
        })}
        description={t('finance.stmt_forbidden_desc', {
          defaultValue:
            'You do not have permission to read the general ledger, so financial statements cannot be shown. Ask an administrator to grant the finance ledger read role.',
        })}
      />
    );
  }
  if (isError) return <RecoveryCard error={error} onRetry={onRetry} />;
  if (loading) return <SkeletonTable rows={6} columns={4} />;
  if (empty) {
    return (
      <EmptyState
        icon={<BookOpen size={26} strokeWidth={1.5} />}
        title={t('finance.stmt_empty_title', { defaultValue: 'No ledger activity' })}
        description={t('finance.stmt_empty_desc', {
          defaultValue:
            'No posted journal entries fall in this period. Post supplier invoices to the ledger from the invoice inbox to populate these statements.',
        })}
      />
    );
  }
  return <>{children}</>;
}

/* ── Statement views ────────────────────────────────────────────────────── */

function IncomeStatementView({
  data,
  currency,
}: {
  data: IncomeStatement;
  currency: string;
}) {
  const { t } = useTranslation();
  const cur = data.currency || currency;
  return (
    <Card padding="none" className="p-5 space-y-5">
      <StatementCaption from={data.date_from ?? undefined} to={data.date_to ?? undefined} />
      <StatementSection
        title={t('finance.stmt_revenue', { defaultValue: 'Revenue' })}
        lines={data.revenue_lines}
        total={data.total_revenue}
        totalLabel={t('finance.stmt_total_revenue', { defaultValue: 'Total revenue' })}
        currency={cur}
      />
      <StatementSection
        title={t('finance.stmt_expenses', { defaultValue: 'Expenses' })}
        lines={data.expense_lines}
        total={data.total_expenses}
        totalLabel={t('finance.stmt_total_expenses', { defaultValue: 'Total expenses' })}
        currency={cur}
      />
      <AmountRow
        label={t('finance.stmt_net_income', { defaultValue: 'Net income' })}
        amount={data.net_income}
        currency={cur}
        variant="total"
        colorize
      />
    </Card>
  );
}

function BalanceSheetView({
  data,
  currency,
}: {
  data: BalanceSheet;
  currency: string;
}) {
  const { t } = useTranslation();
  const cur = data.currency || currency;
  return (
    <Card padding="none" className="p-5 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatementCaption as_of={data.as_of ?? undefined} />
        <TieOutBadge
          ok={data.is_balanced}
          delta={data.out_of_balance}
          currency={cur}
          okLabel={t('finance.stmt_balanced', { defaultValue: 'Balanced' })}
        />
      </div>
      <StatementSection
        title={t('finance.stmt_assets', { defaultValue: 'Assets' })}
        lines={data.asset_lines}
        total={data.total_assets}
        totalLabel={t('finance.stmt_total_assets', { defaultValue: 'Total assets' })}
        currency={cur}
      />
      <StatementSection
        title={t('finance.stmt_liabilities', { defaultValue: 'Liabilities' })}
        lines={data.liability_lines}
        total={data.total_liabilities}
        totalLabel={t('finance.stmt_total_liabilities', { defaultValue: 'Total liabilities' })}
        currency={cur}
      />
      <StatementSection
        title={t('finance.stmt_equity', { defaultValue: 'Equity' })}
        lines={data.equity_lines}
        total={data.total_equity}
        totalLabel={t('finance.stmt_total_equity', { defaultValue: 'Total equity' })}
        currency={cur}
      />
      <AmountRow
        label={t('finance.stmt_liabilities_plus_equity', {
          defaultValue: 'Liabilities + equity',
        })}
        amount={data.liabilities_plus_equity}
        currency={cur}
        variant="total"
      />
    </Card>
  );
}

function CashFlowView({ data, currency }: { data: CashFlow; currency: string }) {
  const { t } = useTranslation();
  const cur = data.currency || currency;
  return (
    <Card padding="none" className="p-5 space-y-2">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <StatementCaption
          from={data.date_from ?? undefined}
          to={data.date_to ?? undefined}
          extra={t('finance.stmt_method_direct', { defaultValue: 'Direct method' })}
        />
        <TieOutBadge
          ok={data.ties_out}
          currency={cur}
          okLabel={t('finance.stmt_ties_out', { defaultValue: 'Ties out' })}
        />
      </div>
      <AmountRow
        label={t('finance.stmt_operating', { defaultValue: 'Operating activities' })}
        amount={data.operating}
        currency={cur}
        colorize
      />
      <AmountRow
        label={t('finance.stmt_investing', { defaultValue: 'Investing activities' })}
        amount={data.investing}
        currency={cur}
        colorize
      />
      <AmountRow
        label={t('finance.stmt_financing', { defaultValue: 'Financing activities' })}
        amount={data.financing}
        currency={cur}
        colorize
      />
      <AmountRow
        label={t('finance.stmt_net_change', { defaultValue: 'Net change in cash' })}
        amount={data.net_change}
        currency={cur}
        variant="total"
        colorize
      />
      <div className="pt-1">
        <AmountRow
          label={t('finance.stmt_opening_cash', { defaultValue: 'Opening cash' })}
          amount={data.opening_cash}
          currency={cur}
          variant="muted"
        />
        <AmountRow
          label={t('finance.stmt_closing_cash', { defaultValue: 'Closing cash' })}
          amount={data.closing_cash}
          currency={cur}
        />
      </div>
    </Card>
  );
}

function TrialBalanceView({
  data,
  currency,
}: {
  data: TrialBalance;
  currency: string;
}) {
  const { t } = useTranslation();
  const cur = data.currency || currency;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatementCaption as_of={data.as_of ?? undefined} />
        <TieOutBadge
          ok={data.is_balanced}
          delta={data.out_of_balance}
          currency={cur}
          okLabel={t('finance.stmt_balanced', { defaultValue: 'Balanced' })}
        />
      </div>
      <Card padding="none" className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-content-secondary">
                <th className="px-4 py-3 font-medium">
                  {t('finance.stmt_col_account', { defaultValue: 'Account' })}
                </th>
                <th className="px-4 py-3 font-medium">
                  {t('finance.stmt_col_type', { defaultValue: 'Type' })}
                </th>
                <th className="px-4 py-3 text-right font-medium">
                  {t('finance.stmt_col_debit', { defaultValue: 'Debit' })}
                </th>
                <th className="px-4 py-3 text-right font-medium">
                  {t('finance.stmt_col_credit', { defaultValue: 'Credit' })}
                </th>
                <th className="px-4 py-3 text-right font-medium">
                  {t('finance.stmt_col_balance', { defaultValue: 'Balance' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr
                  key={r.account_code}
                  className="border-b border-border/60 last:border-0 hover:bg-surface-secondary/50"
                >
                  <td className="px-4 py-2.5">
                    <span className="mr-2 font-mono text-2xs text-content-tertiary">
                      {r.account_code}
                    </span>
                    <span className="text-content-primary">{r.name}</span>
                  </td>
                  <td className="px-4 py-2.5 capitalize text-content-secondary">
                    {r.account_type}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-content-primary">
                    <MoneyDisplay amount={r.debit_total} currency={cur} />
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-content-primary">
                    <MoneyDisplay amount={r.credit_total} currency={cur} />
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-content-primary">
                    <MoneyDisplay amount={r.balance} currency={cur} />
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-border font-semibold text-content-primary">
                <td className="px-4 py-3" colSpan={2}>
                  {t('finance.stmt_totals', { defaultValue: 'Totals' })}
                </td>
                <td className="px-4 py-3 text-right tabular-nums">
                  <MoneyDisplay amount={data.total_debits} currency={cur} />
                </td>
                <td className="px-4 py-3 text-right tabular-nums">
                  <MoneyDisplay amount={data.total_credits} currency={cur} />
                </td>
                <td className="px-4 py-3" />
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>
    </div>
  );
}

/* ── Tab ────────────────────────────────────────────────────────────────── */

const SEGMENTS: { key: StatementKey; labelKey: string; label: string; icon: ReactNode }[] = [
  {
    key: 'income',
    labelKey: 'finance.stmt_seg_income',
    label: 'Income statement',
    icon: <FileSpreadsheet size={14} />,
  },
  {
    key: 'balance',
    labelKey: 'finance.stmt_seg_balance',
    label: 'Balance sheet',
    icon: <Scale size={14} />,
  },
  {
    key: 'cashflow',
    labelKey: 'finance.stmt_seg_cashflow',
    label: 'Cash flow',
    icon: <ArrowRightLeft size={14} />,
  },
  {
    key: 'trial',
    labelKey: 'finance.stmt_seg_trial',
    label: 'Trial balance',
    icon: <BookOpen size={14} />,
  },
];

export function StatementsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();

  const [statement, setStatement] = useState<StatementKey>('income');
  const [dateFrom, setDateFrom] = useState<string>(startOfYearLocal);
  const [dateTo, setDateTo] = useState<string>(todayLocal);
  const [currencyOverride, setCurrencyOverride] = useState<string | null>(null);

  // Resolve the active project's base currency. Shares the dashboard query key
  // used across the Finance page, so this is a cache hit in practice.
  const { data: dashboard } = useQuery({
    queryKey: ['finance', 'dashboard', projectId],
    queryFn: () =>
      apiGet<{ currency?: string }>(`/v1/finance/dashboard/?project_id=${projectId}`),
  });
  const projectCurrency = dashboard?.currency || '';
  const currency = currencyOverride || projectCurrency || 'EUR';

  const currencyChoices = useMemo(() => {
    const set = new Set<string>();
    if (/^[A-Z]{3}$/.test(projectCurrency)) set.add(projectCurrency);
    CURRENCY_SHORTLIST.forEach((c) => set.add(c));
    if (/^[A-Z]{3}$/.test(currency)) set.add(currency);
    return Array.from(set);
  }, [projectCurrency, currency]);

  // Scope every statement to the active project. The GL statement endpoints
  // accept project_id=None for a consolidated (whole-workspace) view, but that
  // path is admin-only server-side, so a plain finance.gl.read user would get a
  // 400. Passing the active project keeps the tab working for every role and
  // mirrors the sibling InvoiceInboxTab, which reads /gaap/accounts the same way.
  const scope = `project_id=${encodeURIComponent(projectId)}` +
    (currency ? `&currency_code=${encodeURIComponent(currency)}` : '');
  const period = (dateFrom ? `&date_from=${encodeURIComponent(dateFrom)}` : '') +
    (dateTo ? `&date_to=${encodeURIComponent(dateTo)}` : '');

  const incomeQ = useQuery({
    queryKey: ['finance-stmt-income', projectId, currency, dateFrom, dateTo],
    queryFn: () =>
      apiGet<IncomeStatement>(`/v1/finance/gaap/statements/income?${scope}${period}`),
    enabled: statement === 'income',
  });
  const balanceQ = useQuery({
    queryKey: ['finance-stmt-balance', projectId, currency, dateTo],
    queryFn: () => {
      const qs = dateTo ? `&as_of=${encodeURIComponent(dateTo)}` : '';
      return apiGet<BalanceSheet>(`/v1/finance/gaap/statements/balance-sheet?${scope}${qs}`);
    },
    enabled: statement === 'balance',
  });
  const cashFlowQ = useQuery({
    queryKey: ['finance-stmt-cashflow', projectId, currency, dateFrom, dateTo],
    queryFn: () =>
      apiGet<CashFlow>(`/v1/finance/gaap/statements/cash-flow?${scope}${period}`),
    enabled: statement === 'cashflow',
  });
  const trialQ = useQuery({
    queryKey: ['finance-stmt-trial', projectId, currency, dateFrom, dateTo],
    queryFn: () =>
      apiGet<TrialBalance>(`/v1/finance/gaap/trial-balance?${scope}${period}`),
    enabled: statement === 'trial',
  });

  return (
    <div className="space-y-4">
      {/* Intro */}
      <div className="rounded-lg border border-oe-blue/15 bg-oe-blue/[0.03] p-3">
        <p className="text-sm text-content-secondary">
          {t('finance.stmt_subtitle', {
            defaultValue:
              'Accountant-facing GAAP statements derived live from the general ledger: income statement, balance sheet, cash flow and trial balance. Pick a period and currency; the balance sheet and trial balance are taken as of the end date.',
          })}
        </p>
      </div>

      {/* Controls: segmented statement switch + period + currency */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div
          role="group"
          aria-label={t('finance.stmt_switch_aria', { defaultValue: 'Choose a financial statement' })}
          className="inline-flex flex-wrap gap-1 rounded-lg border border-border bg-surface-secondary p-0.5"
        >
          {SEGMENTS.map((seg) => (
            <button
              key={seg.key}
              type="button"
              aria-pressed={statement === seg.key}
              onClick={() => setStatement(seg.key)}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                statement === seg.key
                  ? 'bg-surface-primary text-content-primary shadow-xs'
                  : 'text-content-secondary hover:text-content-primary',
              )}
            >
              {seg.icon}
              {t(seg.labelKey, { defaultValue: seg.label })}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('finance.stmt_period_from', { defaultValue: 'From' })}
            </span>
            <input
              type="date"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(e) => setDateFrom(e.target.value)}
              disabled={statement === 'balance'}
              className={clsx(inputCls, statement === 'balance' && 'opacity-50')}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {statement === 'balance'
                ? t('finance.stmt_as_of', { defaultValue: 'As of' })
                : t('finance.stmt_period_to', { defaultValue: 'To' })}
            </span>
            <input
              type="date"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(e) => setDateTo(e.target.value)}
              className={inputCls}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('finance.stmt_currency', { defaultValue: 'Currency' })}
            </span>
            <select
              value={currency}
              onChange={(e) => setCurrencyOverride(e.target.value)}
              className={clsx(inputCls, 'w-28')}
            >
              {currencyChoices.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {/* Active statement */}
      {statement === 'income' && (
        <StatementFrame
          loading={!incomeQ.data && !incomeQ.isError}
          isError={incomeQ.isError}
          error={incomeQ.error}
          empty={
            !!incomeQ.data &&
            incomeQ.data.revenue_lines.length === 0 &&
            incomeQ.data.expense_lines.length === 0 &&
            isZeroAmount(incomeQ.data.net_income)
          }
          onRetry={() => incomeQ.refetch()}
        >
          {incomeQ.data && <IncomeStatementView data={incomeQ.data} currency={currency} />}
        </StatementFrame>
      )}

      {statement === 'balance' && (
        <StatementFrame
          loading={!balanceQ.data && !balanceQ.isError}
          isError={balanceQ.isError}
          error={balanceQ.error}
          empty={
            !!balanceQ.data &&
            balanceQ.data.asset_lines.length === 0 &&
            balanceQ.data.liability_lines.length === 0 &&
            balanceQ.data.equity_lines.length === 0
          }
          onRetry={() => balanceQ.refetch()}
        >
          {balanceQ.data && <BalanceSheetView data={balanceQ.data} currency={currency} />}
        </StatementFrame>
      )}

      {statement === 'cashflow' && (
        <StatementFrame
          loading={!cashFlowQ.data && !cashFlowQ.isError}
          isError={cashFlowQ.isError}
          error={cashFlowQ.error}
          empty={
            !!cashFlowQ.data &&
            isZeroAmount(cashFlowQ.data.operating) &&
            isZeroAmount(cashFlowQ.data.investing) &&
            isZeroAmount(cashFlowQ.data.financing) &&
            isZeroAmount(cashFlowQ.data.opening_cash) &&
            isZeroAmount(cashFlowQ.data.closing_cash) &&
            isZeroAmount(cashFlowQ.data.net_change)
          }
          onRetry={() => cashFlowQ.refetch()}
        >
          {cashFlowQ.data && <CashFlowView data={cashFlowQ.data} currency={currency} />}
        </StatementFrame>
      )}

      {statement === 'trial' && (
        <StatementFrame
          loading={!trialQ.data && !trialQ.isError}
          isError={trialQ.isError}
          error={trialQ.error}
          empty={!!trialQ.data && trialQ.data.rows.length === 0}
          onRetry={() => trialQ.refetch()}
        >
          {trialQ.data && <TrialBalanceView data={trialQ.data} currency={currency} />}
        </StatementFrame>
      )}
    </div>
  );
}
