// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How much of the bill's value sits on the cost structure: the allocated
// share, how many positions are split, and how many splits no longer add up.
// Next to it, the switch for the read-only cost allocation column.

import { useTranslation } from 'react-i18next';
import { GitFork, AlertTriangle, Columns3 } from 'lucide-react';

import { formatCurrency } from '@/shared/lib/money';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import type { AllocationCoverage } from '@/features/costmodel/structureApi';

export interface CostAllocationCoverageBarProps {
  coverage: AllocationCoverage;
  currency?: string;
  showColumn: boolean;
  onToggleColumn: () => void;
}

/** Share as a percentage clamped into [0, 100] for the bar width. */
function barWidth(sharePct: string): number {
  const n = Number(sharePct);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

/** The share with at most one decimal, in the user's number format. */
function shareLabel(sharePct: string): string {
  const n = Number(sharePct);
  return new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 1 }).format(Number.isFinite(n) ? n : 0);
}

export function CostAllocationCoverageBar({
  coverage,
  currency,
  showColumn,
  onToggleColumn,
}: CostAllocationCoverageBarProps) {
  const { t } = useTranslation();
  const width = barWidth(coverage.share_pct);
  const inSuspense = coverage.positions_in_suspense ?? 0;
  // Money on a cost line without an account is not on the structure, so the bar is
  // complete only when every position reaches a postable account.
  const complete =
    coverage.positions_total > 0 && coverage.positions_allocated === coverage.positions_total && inSuspense === 0;
  return (
    <div
      className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-border-light bg-surface-elevated px-3 py-1.5 text-xs"
      data-testid="cost-allocation-coverage"
    >
      <span className="font-medium text-content-secondary">
        {t('boq.cost_allocation.coverage_label', { defaultValue: 'On the cost structure' })}
      </span>
      <span className="flex items-center gap-2" title={t('boq.cost_allocation.coverage_tip', {
        defaultValue: '{{allocated}} of {{total}} allocated, {{unallocated}} still on no cost line.',
        allocated: formatCurrency(coverage.value_allocated, currency),
        total: formatCurrency(coverage.value_total, currency),
        unallocated: formatCurrency(coverage.value_unallocated, currency),
      })}>
        <span className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-secondary" aria-hidden="true">
          <span
            className={`block h-full rounded-full ${complete ? 'bg-semantic-success' : 'bg-amber-500'}`}
            style={{ width: `${width}%` }}
          />
        </span>
        <span className="font-semibold tabular-nums text-content-primary" data-testid="cost-allocation-share">
          {t('boq.cost_allocation.coverage_share', {
            defaultValue: '{{share}} % of the value',
            share: shareLabel(coverage.share_pct),
          })}
        </span>
      </span>
      <span className="flex items-center gap-1 text-content-secondary">
        <GitFork size={12} />
        {t('boq.cost_allocation.coverage_split', {
          defaultValue: 'Split positions: {{split}}',
          split: coverage.positions_split,
        })}
      </span>
      {inSuspense > 0 && (
        <span
          className="flex items-center gap-1 font-medium text-amber-700 dark:text-amber-300"
          data-testid="cost-allocation-suspense"
          title={t('boq.cost_allocation.coverage_suspense_tip', {
            defaultValue:
              'Positions on a cost line without an account: {{count}}. Their money is not on the cost structure until the cost line gets an account.',
            count: inSuspense,
          })}
        >
          <AlertTriangle size={12} />
          {t('boq.cost_allocation.coverage_suspense', {
            defaultValue: 'In suspense: {{amount}}',
            amount: formatCurrency(coverage.value_in_suspense ?? '0', currency),
          })}
        </span>
      )}
      {coverage.positions_invalid > 0 && (
        <span className="flex items-center gap-1 font-medium text-semantic-error">
          <AlertTriangle size={12} />
          {t('boq.cost_allocation.coverage_invalid', {
            defaultValue: 'Splits to fix: {{invalid}}',
            invalid: coverage.positions_invalid,
          })}
        </span>
      )}
      <button
        type="button"
        onClick={onToggleColumn}
        aria-pressed={showColumn}
        data-testid="cost-allocation-column-toggle"
        className={`ms-auto flex items-center gap-1 rounded-md px-2 py-0.5 font-medium transition-colors ${
          showColumn ? 'bg-oe-blue/10 text-oe-blue' : 'text-content-secondary hover:bg-surface-secondary'
        }`}
      >
        <Columns3 size={12} />
        {showColumn
          ? t('boq.cost_allocation.hide_column', { defaultValue: 'Hide allocation column' })
          : t('boq.cost_allocation.show_column', { defaultValue: 'Show allocation column' })}
      </button>
    </div>
  );
}

export interface CostAllocationCoverageErrorProps {
  onRetry: () => void;
}

/**
 * The coverage bar when the allocations could not be loaded. Without it the
 * bar and the allocation column would simply be missing, which reads as "no
 * position is costed" rather than "something failed".
 */
export function CostAllocationCoverageError({ onRetry }: CostAllocationCoverageErrorProps) {
  const { t } = useTranslation();
  return (
    <div
      className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-border-light bg-surface-elevated px-3 py-1.5 text-xs text-semantic-error"
      role="alert"
      data-testid="cost-allocation-coverage-error"
    >
      <span className="flex items-center gap-1">
        <AlertTriangle size={12} />
        {t('boq.cost_allocation.coverage_failed', {
          defaultValue: 'The cost allocation of this bill could not be loaded.',
        })}
      </span>
      <button type="button" onClick={onRetry} className="ms-auto font-medium text-oe-blue hover:underline">
        {t('common.retry', { defaultValue: 'Retry' })}
      </button>
    </div>
  );
}
