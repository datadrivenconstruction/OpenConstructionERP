// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shared helpers for the R6 Property-Dev dashboards.
 *
 * Centralises the status palette, loading/empty primitives, and small
 * formatting helpers used across all six dashboards.
 */

import { Loader2, Inbox, AlertOctagon, RefreshCw } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui/Button';
import { Skeleton, SkeletonText } from '@/shared/ui/Skeleton';
import type { PlotStatus } from '../api';
import { getNumberLocale } from '@/stores/usePreferencesStore';

export const PLOT_STATUS_FILL: Record<string, string> = {
  planned: '#94a3b8',
  under_construction: '#f59e0b',
  ready: '#10b981',
  reserved: '#3b82f6',
  under_contract: '#0ea5e9',
  sold: '#8b5cf6',
  handed_over: '#6366f1',
  maintenance: '#f43f5e',
};

export const PLOT_STATUS_STROKE: Record<string, string> = {
  planned: '#64748b',
  under_construction: '#d97706',
  ready: '#059669',
  reserved: '#2563eb',
  under_contract: '#0284c7',
  sold: '#7c3aed',
  handed_over: '#4f46e5',
  maintenance: '#e11d48',
};

export const ALL_PLOT_STATUSES: PlotStatus[] = [
  'planned',
  'under_construction',
  'ready',
  'reserved',
  'sold',
  'handed_over',
];

export function DashboardLoading({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center justify-center gap-2 py-12 text-sm text-content-tertiary"
    >
      <Loader2 size={16} className="animate-spin" />
      <span>{label ?? t('common.loading', { defaultValue: 'Loading…' })}</span>
    </div>
  );
}

/**
 * Shape-matched skeleton for dashboard widgets — header line + body of
 * bars/blocks that mimic the eventual chart shape. Beats a centered
 * spinner because the layout doesn't shift when data lands.
 *
 * `variant` picks between bars (heatmap / funnel / velocity / ageing),
 * timeline (journey), and cards (KPI rows).
 */
export type DashboardSkeletonVariant = 'bars' | 'timeline' | 'cards';

export function DashboardSkeleton({
  variant = 'bars',
  rows = 5,
}: {
  variant?: DashboardSkeletonVariant;
  rows?: number;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={t('propdev.loading_dashboard', { defaultValue: 'Loading dashboard' })}
      data-testid="dashboard-skeleton"
      className="space-y-3 py-2"
    >
      {/* Header line */}
      <div className="space-y-2">
        <Skeleton height={14} className="w-1/3" />
        <Skeleton height={10} className="w-1/2" />
      </div>
      {/* Body */}
      {variant === 'bars' && (
        <div className="space-y-2 pt-2">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="flex items-center gap-2">
              <Skeleton height={12} className="w-24" />
              <Skeleton
                height={24}
                className={i % 2 === 0 ? 'flex-1' : 'flex-1 opacity-60'}
              />
            </div>
          ))}
        </div>
      )}
      {variant === 'timeline' && (
        <div className="space-y-2.5 border-l-2 border-border-light pl-4 pt-2">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="space-y-1">
              <Skeleton height={12} className="w-2/3" />
              <Skeleton height={10} className="w-1/3" />
            </div>
          ))}
        </div>
      )}
      {variant === 'cards' && (
        <div className="grid grid-cols-2 gap-2 pt-2">
          {Array.from({ length: rows }).map((_, i) => (
            <Skeleton key={i} height={56} />
          ))}
        </div>
      )}
    </div>
  );
}

export function DashboardEmpty({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-2 py-12 text-center"
      data-testid="dashboard-empty"
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-secondary">
        {icon ?? <Inbox size={18} className="text-content-tertiary" />}
      </div>
      <h4 className="text-sm font-semibold text-content-primary">{title}</h4>
      {description && (
        <p className="text-xs text-content-tertiary max-w-md">{description}</p>
      )}
      {action}
    </div>
  );
}

/**
 * Dashboard-scoped error fallback — replaces the previous "DashboardEmpty
 * with red icon" pattern. Surfaces the original error message plus a
 * Retry button wired straight to a `refetch` callback so a transient 5xx
 * never wedges the widget.
 *
 * Use whenever a dashboard fetches over the network. For 401/403 the
 * caller should set `kind="forbidden"` so the description swaps to a
 * "contact your project admin" sentence instead of leaking the raw API
 * error text.
 */
export function DashboardError({
  message,
  onRetry,
  title,
  kind = 'generic',
}: {
  message?: string;
  onRetry?: () => void;
  title?: string;
  kind?: 'generic' | 'forbidden' | 'not_found';
}) {
  const { t } = useTranslation();

  const resolvedTitle =
    title ??
    (kind === 'forbidden'
      ? t('common.access_denied', { defaultValue: "You don't have access" })
      : kind === 'not_found'
        ? t('common.not_found', { defaultValue: 'Not found' })
        : t('propdev.dashboards.error_title', {
            defaultValue: 'Could not load this view',
          }));

  const resolvedMessage =
    kind === 'forbidden'
      ? t('common.access_denied_desc', {
          defaultValue:
            "You don't have access to this data - contact your project admin.",
        })
      : (message ??
        t('common.unknown_error', { defaultValue: 'An unknown error occurred.' }));

  return (
    <div
      className="flex flex-col items-center justify-center gap-2 py-10 text-center"
      role="alert"
      data-testid="dashboard-error"
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-error/10 text-semantic-error">
        <AlertOctagon size={18} />
      </div>
      <h4 className="text-sm font-semibold text-content-primary">{resolvedTitle}</h4>
      <p className="text-xs text-content-tertiary max-w-md">{resolvedMessage}</p>
      {onRetry && kind !== 'forbidden' && (
        <Button
          variant="secondary"
          size="sm"
          icon={<RefreshCw size={12} />}
          onClick={onRetry}
          data-testid="dashboard-error-retry"
        >
          {t('common.retry', { defaultValue: 'Retry' })}
        </Button>
      )}
    </div>
  );
}

/** Re-export SkeletonText so widgets can compose a single-line placeholder
 *  without reaching into shared/ui directly (keeps the dashboard layer
 *  self-contained for downstream skeletons). */
export { SkeletonText };

export function StatusLegend() {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-wrap items-center gap-3 px-3 py-2 text-2xs text-content-tertiary"
      aria-label={t('propdev.dashboards.status_legend', {
        defaultValue: 'Status legend',
      })}
    >
      {ALL_PLOT_STATUSES.map((s) => (
        <div key={s} className="flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-3 rounded-sm"
            style={{ backgroundColor: PLOT_STATUS_FILL[s] }}
            aria-hidden="true"
          />
          <span>
            {t(`propdev.status.${s}`, {
              defaultValue: s.replace(/_/g, ' '),
            })}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Format a numeric value to compact notation (1.2M / 540K). */
export function fmtCompactNumber(value: number, locale = getNumberLocale()): string {
  if (!Number.isFinite(value)) return '0';
  const abs = Math.abs(value);
  if (abs >= 1_000_000)
    return `${(value / 1_000_000).toLocaleString(locale, { maximumFractionDigits: 2 })}M`;
  if (abs >= 1_000)
    return `${(value / 1_000).toLocaleString(locale, { maximumFractionDigits: 1 })}K`;
  return value.toLocaleString(locale, { maximumFractionDigits: 0 });
}

/** Convert a `Decimal` / `string` / `number` payload field to JS number. */
export function num(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  if (typeof v === 'number') return Number.isFinite(v) ? v : 0;
  const parsed = Number(v);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** Sum a list of CurrencyAmount entries into a {currency: number} map. */
export function sumByCurrency(
  rows: { currency: string; amount: number | string }[],
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of rows) {
    out[r.currency] = (out[r.currency] ?? 0) + num(r.amount);
  }
  return out;
}

/** Quartile bucket (0..3) for a numeric drop-off percentage. */
export function dropQuartile(pct: number): 0 | 1 | 2 | 3 {
  if (pct < 25) return 0;
  if (pct < 50) return 1;
  if (pct < 75) return 2;
  return 3;
}
