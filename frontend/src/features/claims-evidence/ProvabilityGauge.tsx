// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// <ProvabilityGauge> - how provable is one change / claim from its evidence?
//
// A self-contained panel over the claims-evidence provability endpoint (#6). It
// shows the 0-100 provability score with its band, a per-signal breakdown of
// what evidence is present vs missing (notice timeliness, acknowledgement,
// linked instruction, ownership continuity, dated record) and the ordered list
// of cures - the concrete actions that would raise the score before the change
// is contested. Read-only; nothing is written.
//
// Mount it anywhere a single change / variation / MoC is on screen (e.g. a
// change-order or variation detail drawer): pass the project id, the subject
// kind and the subject id. It owns its own data fetch, so a host only needs to
// render <ProvabilityGauge projectId=... subjectKind=... subjectId=... />.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, ShieldCheck, XCircle } from 'lucide-react';
import { Card, Badge, EmptyState, SkeletonTable } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { getChangeProvability, type SubjectKind } from './api';
import type { ProvabilityBand } from './types';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

const BAND_VARIANT: Record<ProvabilityBand, BadgeVariant> = {
  strong: 'success',
  moderate: 'warning',
  weak: 'error',
};

// English fallbacks for the engine's signal tokens. The rendered label comes
// from the locale (claims_evidence.signal.*); these keep an unknown or not yet
// translated token readable rather than leaking a raw key.
const SIGNAL_LABEL: Record<string, string> = {
  notice_timeliness: 'Notice served on time',
  acknowledgement: 'Acknowledged by the other party',
  linked_instruction: 'Linked to a governing instruction',
  ownership_continuity: 'Clear ownership chain',
  date_completeness: 'Dated contemporaneous record',
};

/** Best-effort title-case of a token like "notice_timeliness". */
function humanize(token: string): string {
  return (token || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

/** Ring colour class for the score dial, by band. */
function bandRingClass(band: ProvabilityBand): string {
  if (band === 'strong') return 'text-semantic-success';
  if (band === 'moderate') return 'text-semantic-warning';
  return 'text-semantic-error';
}

export interface ProvabilityGaugeProps {
  projectId: string;
  subjectKind: SubjectKind;
  subjectId: string;
  /** Optional extra classes for the outer card. */
  className?: string;
}

/**
 * Provability gauge for one change / claim subject.
 *
 * Fetches the score on mount (and whenever the subject changes) and renders the
 * dial, the present / missing signal rows and the cure list. A host that has not
 * yet selected a subject should simply not render this component.
 */
export function ProvabilityGauge({ projectId, subjectKind, subjectId, className }: ProvabilityGaugeProps) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['claims-evidence', 'provability', projectId, subjectKind, subjectId],
    queryFn: () => getChangeProvability(projectId, subjectKind, subjectId),
    enabled: !!projectId && !!subjectKind && !!subjectId,
    retry: false,
    staleTime: 30_000,
  });
  const score = q.data;

  return (
    <Card className={`space-y-4 p-4 ${className ?? ''}`}>
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <ShieldCheck className="h-4 w-4" />
        </span>
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('provability.title', { defaultValue: 'Provability' })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('provability.subtitle', {
              defaultValue: 'How well this change could be proven from the record',
            })}
          </p>
        </div>
      </div>

      {q.isLoading ? (
        <SkeletonTable />
      ) : q.isError ? (
        <div className="flex items-center gap-2 text-sm text-semantic-error">
          <AlertTriangle className="h-4 w-4" />
          <span>{getErrorMessage(q.error)}</span>
        </div>
      ) : !score ? (
        <EmptyState
          icon={<ShieldCheck className="h-6 w-6" />}
          title={t('provability.empty_title', { defaultValue: 'No score yet' })}
          description={t('provability.empty_desc', {
            defaultValue: 'Select a change to see how provable it is from the evidence on the project.',
          })}
        />
      ) : (
        <div className="space-y-4">
          {/* Score dial + band */}
          <div className="flex items-center gap-4">
            <ScoreDial score={score.score} band={score.band} />
            <div className="space-y-1">
              <Badge variant={BAND_VARIANT[score.band]} dot>
                {t(`claims_evidence.range.${score.band}`, { defaultValue: humanize(score.band) })}
              </Badge>
              <div className="text-xs text-content-tertiary">
                {score.entry_count > 0
                  ? t('provability.record_span', {
                      defaultValue: '{{count}} dated record(s)',
                      count: score.entry_count,
                    })
                  : t('provability.no_record', { defaultValue: 'No dated record' })}
              </div>
            </div>
          </div>

          {/* Per-signal breakdown: present vs missing */}
          <div className="space-y-1.5">
            <div className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('provability.signals', { defaultValue: 'Evidence signals' })}
            </div>
            <ul className="space-y-1">
              {score.sub_scores.map((s) => (
                <li key={s.signal} className="flex items-center gap-2 text-sm">
                  {s.present ? (
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-semantic-success" />
                  ) : (
                    <XCircle className="h-4 w-4 shrink-0 text-content-tertiary" />
                  )}
                  <span className={s.present ? 'text-content-secondary' : 'text-content-tertiary'}>
                    {t(`claims_evidence.signal.${s.signal}`, {
                      defaultValue: SIGNAL_LABEL[s.signal] ?? humanize(s.signal),
                    })}
                  </span>
                  <span className="ml-auto tabular-nums text-xs text-content-tertiary">
                    {s.earned}/{s.weight}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {/* Cure list: what to fix, worst-cost first as the engine orders it */}
          {score.weaknesses.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                {t('provability.cures', { defaultValue: 'What would strengthen it' })}
              </div>
              <ul className="space-y-1.5">
                {score.weaknesses.map((w) => (
                  <li key={w.token} className="flex items-start gap-2 text-sm text-content-secondary">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-warning" />
                    {/* Translate by the engine's stable token; an unknown token
                        falls back to the backend's English prose untouched. */}
                    <span>{t(`claims_evidence.weakness.${w.token}`, { defaultValue: w.message })}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/**
 * A compact circular score dial rendered as an SVG ring. The filled arc is
 * proportional to score/100 and tinted by the band; the number sits in the
 * middle. Purely presentational and self-contained.
 */
function ScoreDial({ score, band }: { score: number; band: ProvabilityBand }) {
  const clamped = Math.max(0, Math.min(100, score));
  const radius = 26;
  const circumference = 2 * Math.PI * radius;
  const dash = (clamped / 100) * circumference;

  return (
    <div className="relative h-16 w-16 shrink-0">
      <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90" aria-hidden="true">
        <circle cx="32" cy="32" r={radius} fill="none" strokeWidth="6" className="stroke-border-light" />
        <circle
          cx="32"
          cy="32"
          r={radius}
          fill="none"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference - dash}`}
          className={bandRingClass(band)}
          stroke="currentColor"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-lg font-semibold tabular-nums text-content-primary">{clamped}</span>
      </div>
    </div>
  );
}

export default ProvabilityGauge;
