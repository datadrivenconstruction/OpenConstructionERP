// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// UsageBadge - the single, instantly readable indicator next to a cost
// item's price. It tells you whether the rate is already used in an
// estimate (BOQ position), how many times, and how fresh that evidence is.
//
// This replaces the old pair of contradictory circles (a green usage pill
// next to a separate red certainty dot). One control, one story:
//   * Unused  -> quiet outlined dot. Unused is NORMAL, not an error, so it
//     is muted and never red.
//   * Used    -> a "check + count" pill, tinted by the certainty band so the
//     freshness reads at a glance:
//       - green  band -> success tone (well proven: used often and recently).
//       - yellow band -> amber tone (in use, not yet proven).
//       - red / stale -> amber tone too. A used item is never shown in red:
//         red inside a "used" pill reads as an error. Stale evidence is a
//         "double-check" hint, which amber communicates.
//
// Usage counts and the certainty band both come from page-level batched
// requests, passed down as props - no per-row fetch.

import { useTranslation } from 'react-i18next';
import { Check } from 'lucide-react';
import clsx from 'clsx';

import type { CertaintyBadge as CertaintyBadgeData } from './api';

/** Sentinel age the backend uses for "never logged". Mirrors
 *  ``intelligence.py::NEVER_USED_AGE_DAYS`` (rounded for the day-diff). */
const STALE_AGE_SENTINEL = 999_000;

/** Plain-words freshness phrase for the most recent use. Mirrors the helper
 *  the old CertaintyBadge used so the wording stays consistent. */
function formatAge(ageDays: number, t: ReturnType<typeof useTranslation>['t']): string {
  if (ageDays >= STALE_AGE_SENTINEL) {
    return t('costs.certainty.never_used', { defaultValue: 'never used' });
  }
  if (ageDays < 30) {
    return t('costs.certainty.age_days', { count: ageDays, defaultValue: '{{count}}d ago' });
  }
  if (ageDays < 365) {
    const months = Math.round(ageDays / 30);
    return t('costs.certainty.age_months', { count: months, defaultValue: '{{count}}mo ago' });
  }
  const years = Math.round((ageDays / 365) * 10) / 10;
  return t('costs.certainty.age_years', { count: years, defaultValue: '{{count}}y ago' });
}

interface UsageBadgeProps {
  /** Number of estimate (BOQ) positions this cost item is used in. 0 = unused. */
  count: number;
  /** Pre-resolved certainty band from the page-level batch fetch. Tints the
   *  pill and feeds the freshness phrase in the tooltip. ``null`` (or omitted)
   *  means "no band data" - the pill falls back to the neutral success look. */
  band?: CertaintyBadgeData | null;
  /** Optional extra classes for the wrapper. */
  className?: string;
}

// Pill tints, keyed by the visible band. A "used" pill is never red - red is
// reserved for genuine errors, and a used rate is not an error.
const PILL_TINTS = {
  green: 'bg-semantic-success/12 text-semantic-success ring-semantic-success/25',
  amber: 'bg-amber-500/12 text-amber-600 dark:text-amber-400 ring-amber-500/30',
} as const;

export function UsageBadge({ count, band, className }: UsageBadgeProps) {
  const { t } = useTranslation();

  if (count <= 0) {
    // Quiet "not yet used" state - a small outlined dot, no alarm colour.
    const label = t('costs.usage.unused', {
      defaultValue: 'Not used in any estimate yet',
    });
    return (
      <span
        title={label}
        aria-label={label}
        data-usage="0"
        data-band={band?.confidence_badge ?? 'none'}
        className={clsx(
          'inline-flex h-2.5 w-2.5 shrink-0 rounded-full border border-content-tertiary/40',
          className,
        )}
      />
    );
  }

  // Green only when the band itself is green; everything else used reads as
  // amber (in use, double-check freshness) - never red.
  const visualBand: keyof typeof PILL_TINTS =
    band?.confidence_badge === 'green' ? 'green' : 'amber';

  const usageLabel = t('costs.usage.used_count', {
    count,
    defaultValue: 'Used in {{count}} estimate position',
    defaultValue_other: 'Used in {{count}} estimate positions',
  });
  // Combine usage with the freshness phrase when we have band data, so the
  // single control still surfaces "how recently" on hover.
  const label = band
    ? t('costs.usage.used_count_with_age', {
        count,
        age: formatAge(band.age_days, t),
        defaultValue: 'Used in {{count}} estimate position, last {{age}}',
        defaultValue_other: 'Used in {{count}} estimate positions, last {{age}}',
      })
    : usageLabel;

  return (
    <span
      title={label}
      aria-label={label}
      data-usage={count}
      data-band={band?.confidence_badge ?? visualBand}
      className={clsx(
        'inline-flex items-center gap-0.5 shrink-0 rounded-md px-1.5 py-0.5',
        'ring-1 ring-inset',
        PILL_TINTS[visualBand],
        'text-2xs font-semibold tabular-nums',
        className,
      )}
    >
      <Check size={10} strokeWidth={3} className="shrink-0" />
      {count}
    </span>
  );
}
