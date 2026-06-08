/**
 * Performance scorecard tile — four sparkline-style dials (Safety,
 * Quality, Schedule, Cost) + an overall score with a trend arrow vs
 * the immediately previous rating period.
 *
 * Backed by GET /api/v1/subcontractors/ratings/?subcontractor_id=...
 * The endpoint already returns rows ordered newest-first (period DESC)
 * — we read index 0 for "current" and index 1 for "prior" to compute
 * the delta arrow.
 *
 * Score domain: 0..100 (matches the SubcontractorRating Numeric(5,2)
 * column). A missing prior period renders the dials without a delta
 * indicator — the user sees the absolute score but no "vs last" yet.
 *
 * Renders inside the DetailDrawer "Ratings" tab as a header band
 * above the existing per-period table. Total component LOC ~120.
 */

import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { Shield, ClipboardCheck, CalendarClock, Coins, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import type { Rating } from './api';

interface ScorecardTileProps {
  ratings: Rating[];
}

function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  return typeof v === 'number' ? v : Number(v) || 0;
}

/**
 * Map a 0..100 score to a Tailwind colour token. We use the same
 * thresholds as a typical subcontractor prequalification platform scorecard
 * so PM users see a familiar palette.
 *
 * >= 80 green, >= 60 amber, < 60 red.
 */
function colorFor(score: number): { bar: string; text: string; ring: string } {
  if (score >= 80) {
    return {
      bar: 'bg-emerald-500',
      text: 'text-emerald-700 dark:text-emerald-300',
      ring: 'ring-emerald-200 dark:ring-emerald-900/40',
    };
  }
  if (score >= 60) {
    return {
      bar: 'bg-amber-500',
      text: 'text-amber-700 dark:text-amber-300',
      ring: 'ring-amber-200 dark:ring-amber-900/40',
    };
  }
  return {
    bar: 'bg-rose-500',
    text: 'text-rose-700 dark:text-rose-300',
    ring: 'ring-rose-200 dark:ring-rose-900/40',
  };
}

interface DialProps {
  label: string;
  value: number;
  prior: number | null;
  icon: React.ElementType;
}

/**
 * Single 4-segment dial. Visual: rounded horizontal bar filled to
 * value%, with the numeric score + trend chip beneath. Compact (~60px
 * height per dial) so all four fit on a phone-width screen.
 */
function Dial({ label, value, prior, icon: Icon }: DialProps) {
  const v = Math.max(0, Math.min(100, value));
  const cls = colorFor(v);
  // Trend delta in absolute points (0..100 domain) — easier for PMs
  // to read than a percentage of a percentage. Threshold of ±1 avoids
  // noise from rounding inside the rating computation.
  const delta = prior !== null ? Math.round(v - prior) : null;
  return (
    <div
      className={clsx(
        'rounded-lg ring-1 ring-inset p-2.5 bg-surface-primary',
        cls.ring,
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Icon size={12} className={cls.text} />
          <span className="text-[10px] font-medium uppercase tracking-wide text-content-secondary">
            {label}
          </span>
        </div>
        {delta !== null && delta !== 0 && (
          <span
            className={clsx(
              'inline-flex items-center gap-0.5 text-[10px] font-semibold tabular-nums',
              delta > 0
                ? 'text-emerald-600 dark:text-emerald-300'
                : 'text-rose-600 dark:text-rose-300',
            )}
            aria-label={
              delta > 0 ? `+${delta} vs prior period` : `${delta} vs prior period`
            }
          >
            {delta > 0 ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
            {delta > 0 ? `+${delta}` : delta}
          </span>
        )}
        {delta === 0 && (
          <Minus size={10} className="text-content-tertiary" aria-label="No change" />
        )}
      </div>
      <p className={clsx('mt-1 text-base font-semibold tabular-nums', cls.text)}>
        {v.toFixed(0)}
        <span className="ml-0.5 text-xs font-normal text-content-tertiary">
          /100
        </span>
      </p>
      <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
        <div
          className={clsx('h-full rounded-full transition-[width]', cls.bar)}
          style={{ width: `${v}%` }}
          role="progressbar"
          aria-valuenow={v}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${label} score ${v} out of 100`}
        />
      </div>
    </div>
  );
}

/**
 * Empty-state copy when no rating periods have been recorded. Stays
 * inside the same card frame so the layout doesn't jump when the
 * first rating lands.
 */
function ScorecardEmpty() {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-dashed border-border-light bg-surface-secondary p-4 text-center">
      <p className="text-xs text-content-tertiary">
        {t('subcontractors.scorecard_empty', {
          defaultValue:
            'No performance ratings recorded yet. Once monthly rollups exist, the four-dial scorecard appears here.',
        })}
      </p>
    </div>
  );
}

// Subset of Rating keys that are numeric score columns — typed this way
// so the dial config below can index into current/prior without
// dragging the dict-typed ``basis`` column through ``toNum``.
type ScoreField =
  | 'hse_score'
  | 'quality_score'
  | 'schedule_score'
  | 'cost_score';

export function ScorecardTile({ ratings }: ScorecardTileProps) {
  const { t } = useTranslation();
  if (!ratings || ratings.length === 0) {
    return <ScorecardEmpty />;
  }
  const current = ratings[0];
  const prior = ratings[1] ?? null;
  // Defensive narrow — the guard above already proves this, but TS
  // needs an explicit ``if (!current)`` for the conditional access
  // checks (noUncheckedIndexedAccess).
  if (!current) {
    return <ScorecardEmpty />;
  }
  const dials: Array<{ label: string; field: ScoreField; icon: React.ElementType }> = [
    {
      label: t('subcontractors.hse', { defaultValue: 'Safety' }),
      field: 'hse_score',
      icon: Shield,
    },
    {
      label: t('subcontractors.quality', { defaultValue: 'Quality' }),
      field: 'quality_score',
      icon: ClipboardCheck,
    },
    {
      label: t('subcontractors.schedule', { defaultValue: 'Schedule' }),
      field: 'schedule_score',
      icon: CalendarClock,
    },
    {
      label: t('subcontractors.cost', { defaultValue: 'Cost' }),
      field: 'cost_score',
      icon: Coins,
    },
  ];
  const overall = toNum(current.overall_score);
  const overallPrior = prior ? toNum(prior.overall_score) : null;
  const overallCls = colorFor(overall);
  const overallDelta =
    overallPrior !== null ? Math.round(overall - overallPrior) : null;

  return (
    <section
      aria-label={t('subcontractors.scorecard_aria', {
        defaultValue: 'Performance scorecard',
      })}
      className="space-y-2"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
          {t('subcontractors.scorecard_title', {
            defaultValue: 'Performance - current period',
          })}
        </h3>
        <span className="text-[11px] text-content-tertiary font-mono">
          {current.period}
          {prior ? ` · vs ${prior.period}` : ''}
        </span>
      </div>
      <div className="rounded-lg ring-1 ring-inset ring-border-light bg-surface-primary p-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-content-tertiary">
            {t('subcontractors.overall', { defaultValue: 'Overall' })}
          </p>
          <p
            className={clsx(
              'mt-0.5 text-2xl font-bold tabular-nums',
              overallCls.text,
            )}
          >
            {overall.toFixed(0)}
            <span className="ml-1 text-sm font-normal text-content-tertiary">
              /100
            </span>
          </p>
        </div>
        {overallDelta !== null && overallDelta !== 0 && (
          <span
            className={clsx(
              'inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset tabular-nums',
              overallDelta > 0
                ? 'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-900/40'
                : 'bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-950/30 dark:text-rose-300 dark:ring-rose-900/40',
            )}
          >
            {overallDelta > 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {overallDelta > 0 ? `+${overallDelta}` : overallDelta}{' '}
            {t('subcontractors.scorecard_vs_prior', {
              defaultValue: 'vs prior',
            })}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {dials.map((d) => (
          <Dial
            key={d.field}
            label={d.label}
            value={toNum(current[d.field])}
            prior={prior ? toNum(prior[d.field]) : null}
            icon={d.icon}
          />
        ))}
      </div>
    </section>
  );
}
