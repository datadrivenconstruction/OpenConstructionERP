// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Accuracy scoreboard - the AI trust moat made visible.
//
// Construction teams' #1 stated barrier to trusting AI is accuracy: a model
// that sounds confident but is quietly wrong is worse than no model. Our answer
// is to score every agent's stated confidence against what actually happened on
// the user's own runs (recorded via the per-run verdict). This panel surfaces
// that record: for each agent, how often it was right, how confident it claimed
// to be, whether the two line up (calibration), and its Brier score. It is the
// proof, not the promise - built entirely from first-party outcomes, never a
// vendor benchmark.
import { useTranslation } from 'react-i18next';
import { Target, Info, Sparkles, Loader2 } from 'lucide-react';
import clsx from 'clsx';

import { agentDisplayName } from './agentMeta';
import type { AccuracyScore, AgentDescriptor } from '../api';
import { fmtFixed } from '@/shared/lib/formatters';

interface AccuracyScoreboardProps {
  scores: AccuracyScore[];
  agents: AgentDescriptor[];
  loading: boolean;
  // Hosted-demo affordance: when true, the empty state offers a one-tap "see
  // AI in practice" action that seeds a few pre-scored sample runs so the
  // scoreboard renders populated. Hidden on real installs.
  canSeedSample?: boolean;
  seeding?: boolean;
  onSeedSample?: () => void;
}

/** Compare stated confidence to observed accuracy -> a calibration verdict. */
function calibrationVerdict(meanConfidence: number, observedRate: number): {
  key: string;
  label: string;
  chip: string;
} {
  const gap = meanConfidence - observedRate;
  if (Math.abs(gap) <= 0.1)
    return {
      key: 'calibrated',
      label: 'Well calibrated',
      chip: 'bg-semantic-success-bg text-semantic-success',
    };
  if (gap > 0.1)
    return {
      key: 'overconfident',
      label: 'Over-confident',
      chip: 'bg-semantic-warning-bg text-[#b45309]',
    };
  return {
    key: 'underconfident',
    label: 'Under-confident',
    chip: 'bg-semantic-info-bg text-semantic-info',
  };
}

function pct(x: number): number {
  if (!Number.isFinite(x)) return 0;
  return Math.round(Math.min(1, Math.max(0, x)) * 100);
}

function MiniBar({ value, tint, label }: { value: number; tint: string; label: string }): JSX.Element {
  return (
    <div className="flex items-center gap-2">
      <span className="w-12 shrink-0 text-2xs uppercase tracking-wide text-content-tertiary">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-secondary">
        <div className={clsx('h-full rounded-full', tint)} style={{ width: `${pct(value)}%` }} />
      </div>
      <span className="w-9 shrink-0 text-right text-2xs font-medium tabular-nums text-content-secondary">
        {pct(value)}%
      </span>
    </div>
  );
}

function ScoreCard({
  score,
  agents,
}: {
  score: AccuracyScore;
  agents: AgentDescriptor[];
}): JSX.Element {
  const { t } = useTranslation();
  const descriptor = agents.find((a) => a.name === score.agent_name);
  const name = agentDisplayName(score.agent_name, descriptor?.display_name);
  const verdict = calibrationVerdict(score.mean_confidence, score.observed_rate);

  return (
    <li className="rounded-xl border border-border-light bg-surface-elevated p-3 shadow-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-content-primary" title={name}>
            {name}
          </div>
          <div className="text-2xs text-content-tertiary">
            {t('agents.accuracy.scored_count', {
              defaultValue: '{{count}} scored run',
              defaultValue_plural: '{{count}} scored runs',
              count: score.count,
            })}
          </div>
        </div>
        <span
          className={clsx(
            'shrink-0 rounded-full px-2 py-0.5 text-2xs font-semibold',
            verdict.chip,
          )}
        >
          {t(`agents.accuracy.verdict_${verdict.key}`, { defaultValue: verdict.label })}
        </span>
      </div>

      <div className="mt-2.5 flex items-baseline gap-1.5">
        <span className="text-2xl font-bold tabular-nums text-content-primary">{pct(score.observed_rate)}%</span>
        <span className="text-xs text-content-tertiary">
          {t('agents.accuracy.accurate', { defaultValue: 'accurate' })}
        </span>
        <span className="ml-auto text-2xs text-content-tertiary">
          {t('agents.accuracy.brier', { defaultValue: 'Brier {{score}}', score: fmtFixed(score.brier_score, 2) })}
        </span>
      </div>

      <div className="mt-2 space-y-1">
        <MiniBar
          value={score.mean_confidence}
          tint="bg-oe-blue"
          label={t('agents.accuracy.said', { defaultValue: 'Said' })}
        />
        <MiniBar
          value={score.observed_rate}
          tint="bg-semantic-success"
          label={t('agents.accuracy.real', { defaultValue: 'Real' })}
        />
      </div>
    </li>
  );
}

export function AccuracyScoreboard({
  scores,
  agents,
  loading,
  canSeedSample = false,
  seeding = false,
  onSeedSample,
}: AccuracyScoreboardProps): JSX.Element {
  const { t } = useTranslation();

  return (
    <section aria-label={t('agents.accuracy.title', { defaultValue: 'Accuracy scoreboard' })}>
      <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-content-tertiary">
        <Target className="h-4 w-4" aria-hidden="true" />
        {t('agents.accuracy.title', { defaultValue: 'Accuracy scoreboard' })}
      </h2>
      <p className="mt-1 text-2xs leading-relaxed text-content-tertiary">
        {t('agents.accuracy.subtitle', {
          defaultValue: 'Stated confidence vs your recorded outcomes, per agent.',
        })}
      </p>

      {loading && (
        <div className="mt-3 space-y-2">
          <div className="h-24 animate-pulse rounded-xl bg-surface-secondary/60" />
          <div className="h-24 animate-pulse rounded-xl bg-surface-secondary/60" />
        </div>
      )}

      {!loading && scores.length === 0 && (
        <div className="mt-3 rounded-xl border border-dashed border-border-light bg-surface-secondary/30 p-5 text-center">
          <Info className="mx-auto h-5 w-5 text-content-tertiary" aria-hidden="true" />
          <p className="mt-2 text-xs font-medium text-content-secondary">
            {t('agents.accuracy.empty_title', { defaultValue: 'No scored runs yet' })}
          </p>
          <p className="mt-1 text-2xs leading-relaxed text-content-tertiary">
            {t('agents.accuracy.empty_body', {
              defaultValue:
                'Open a finished run and mark it correct or incorrect. Once an answer has a stated confidence and a recorded outcome, it appears here.',
            })}
          </p>
          {canSeedSample && onSeedSample && (
            <button
              type="button"
              onClick={onSeedSample}
              disabled={seeding}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-semibold text-content-inverse transition-colors hover:bg-oe-blue-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {seeding ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {t('agents.accuracy.see_in_practice', { defaultValue: 'See AI in practice' })}
            </button>
          )}
        </div>
      )}

      {!loading && scores.length > 0 && (
        <ul className="mt-3 space-y-2">
          {scores.map((s) => (
            <ScoreCard key={s.agent_name} score={s} agents={agents} />
          ))}
        </ul>
      )}
    </section>
  );
}

export default AccuracyScoreboard;
