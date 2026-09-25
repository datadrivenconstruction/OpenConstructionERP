// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ContractExposurePanel - surfaces the 5D cost model's contract-exposure
// endpoint (GET /costmodel/projects/{id}/5d/contract-exposure/). For every cost
// group it shows how much of the budget is already committed to contracts
// (subcontracts, purchase orders, awarded values), how much is still free to
// commit, the commitment ratio, and whether the group is overcommitted; the
// per-group rows roll up into a project-level headline.
//
// Money note: budgeted / committed / remaining arrive as Decimal-encoded
// STRINGS. We format them with the shared locale-aware ``fmtCurrency`` and
// never coerce them to a number for anything but display / bar geometry. When
// the budget lines span more than one currency the backend sets
// ``mixed_currency`` and the summed totals may have been blended across a
// missing fx rate, so we surface an informational banner.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Wallet, AlertTriangle, Inbox } from 'lucide-react';

import { Card, Skeleton, EmptyState, Badge } from '@/shared/ui';
import { fmtCurrency, fmtPercent, fmtFixed } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { costModelApi, type ContractExposureGroup } from './api';

export interface ContractExposurePanelProps {
  projectId: string;
  /** Project currency, used as a fallback when the rollup omits one. */
  currency?: string;
}

/** committed/budget fraction -> whole percent, or null when undefined. */
function ratioToPct(ratio: number | null | undefined): number | null {
  if (ratio == null || !Number.isFinite(ratio)) return null;
  return ratio * 100;
}

/** Tailwind text colour for a commitment-ratio percent. */
function ratioColor(pct: number | null): string {
  if (pct == null) return 'text-content-tertiary';
  if (pct > 100) return 'text-semantic-error';
  if (pct >= 90) return 'text-amber-600';
  return 'text-content-secondary';
}

/** Tailwind fill colour for the commitment-ratio bar. */
function ratioBar(pct: number | null): string {
  if (pct == null) return 'bg-surface-secondary';
  if (pct > 100) return 'bg-semantic-error';
  if (pct >= 90) return 'bg-amber-500';
  return 'bg-oe-blue';
}

/**
 * Committed-vs-budget contract-exposure card for the 5D Cost Model page.
 */
export function ContractExposurePanel({ projectId, currency }: ContractExposurePanelProps) {
  const { t } = useTranslation();

  const { data, isLoading, error } = useQuery({
    queryKey: ['costmodel', 'contract-exposure', projectId],
    queryFn: () => costModelApi.getContractExposure(projectId),
    retry: false,
  });

  const resolvedCurrency = data?.currency || currency || 'EUR';

  // Reuse the Budget-by-Category labels so a cost group reads the same in both
  // surfaces; an unknown group falls back to its raw key.
  const categoryLabels = useMemo<Record<string, string>>(
    () => ({
      material: t('costmodel.cat_material', { defaultValue: 'Material' }),
      labor: t('costmodel.cat_labor', { defaultValue: 'Labor' }),
      equipment: t('costmodel.cat_equipment', { defaultValue: 'Equipment' }),
      subcontractor: t('costmodel.cat_subcontractor', { defaultValue: 'Subcontractor' }),
      overhead: t('costmodel.cat_overhead', { defaultValue: 'Overhead' }),
      contingency: t('costmodel.cat_contingency', { defaultValue: 'Contingency' }),
      // Committed documents on cost lines without a budget line arrive under
      // the empty key, next to budget lines that carry no category.
      '': t('boq.uncategorized', { defaultValue: '(Not specified)' }),
    }),
    [t],
  );

  const labelFor = (group: string): string => categoryLabels[group] || group;

  /* ── Status badge for a single group ─────────────────────────────────────── */

  const renderStatus = (g: ContractExposureGroup, pct: number | null) => {
    if (g.overcommitted) {
      return (
        <Badge variant="error" size="sm">
          {t('costmodel.exposure_status_overcommitted', { defaultValue: 'Over budget' })}
        </Badge>
      );
    }
    if (pct != null && pct >= 100) {
      return (
        <Badge variant="warning" size="sm">
          {t('costmodel.exposure_status_full', { defaultValue: 'Fully committed' })}
        </Badge>
      );
    }
    return (
      <Badge variant="neutral" size="sm">
        {t('costmodel.exposure_status_ok', { defaultValue: 'Within budget' })}
      </Badge>
    );
  };

  /* ── Loading / error ─────────────────────────────────────────────────────── */

  if (isLoading) {
    return (
      <Card>
        <div className="space-y-3">
          <Skeleton height={32} className="w-1/3" rounded="md" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} height={72} className="w-full" rounded="lg" />
            ))}
          </div>
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={40} className="w-full" rounded="md" />
          ))}
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <div className="flex items-start gap-3 rounded-lg border border-semantic-error/30 bg-semantic-error-bg/30 p-3">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-semantic-error" />
          <div>
            <p className="text-sm font-medium text-content-primary">
              {t('costmodel.exposure_load_failed', { defaultValue: 'Could not load contract exposure' })}
            </p>
            <p className="mt-0.5 text-xs text-content-tertiary">{getErrorMessage(error)}</p>
          </div>
        </div>
      </Card>
    );
  }

  const groups = data?.groups ?? [];
  const totalPct = ratioToPct(data?.total_commitment_ratio ?? null);
  const remainingNegative = Number(data?.total_remaining_to_commit ?? 0) < 0;

  /* ── Render ──────────────────────────────────────────────────────────────── */

  return (
    <Card padding="none">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-light px-5 py-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
            <Wallet size={16} />
          </div>
          <div>
            <h3 className="text-base font-semibold text-content-primary">
              {t('costmodel.exposure_title', { defaultValue: 'Contract Exposure' })}
            </h3>
            <p className="text-xs text-content-tertiary">
              {t('costmodel.exposure_subtitle', {
                defaultValue: 'Committed to contracts vs budget, by cost group.',
              })}
            </p>
          </div>
        </div>
        {data && (data.overcommitted || data.overcommitted_group_count > 0) && (
          <Badge variant="error" size="sm">
            {t('costmodel.exposure_overcommitted_badge', { defaultValue: 'Overcommitted' })}
          </Badge>
        )}
      </div>

      {/* Mixed-currency banner */}
      {data?.mixed_currency && (
        <div
          role="alert"
          className="flex items-start gap-2 border-b border-amber-200 bg-amber-50/70 px-5 py-2.5 dark:border-amber-800/50 dark:bg-amber-950/20"
        >
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
          <p className="text-xs text-amber-800 dark:text-amber-300">
            {t('costmodel.exposure_mixed_currency', {
              defaultValue:
                'Budget lines span more than one currency, so the summed totals may have been blended across a missing exchange rate. Compare groups within the same currency.',
            })}
          </p>
        </div>
      )}

      {groups.length === 0 ? (
        <div className="p-6">
          <EmptyState
            icon={<Inbox size={28} strokeWidth={1.5} />}
            title={t('costmodel.exposure_empty_title', { defaultValue: 'No commitments to show yet' })}
            description={t('costmodel.exposure_empty_desc', {
              defaultValue:
                'Generate a budget from your BOQ, then record committed values (subcontracts, purchase orders, awarded contracts) to see how much of each cost group is committed against budget.',
            })}
          />
        </div>
      ) : (
        <div className="space-y-5 p-5">
          {/* Headline KPIs */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs">
              <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                {t('costmodel.exposure_total_budgeted', { defaultValue: 'Budgeted' })}
              </div>
              <div className="text-xl font-bold tabular-nums text-content-primary">
                {fmtCurrency(data?.total_budgeted, resolvedCurrency)}
              </div>
            </div>
            <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs">
              <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                {t('costmodel.exposure_total_committed', { defaultValue: 'Committed' })}
              </div>
              <div className="text-xl font-bold tabular-nums text-content-primary">
                {fmtCurrency(data?.total_committed, resolvedCurrency)}
              </div>
              {totalPct != null && (
                <div className={`mt-1 text-2xs font-medium ${ratioColor(totalPct)}`}>
                  {t('costmodel.exposure_committed_of_budget', {
                    defaultValue: '{{pct}}% of budget committed',
                    pct: fmtFixed(totalPct, 0),
                  })}
                </div>
              )}
            </div>
            <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs">
              <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                {t('costmodel.exposure_remaining_to_commit', { defaultValue: 'Remaining to commit' })}
              </div>
              <div
                className={`text-xl font-bold tabular-nums ${remainingNegative ? 'text-semantic-error' : 'text-content-primary'}`}
              >
                {fmtCurrency(data?.total_remaining_to_commit, resolvedCurrency)}
              </div>
            </div>
          </div>

          {/* Commitment-ratio bar */}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium text-content-secondary">
                {t('costmodel.exposure_commitment_ratio', { defaultValue: 'Commitment ratio' })}
              </span>
              <span className={`text-xs font-semibold tabular-nums ${ratioColor(totalPct)}`}>
                {totalPct == null
                  ? t('costmodel.exposure_ratio_na', { defaultValue: 'n/a' })
                  : fmtPercent(totalPct, 0)}
              </span>
            </div>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-secondary">
              <div
                className={`h-full rounded-full transition-all ${ratioBar(totalPct)}`}
                style={{ width: `${Math.max(0, Math.min(100, totalPct ?? 0))}%` }}
              />
            </div>
          </div>

          {/* Overcommit alert */}
          {data && (data.overcommitted || data.overcommitted_group_count > 0) && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-xl border border-semantic-error/30 bg-semantic-error-bg/40 p-3"
            >
              <AlertTriangle size={15} className="mt-0.5 shrink-0 text-semantic-error" />
              <p className="text-xs text-content-secondary">
                {t('costmodel.exposure_overcommitted_hint', {
                  defaultValue:
                    '{{count}} of {{total}} cost groups are committed above budget. Review the commitments or rebalance the budget.',
                  count: data.overcommitted_group_count,
                  total: groups.length,
                })}
              </p>
            </div>
          )}

          {/* Per-group breakdown */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b-2 border-border text-xs uppercase tracking-wider text-content-secondary">
                  <th scope="col" className="py-3 pr-4 text-left font-semibold">
                    {t('costmodel.exposure_col_group', { defaultValue: 'Cost group' })}
                  </th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">
                    {t('costmodel.exposure_col_budgeted', { defaultValue: 'Budgeted' })}
                  </th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">
                    {t('costmodel.exposure_col_committed', { defaultValue: 'Committed' })}
                  </th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">
                    {t('costmodel.exposure_col_remaining', { defaultValue: 'Remaining' })}
                  </th>
                  <th scope="col" className="px-2 py-3 text-center font-semibold" style={{ minWidth: 96 }}>
                    {t('costmodel.exposure_col_ratio', { defaultValue: 'Committed %' })}
                  </th>
                  <th scope="col" className="py-3 pl-4 text-right font-semibold">
                    {t('costmodel.exposure_col_status', { defaultValue: 'Status' })}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {groups.map((g) => {
                  const pct = ratioToPct(g.commitment_ratio);
                  const remNeg = Number(g.remaining_to_commit) < 0;
                  return (
                    <tr key={g.group} className="transition-colors hover:bg-surface-secondary/50">
                      <td className="py-3.5 pr-4 font-medium text-content-primary">
                        <span>{labelFor(g.group)}</span>
                        {g.group && categoryLabels[g.group] && g.group !== categoryLabels[g.group] && (
                          <span className="block text-2xs font-normal text-content-tertiary">{g.group}</span>
                        )}
                      </td>
                      <td className="py-3.5 px-4 text-right tabular-nums text-content-secondary">
                        {fmtCurrency(g.budgeted, resolvedCurrency)}
                      </td>
                      <td className="py-3.5 px-4 text-right tabular-nums text-content-secondary">
                        {fmtCurrency(g.committed, resolvedCurrency)}
                      </td>
                      <td
                        className={`py-3.5 px-4 text-right tabular-nums ${remNeg ? 'text-semantic-error' : 'text-content-secondary'}`}
                      >
                        {fmtCurrency(g.remaining_to_commit, resolvedCurrency)}
                      </td>
                      <td className="py-3.5 px-2">
                        <div className="flex flex-col items-center gap-0.5">
                          <span className={`text-2xs font-semibold tabular-nums ${ratioColor(pct)}`}>
                            {pct == null
                              ? t('costmodel.exposure_ratio_na', { defaultValue: 'n/a' })
                              : fmtPercent(pct, 0)}
                          </span>
                          <div className="h-1.5 w-full max-w-[64px] overflow-hidden rounded-full bg-surface-secondary">
                            <div
                              className={`h-full rounded-full ${ratioBar(pct)}`}
                              style={{ width: `${Math.max(0, Math.min(100, pct ?? 0))}%` }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="py-3.5 pl-4 text-right">{renderStatus(g, pct)}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-border font-semibold">
                  <td className="py-3.5 pr-4 text-content-primary">
                    {t('costmodel.exposure_total', { defaultValue: 'Project total' })}
                  </td>
                  <td className="py-3.5 px-4 text-right tabular-nums text-content-primary">
                    {fmtCurrency(data?.total_budgeted, resolvedCurrency)}
                  </td>
                  <td className="py-3.5 px-4 text-right tabular-nums text-content-primary">
                    {fmtCurrency(data?.total_committed, resolvedCurrency)}
                  </td>
                  <td
                    className={`py-3.5 px-4 text-right tabular-nums ${remainingNegative ? 'text-semantic-error' : 'text-content-primary'}`}
                  >
                    {fmtCurrency(data?.total_remaining_to_commit, resolvedCurrency)}
                  </td>
                  <td className="py-3.5 px-2 text-center">
                    <span className={`text-2xs font-bold tabular-nums ${ratioColor(totalPct)}`}>
                      {totalPct == null ? '-' : fmtPercent(totalPct, 0)}
                    </span>
                  </td>
                  <td className="py-3.5 pl-4" />
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
