// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How much of a plan generated from the bill is backed by data. The score and
// its reasons come from the server (schedule/plan_confidence.py); this file
// only reads and words them. Weights: docs/design/schedule_from_estimate.md.
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { AlertTriangle } from 'lucide-react';
import { fmtFixed } from '@/shared/lib/formatters';
import type { ActivityConfidence, ConfidenceBand } from './api';

const BANDS: readonly ConfidenceBand[] = ['high', 'medium', 'low'];

/** The confidence a generated activity carries, or null for anything else. */
export function activityConfidence(metadata: Record<string, unknown> | null | undefined): ActivityConfidence | null {
  const raw = metadata?.confidence;
  if (!raw || typeof raw !== 'object') return null;
  const c = raw as Partial<ActivityConfidence>;
  if (typeof c.score !== 'number' || !Number.isFinite(c.score)) return null;
  const band = BANDS.includes(c.band as ConfidenceBand) ? (c.band as ConfidenceBand) : confidenceBand(c.score);
  return {
    score: c.score,
    band,
    duration: typeof c.duration === 'number' ? c.duration : 0,
    logic: typeof c.logic === 'number' ? c.logic : 0,
    breakdown: typeof c.breakdown === 'number' ? c.breakdown : 0,
    reasons: Array.isArray(c.reasons) ? c.reasons.filter((r): r is string => typeof r === 'string') : [],
  };
}

/** Same thresholds as the server: high from 0.7, medium from 0.5. */
export function confidenceBand(score: number): ConfidenceBand {
  if (score >= 0.7 - 1e-9) return 'high';
  if (score >= 0.5 - 1e-9) return 'medium';
  return 'low';
}

/** Two decimals, with the reader's decimal separator ("0.66", "0,66"). */
export function formatScore(score: number): string {
  return fmtFixed(score, 2);
}

export function bandLabel(t: TFunction, band: ConfidenceBand): string {
  switch (band) {
    case 'high':
      return t('schedule.confidence_band_high', { defaultValue: 'high' });
    case 'medium':
      return t('schedule.confidence_band_medium', { defaultValue: 'medium' });
    default:
      return t('schedule.confidence_band_low', { defaultValue: 'low' });
  }
}

/** One reason code in words; unknown codes are dropped rather than shown raw. */
export function confidenceReasonText(t: TFunction, reason: string): string | null {
  switch (reason) {
    case 'duration_labor_hours':
      return t('schedule.confidence_reason_labor_hours', { defaultValue: 'Duration from the labour norm of the position' });
    case 'duration_resource_sum':
      return t('schedule.confidence_reason_resource_sum', { defaultValue: 'Duration from the labour hours in its resources' });
    case 'duration_machine_hours':
      return t('schedule.confidence_reason_machine_hours', { defaultValue: 'Duration set by the machine hours of the position' });
    case 'duration_spans_works':
      return t('schedule.confidence_reason_spans_works', { defaultValue: 'A lump sum that runs for the whole works' });
    case 'duration_estimated_fallback':
      return t('schedule.confidence_reason_estimated_fallback', { defaultValue: 'Duration guessed from the unit, no labour norm' });
    case 'duration_cost_proportional':
      return t('schedule.confidence_reason_cost_proportional', { defaultValue: 'Duration from its share of the cost, no quantity to go by' });
    case 'duration_default_minimum':
      return t('schedule.confidence_reason_default_minimum', { defaultValue: 'Default duration: no labour, quantity or price' });
    case 'capped_by_price':
      return t('schedule.confidence_reason_capped_by_price', { defaultValue: 'The guess was held down by the price' });
    case 'unverified_norm':
      return t('schedule.confidence_reason_unverified_norm', { defaultValue: 'The norm hours are marked as not verified' });
    case 'shortened':
      return t('schedule.confidence_reason_shortened', { defaultValue: 'Shortened to fit the end date' });
    case 'logic_bill_order':
      return t('schedule.confidence_reason_bill_order', { defaultValue: 'Sequence follows the order of the bill' });
    case 'logic_spans_works':
      return t('schedule.confidence_reason_logic_spans_works', { defaultValue: 'Placed over the whole works by rule' });
    case 'breakdown_lump_sum':
      return t('schedule.confidence_reason_lump_sum', { defaultValue: 'A lump sum, not broken down by quantity' });
    case 'breakdown_whole_position':
      return t('schedule.confidence_reason_whole_position', { defaultValue: 'One bar for the whole position' });
    default:
      return null;
  }
}

/** The tooltip of a badge: the score, then why. */
export function confidenceTooltip(t: TFunction, c: ActivityConfidence): string {
  const head = t('schedule.confidence_tooltip', {
    defaultValue: 'Confidence {{score}} ({{band}}). Check low ones before you rely on the plan.',
    score: formatScore(c.score),
    band: bandLabel(t, c.band),
  });
  const reasons = c.reasons.map((r) => confidenceReasonText(t, r)).filter((r): r is string => !!r);
  return reasons.length ? `${head}\n${reasons.map((r) => `- ${r}`).join('\n')}` : head;
}

const BAND_CLASSES: Record<ConfidenceBand, string> = {
  high: 'border-semantic-success/40 bg-semantic-success/10 text-semantic-success',
  medium: 'border-border-light bg-surface-secondary text-content-tertiary',
  low: 'border-semantic-warning/50 bg-semantic-warning/15 text-semantic-warning',
};

/** A small badge with the score; a low score carries a warning sign so it stands out for review. */
export function ConfidenceBadge({ confidence }: { confidence: ActivityConfidence }) {
  const { t } = useTranslation();
  return (
    <span
      title={confidenceTooltip(t, confidence)}
      data-testid="confidence-badge"
      data-band={confidence.band}
      className={`inline-flex shrink-0 cursor-help items-center gap-0.5 rounded border px-1 py-0.5 text-[9px] font-semibold tabular-nums ${BAND_CLASSES[confidence.band]}`}
    >
      {confidence.band === 'low' && <AlertTriangle size={9} className="shrink-0" />}
      {formatScore(confidence.score)}
    </span>
  );
}
