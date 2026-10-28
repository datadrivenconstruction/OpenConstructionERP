// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// AI feedback summary - the read side of the generic trust loop.
//
// Every thumbs up / down a user records on a non-run AI surface (the AI
// Estimator result, a match suggestion, an advisor answer) is rolled up here
// into a correct rate, overall and per surface. The accuracy scoreboard scores
// agent *runs*; this covers the AI the user meets everywhere else, so the trust
// signal those verdicts feed is no longer write-only. A surface with no verdicts
// shows a dash, never a misleading 0%.
import { useTranslation } from 'react-i18next';
import { MessageSquare, Info } from 'lucide-react';
import clsx from 'clsx';

import type { AIFeedbackSummary, SurfaceFeedback } from '../api';

interface FeedbackSummaryPanelProps {
  summary: AIFeedbackSummary | null;
  loading: boolean;
}

/** A [0,1] rate as a whole percent, or null when the rate is undefined. */
function pct(rate: number | null | undefined): number | null {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return null;
  return Math.round(Math.min(1, Math.max(0, rate)) * 100);
}

/** Tint the bar by how the surface is landing (green strong, blue ok, amber weak). */
function rateTint(rate: number | null): string {
  if (rate === null) return 'bg-surface-secondary';
  if (rate >= 0.8) return 'bg-semantic-success';
  if (rate >= 0.5) return 'bg-oe-blue';
  return 'bg-semantic-warning';
}

function SurfaceRow({ row }: { row: SurfaceFeedback }): JSX.Element {
  const { t } = useTranslation();
  // Friendly label for the known surfaces, falling back to the raw slug.
  const label = t(`agents.feedback.surface_${row.surface}`, { defaultValue: row.surface });
  const percent = pct(row.correct_rate);

  return (
    <li className="rounded-xl border border-border-light bg-surface-elevated p-3 shadow-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-content-primary" title={label}>
          {label}
        </span>
        <span className="shrink-0 text-2xs text-content-tertiary">
          {t('agents.feedback.counts', {
            defaultValue: '{{correct}}/{{total}} correct',
            correct: row.correct,
            total: row.total,
          })}
        </span>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-secondary">
          <div
            className={clsx('h-full rounded-full', rateTint(row.correct_rate))}
            style={{ width: `${percent ?? 0}%` }}
          />
        </div>
        <span className="w-9 shrink-0 text-right text-2xs font-medium tabular-nums text-content-secondary">
          {percent === null ? '—' : `${percent}%`}
        </span>
      </div>
    </li>
  );
}

export function FeedbackSummaryPanel({ summary, loading }: FeedbackSummaryPanelProps): JSX.Element {
  const { t } = useTranslation();
  const overall = pct(summary?.correct_rate ?? null);
  const hasFeedback = !!summary && summary.total > 0;

  return (
    <section aria-label={t('agents.feedback.title', { defaultValue: 'AI feedback' })}>
      <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-content-tertiary">
        <MessageSquare className="h-4 w-4" aria-hidden="true" />
        {t('agents.feedback.title', { defaultValue: 'AI feedback' })}
      </h2>
      <p className="mt-1 text-2xs leading-relaxed text-content-tertiary">
        {t('agents.feedback.subtitle', {
          defaultValue: 'Your thumbs up / down on AI results across the app, by surface.',
        })}
      </p>

      {loading && (
        <div className="mt-3 space-y-2">
          <div className="h-16 animate-pulse rounded-xl bg-surface-secondary/60" />
          <div className="h-16 animate-pulse rounded-xl bg-surface-secondary/60" />
        </div>
      )}

      {!loading && !hasFeedback && (
        <div className="mt-3 rounded-xl border border-dashed border-border-light bg-surface-secondary/30 p-5 text-center">
          <Info className="mx-auto h-5 w-5 text-content-tertiary" aria-hidden="true" />
          <p className="mt-2 text-xs font-medium text-content-secondary">
            {t('agents.feedback.empty_title', { defaultValue: 'No feedback yet' })}
          </p>
          <p className="mt-1 text-2xs leading-relaxed text-content-tertiary">
            {t('agents.feedback.empty_body', {
              defaultValue:
                'Use the thumbs up / down on an AI Estimator result, a match suggestion or an advisor answer. Your verdicts roll up here.',
            })}
          </p>
        </div>
      )}

      {!loading && hasFeedback && summary && (
        <>
          <div className="mt-3 flex items-baseline gap-1.5">
            <span className="text-2xl font-bold tabular-nums text-content-primary">
              {overall === null ? '—' : `${overall}%`}
            </span>
            <span className="text-xs text-content-tertiary">
              {t('agents.feedback.overall_correct', { defaultValue: 'marked correct' })}
            </span>
            <span className="ml-auto text-2xs text-content-tertiary">
              {t('agents.feedback.total_verdicts', {
                defaultValue: '{{count}} verdict',
                defaultValue_plural: '{{count}} verdicts',
                count: summary.total,
              })}
            </span>
          </div>
          <ul className="mt-3 space-y-2">
            {summary.by_surface.map((row) => (
              <SurfaceRow key={row.surface} row={row} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export default FeedbackSummaryPanel;
