// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FinanceSummaryCard - at-a-glance money rollup for the dashboard.
 *
 * Surfaces figures the dashboard rollup ALREADY computes (no new fetch):
 *   - open change-order cost impact, per currency  (change_orders.by_currency)
 *   - budget-warning count + worst over-budget project  (budget_variance)
 *
 * The estimated BOQ value lives in the KPI ribbon (its "Total Value" tile);
 * we deliberately do NOT repeat that per-currency row here so the dashboard
 * shows each headline figure exactly once.
 *
 * Money is rendered through the shared decimal-safe helpers in
 * ``shared/lib/money.ts`` (the wire ships Decimals as strings; never call
 * ``.toFixed`` on a raw value or ``+`` two wire strings). Cross-currency
 * portfolios are shown as per-currency chips - we never blend ISO currencies
 * into one scalar.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, ArrowRight, FileEdit, Wallet } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { useDashboardRollupContext } from './context/DashboardRollupContext';

/** A per-currency money subtotal as it arrives on the rollup payload. */
interface CurrencyChip {
  currency: string;
  amount: number;
}

/** Render a list of per-currency amounts as compact chips (joined by ·). */
function MoneyChips({ chips, emptyLabel }: { chips: CurrencyChip[]; emptyLabel: string }) {
  if (chips.length === 0) {
    return <span className="text-content-tertiary">{emptyLabel}</span>;
  }
  return (
    <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      {chips.map((c, i) => (
        <span key={c.currency} className="tabular-nums">
          {formatCurrency(c.amount, c.currency, undefined, { maximumFractionDigits: 0 })}
          {i < chips.length - 1 && <span aria-hidden className="ml-2 text-content-quaternary">·</span>}
        </span>
      ))}
    </span>
  );
}

export function FinanceSummaryCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { byWidget, isLoading } = useDashboardRollupContext();

  const budget = byWidget('budget_variance');
  const changeOrders = byWidget('change_orders');

  // Open change-order impact chips (same per-currency treatment).
  const coChips = useMemo<CurrencyChip[]>(() => {
    const by = changeOrders?.by_currency;
    if (!by || by.length === 0) return [];
    return by
      .map((b) => ({ currency: b.currency || '', amount: toNum(b.total_impact) }))
      .filter((c) => c.amount !== 0 || c.currency);
  }, [changeOrders]);

  const overBudgetCount = budget?.over_budget_count ?? 0;
  const worstOverBudget = useMemo(() => {
    const rows = budget?.top_over ?? [];
    if (rows.length === 0) return null;
    // top_over is already sorted by variance desc on the backend.
    return rows[0] ?? null;
  }, [budget]);

  // While the shared rollup is still loading, show a light skeleton so the
  // card doesn't flash zeros on a cold dashboard.
  if (isLoading && !budget && !changeOrders) {
    return (
      <Card>
        <CardHeader title={t('dashboard.finance_summary', { defaultValue: 'Finance summary' })} />
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" aria-busy="true">
            {[0, 1].map((i) => (
              <div
                key={i}
                className="rounded-xl border border-border-light bg-surface-elevated/90 p-3"
              >
                <div className="h-3 w-20 rounded bg-surface-secondary animate-pulse" />
                <div className="mt-2 h-5 w-24 rounded bg-surface-secondary animate-pulse" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <Wallet size={16} className="text-oe-blue" strokeWidth={1.75} />
            {t('dashboard.finance_summary', { defaultValue: 'Finance summary' })}
          </span>
        }
        action={
          <button
            type="button"
            onClick={() => navigate('/finance')}
            className="inline-flex items-center gap-1 text-xs font-medium text-content-secondary hover:text-oe-blue transition-colors"
          >
            {t('dashboard.open_finance', { defaultValue: 'Open Finance' })}
            <ArrowRight size={13} />
          </button>
        }
      />
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {/* Open change-order impact */}
          <button
            type="button"
            onClick={() => navigate('/changeorders')}
            className="group rounded-xl border border-border-light bg-surface-elevated/90 p-3 text-left shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/30"
          >
            <div className="flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              <FileEdit size={12} className="text-violet-500" />
              {t('dashboard.finance_change_orders', { defaultValue: 'Open change orders' })}
            </div>
            <div className="mt-1 text-base font-bold text-content-primary">
              <MoneyChips
                chips={coChips}
                emptyLabel={t('dashboard.finance_no_change_orders', { defaultValue: 'None open' })}
              />
            </div>
            {(changeOrders?.open_count ?? 0) > 0 && (
              <div className="mt-0.5 text-2xs text-content-tertiary">
                {t('dashboard.finance_change_orders_count', {
                  defaultValue: '{{count}} pending',
                  count: changeOrders?.open_count ?? 0,
                })}
              </div>
            )}
          </button>

          {/* Budget warnings */}
          <button
            type="button"
            onClick={() =>
              worstOverBudget
                ? navigate(`/projects/${worstOverBudget.project_id}`)
                : navigate('/finance')
            }
            className={[
              'group rounded-xl border p-3 text-left shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/30',
              overBudgetCount > 0
                ? 'border-amber-300/60 bg-amber-50 dark:bg-amber-900/10'
                : 'border-border-light bg-surface-elevated/90',
            ].join(' ')}
          >
            <div className="flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              <AlertTriangle
                size={12}
                className={overBudgetCount > 0 ? 'text-amber-500' : 'text-content-quaternary'}
              />
              {t('dashboard.finance_budget_warnings', { defaultValue: 'Budget warnings' })}
            </div>
            <div
              className={[
                'mt-1 text-xl font-bold tabular-nums',
                overBudgetCount > 0 ? 'text-amber-600' : 'text-content-primary',
              ].join(' ')}
            >
              {overBudgetCount}
            </div>
            {worstOverBudget && (
              <div className="mt-0.5 truncate text-2xs text-content-tertiary">
                {t('dashboard.finance_worst_over', {
                  defaultValue: '{{name}} +{{pct}}%',
                  name: worstOverBudget.project_name,
                  pct: worstOverBudget.pct,
                })}
              </div>
            )}
          </button>
        </div>
      </CardContent>
    </Card>
  );
}

export default FinanceSummaryCard;
