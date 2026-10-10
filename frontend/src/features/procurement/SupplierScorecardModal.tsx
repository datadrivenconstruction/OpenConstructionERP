// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SupplierScorecardModal - trailing-window supplier KPI dialog (Wave 2 / T4).
//
// Opens from the supplier name in any PO row and surfaces three KPI tiles
// (on-time delivery %, qty variance %, GR rejection rate) plus the
// trailing-12-month PO summary. The data comes from
// GET /v1/procurement/suppliers/{contact_id}/scorecard.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Loader2, TrendingUp, AlertTriangle, Truck } from 'lucide-react';
import { WideModal, Badge, EmptyState } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { getSupplierScorecard } from './api';
import { fmtPercent } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

interface SupplierScorecardModalProps {
  open: boolean;
  onClose: () => void;
  contactId: string;
  contactName?: string | null;
  projectId?: string;
}

type TileTone = 'success' | 'warning' | 'error' | 'neutral';

type QualificationState = 'expired' | 'expiring' | 'valid' | 'not_stated';

const QUALIFICATION_TONE: Record<QualificationState, 'error' | 'warning' | 'success' | 'neutral'> = {
  expired: 'error',
  expiring: 'warning',
  valid: 'success',
  not_stated: 'neutral',
};

function qualificationLabel(
  state: QualificationState,
  until: string | null | undefined,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  switch (state) {
    case 'expired':
      return t('procurement.qualification_expired', { defaultValue: 'Expired on {{date}}', date: until ?? '' });
    case 'expiring':
      return t('procurement.qualification_expiring', { defaultValue: 'Ends on {{date}}', date: until ?? '' });
    case 'valid':
      return t('procurement.qualification_valid', { defaultValue: 'Valid until {{date}}', date: until ?? '' });
    default:
      return t('procurement.qualification_not_stated', { defaultValue: 'No end date recorded' });
  }
}

function pctTone(
  value: number,
  thresholds: { good: number; warn: number },
  invert = false,
): TileTone {
  // Default: higher = better. `invert` flips so higher = worse
  // (rejection / variance).
  const v = value;
  if (invert) {
    if (v <= thresholds.good) return 'success';
    if (v <= thresholds.warn) return 'warning';
    return 'error';
  }
  if (v >= thresholds.good) return 'success';
  if (v >= thresholds.warn) return 'warning';
  return 'error';
}

const TONE_BG: Record<TileTone, string> = {
  success: 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-900',
  warning: 'bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-900',
  error: 'bg-rose-50 dark:bg-rose-950/20 border-rose-200 dark:border-rose-900',
  neutral: 'bg-surface-secondary border-border',
};

const TONE_TEXT: Record<TileTone, string> = {
  success: 'text-emerald-700 dark:text-emerald-400',
  warning: 'text-amber-700 dark:text-amber-400',
  error: 'text-rose-700 dark:text-rose-400',
  neutral: 'text-content-primary',
};

function formatPct(value: number): string {
  return fmtPercent(value * 100);
}

/**
 * Decide how the on-time-delivery KPI tile should render.
 *
 * The backend's on-time denominator excludes deliveries whose PO had no
 * delivery_date (counted as ``unscheduled``). When there is no schedulable
 * delivery at all, ``on_time_delivery_pct`` is 0.0 by construction - showing
 * that as a red "0.0%" risk tile is misleading, because the supplier may have
 * a perfect record and simply nothing to measure against. This collapses the
 * three signals (total GRs, unscheduled, on-time) into a small descriptor the
 * component maps to translated strings.
 *
 * Pure + side-effect free so it can be unit-tested without React Query.
 */
export function onTimeTileModel(input: {
  total_gr_count: number;
  unscheduled_count: number;
  on_time_count: number;
  on_time_delivery_pct: number;
}): {
  kind: 'measured' | 'unscheduled_only' | 'no_deliveries';
  tone: TileTone;
  scheduled: number;
} {
  const scheduled = input.total_gr_count - input.unscheduled_count;
  if (scheduled > 0) {
    return {
      kind: 'measured',
      tone: pctTone(input.on_time_delivery_pct, { good: 0.9, warn: 0.75 }),
      scheduled,
    };
  }
  // No schedulable delivery: distinguish "had unscheduled deliveries" from
  // "had no deliveries at all" so the tile can say which.
  return {
    kind: input.unscheduled_count > 0 ? 'unscheduled_only' : 'no_deliveries',
    tone: 'neutral',
    scheduled: 0,
  };
}

export function SupplierScorecardModal({
  open,
  onClose,
  contactId,
  contactName,
  projectId,
}: SupplierScorecardModalProps) {
  const { t } = useTranslation();

  const {
    data: scorecard,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['procurement-scorecard', contactId, projectId ?? null],
    queryFn: () => getSupplierScorecard(contactId, { projectId }),
    enabled: open && Boolean(contactId),
  });

  const title =
    contactName ||
    scorecard?.supplier_name ||
    t('procurement.scorecard_title', { defaultValue: 'Supplier scorecard' });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={title}
      subtitle={t('procurement.scorecard_subtitle', {
        defaultValue: 'Trailing {{days}}-day performance',
        days: scorecard?.period_days ?? 365,
      })}
      size="lg"
    >
      {isLoading && (
        <div className="flex items-center justify-center py-12 text-content-tertiary">
          <Loader2 size={20} className="animate-spin mr-2" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      )}

      {isError && !isLoading && (
        <EmptyState
          icon={<AlertTriangle size={24} strokeWidth={1.5} />}
          title={t('common.error', { defaultValue: 'Error' })}
          description={t('procurement.scorecard_load_error', {
            defaultValue: 'Failed to load supplier scorecard.',
          })}
        />
      )}

      {scorecard && !isLoading && (
        <div className="space-y-6">
          {/* ── Summary row ────────────────────────────────────────────── */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <SummaryStat
              label={t('procurement.scorecard_total_pos', {
                defaultValue: 'Purchase orders',
              })}
              value={scorecard.total_po_count.toLocaleString(getNumberLocale())}
            />
            <SummaryStat
              label={t('procurement.scorecard_total_grs', {
                defaultValue: 'Goods receipts',
              })}
              value={scorecard.total_gr_count.toLocaleString(getNumberLocale())}
            />
            <SummaryStat
              label={t('procurement.scorecard_total_value', {
                defaultValue: 'Total PO value',
              })}
              value={
                scorecard.currency ? (
                  <MoneyDisplay
                    amount={scorecard.total_po_value}
                    currency={scorecard.currency}
                  />
                ) : (
                  scorecard.total_po_value
                )
              }
            />
          </div>

          {/* ── KPI tiles ──────────────────────────────────────────────── */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {(() => {
              const onTime = onTimeTileModel(scorecard);
              const label = t('procurement.scorecard_on_time', {
                defaultValue: 'On-time delivery',
              });
              if (onTime.kind === 'measured') {
                return (
                  <KpiTile
                    icon={<Truck size={18} />}
                    label={label}
                    value={formatPct(scorecard.on_time_delivery_pct)}
                    tone={onTime.tone}
                    detail={t('procurement.scorecard_on_time_detail', {
                      defaultValue: '{{onTime}} of {{scheduled}} on time',
                      onTime: scorecard.on_time_count,
                      scheduled: onTime.scheduled,
                    })}
                  />
                );
              }
              return (
                <KpiTile
                  icon={<Truck size={18} />}
                  label={label}
                  value={t('procurement.scorecard_on_time_na', {
                    defaultValue: 'Not scheduled',
                  })}
                  tone={onTime.tone}
                  detail={
                    onTime.kind === 'unscheduled_only'
                      ? t('procurement.scorecard_on_time_unscheduled', {
                          defaultValue:
                            '{{count}} delivery with no scheduled date',
                          defaultValue_plural:
                            '{{count}} deliveries with no scheduled date',
                          count: scorecard.unscheduled_count,
                        })
                      : t('procurement.scorecard_on_time_no_gr', {
                          defaultValue: 'No deliveries yet',
                        })
                  }
                />
              );
            })()}
            <KpiTile
              icon={<TrendingUp size={18} />}
              label={t('procurement.scorecard_qty_variance', {
                defaultValue: 'Qty variance',
              })}
              value={formatPct(scorecard.qty_variance_pct)}
              tone={pctTone(
                scorecard.qty_variance_pct,
                { good: 0.05, warn: 0.15 },
                true,
              )}
            />
            <KpiTile
              icon={<AlertTriangle size={18} />}
              label={t('procurement.scorecard_rejection', {
                defaultValue: 'GR rejection',
              })}
              value={formatPct(scorecard.gr_rejection_rate)}
              tone={pctTone(
                scorecard.gr_rejection_rate,
                { good: 0.02, warn: 0.1 },
                true,
              )}
            />
          </div>

          {/* ── Still qualified to buy from? ───────────────────────────── */}
          {scorecard.total_po_count > 0 && (
            <div className="space-y-1 rounded-lg border border-border-light px-4 py-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-content-secondary">
                  {t('procurement.scorecard_qualification', { defaultValue: 'Qualification' })}
                </span>
                <Badge variant={QUALIFICATION_TONE[scorecard.qualification_state ?? 'not_stated']}>
                  {qualificationLabel(scorecard.qualification_state ?? 'not_stated', scorecard.qualified_until, t)}
                </Badge>
              </div>
              {(scorecard.compliance_reasons?.length ?? 0) > 0 && (
                <p className="text-semantic-warning">
                  {t('procurement.scorecard_compliance_issues', {
                    defaultValue: 'Open compliance issues on the subcontractor record: {{count}}',
                    count: scorecard.compliance_reasons!.length,
                  })}
                </p>
              )}
              {(scorecard.unconfirmed_po_count ?? 0) > 0 && (
                <p className="text-content-secondary">
                  {t('procurement.scorecard_unconfirmed_orders', {
                    defaultValue: 'Issued orders not yet confirmed by the supplier: {{count}}',
                    count: scorecard.unconfirmed_po_count,
                  })}
                </p>
              )}
            </div>
          )}

          {/* ── Empty-state hint when there is no data ─────────────────── */}
          {scorecard.total_po_count === 0 && (
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-6 text-center text-sm text-content-tertiary">
              {t('procurement.scorecard_empty', {
                defaultValue:
                  'No purchase orders for this supplier in the trailing window yet.',
              })}
            </div>
          )}
        </div>
      )}
    </WideModal>
  );
}

/* ── Small subcomponents ───────────────────────────────────────────────── */

function SummaryStat({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface-primary px-4 py-3">
      <div className="text-2xs uppercase tracking-wider font-medium text-content-tertiary">
        {label}
      </div>
      <div className="mt-1 text-base font-semibold tabular-nums text-content-primary">
        {value}
      </div>
    </div>
  );
}

function KpiTile({
  icon,
  label,
  value,
  tone,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone: TileTone;
  /** Optional supporting line shown under the headline value (e.g. the
   *  on-time numerator/denominator, or why a figure is not measurable). */
  detail?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className={`rounded-lg border px-4 py-4 ${TONE_BG[tone]}`}>
      <div className="flex items-center justify-between">
        <div className={`flex items-center gap-2 text-xs font-medium ${TONE_TEXT[tone]}`}>
          {icon}
          <span>{label}</span>
        </div>
        <Badge
          variant={
            tone === 'success'
              ? 'success'
              : tone === 'warning'
                ? 'warning'
                : tone === 'error'
                  ? 'error'
                  : 'neutral'
          }
          size="sm"
        >
          {tone === 'success'
            ? t('procurement.scorecard_tone_good', { defaultValue: 'good' })
            : tone === 'warning'
              ? t('procurement.scorecard_tone_warn', { defaultValue: 'warn' })
              : tone === 'error'
                ? t('procurement.scorecard_tone_risk', { defaultValue: 'risk' })
                : '-'}
        </Badge>
      </div>
      <div className={`mt-2 text-2xl font-bold tabular-nums ${TONE_TEXT[tone]}`}>
        {value}
      </div>
      {detail && (
        <div className="mt-1 text-2xs text-content-tertiary">{detail}</div>
      )}
    </div>
  );
}
