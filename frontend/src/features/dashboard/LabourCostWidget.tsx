// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Dashboard widget — cumulative field labour cost vs the labour budget.
 *
 * Sources:
 *   - live labour cost from the payroll rollup (`/v1/payroll/.../labour-cost/`),
 *     already in the project base currency,
 *   - the planned labour budget from the cost-model budget summary
 *     (`category === 'labor'`).
 *
 * Currency is the project base currency returned by the labour-cost endpoint -
 * never a hardcoded symbol, and the two figures are never blended across
 * currencies (both are already in base).
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchLabourCost } from '@/features/payroll/api';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { costModelApi } from '@/features/costmodel/api';
import { KpiStrip } from './KpiStrip';
import { fmtFixed } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

function money(value: number, currency?: string): string {
  if (!Number.isFinite(value)) return '-';
  try {
    return new Intl.NumberFormat(getNumberLocale(), {
      style: currency ? 'currency' : 'decimal',
      currency: currency || undefined,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return value.toFixed(0);
  }
}

export function LabourCostWidget() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  // The rollup is payroll data (payroll.read, manager and above). Below that
  // the widget hides rather than showing a spent-to-date of zero it never read.
  const canReadPayroll = useHasPermission('payroll.read');

  const labourQuery = useQuery({
    queryKey: ['payroll', 'labour-cost', projectId],
    queryFn: () => fetchLabourCost(projectId),
    enabled: Boolean(projectId) && canReadPayroll,
  });

  const budgetQuery = useQuery({
    queryKey: ['costmodel', 'budget-summary', projectId],
    queryFn: () => costModelApi.getBudgetSummary(projectId),
    enabled: Boolean(projectId) && canReadPayroll,
  });

  if (!projectId || !canReadPayroll) return null;

  const labour = labourQuery.data;
  const currency = labour?.currency || undefined;
  const spent = labour ? Number(labour.labour_cost) : 0;
  const labourBudget = (budgetQuery.data?.categories ?? []).find((c) => c.category === 'labor');
  const planned = labourBudget?.planned ?? 0;
  const pct = planned > 0 ? Math.min(100, Math.round((spent / planned) * 100)) : 0;
  // Uncapped share for the KPI cell so an over-budget project can read past
  // 100% (the progress bar below still clamps its width to `pct`).
  const usedPct = planned > 0 ? Math.round((spent / planned) * 100) : 0;
  const over = planned > 0 && spent > planned;

  return (
    <Card className="h-full">
      <CardHeader title={t('dashboard.labour_cost_title', { defaultValue: 'Labour cost vs budget' })} />
      <CardContent>
        <KpiStrip
          stats={[
            {
              label: t('dashboard.labour_spent', { defaultValue: 'Spent to date' }),
              value: money(spent, currency),
            },
            {
              label: t('dashboard.labour_budget', { defaultValue: 'Budget' }),
              value:
                planned > 0
                  ? money(planned, currency)
                  : t('dashboard.labour_no_budget', { defaultValue: 'Not set' }),
              tone: 'text-content-secondary',
            },
            {
              label: t('dashboard.labour_used', { defaultValue: 'Used' }),
              value: planned > 0 ? `${usedPct}%` : '-',
              tone: over ? 'text-rose-600' : 'text-content-secondary',
            },
          ]}
        />
        {planned > 0 && (
          <div className="mt-3">
            <div className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary">
              <div
                className={`h-full rounded-full ${over ? 'bg-rose-500' : 'bg-emerald-500'}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className={`mt-1 text-xs ${over ? 'text-rose-600' : 'text-content-tertiary'}`}>
              {over
                ? t('dashboard.labour_over', {
                    defaultValue: 'Over budget by {{amount}}',
                    amount: money(spent - planned, currency),
                  })
                : t('dashboard.labour_pct_used', { defaultValue: '{{pct}}% of budget used', pct })}
            </p>
          </div>
        )}
        {labour && Number(labour.total_hours) > 0 && (
          <p className="mt-2 text-xs text-content-tertiary">
            {t('dashboard.labour_hours', {
              defaultValue: 'over {{hours}} h logged',
              hours: fmtFixed(Number(labour.total_hours), 0),
            })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default LabourCostWidget;
