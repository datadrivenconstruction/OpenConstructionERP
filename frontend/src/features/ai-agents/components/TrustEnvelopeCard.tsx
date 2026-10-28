// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Trust & verification card for a completed agent run.
//
// The single biggest barrier construction teams report to AI adoption is
// trust: can an estimator rely on what the model said, and can they check it?
// Every analytical agent already attaches a structured trust envelope to its
// answer - a calibrated confidence, a short rationale, the REAL sources it
// cited, and what would make it more sure - but the UI used to discard it.
// This card surfaces that envelope and closes the loop: the user records
// whether the answer turned out correct, which lets the accuracy scoreboard
// score the stated confidence against what actually happened. Nothing here is
// fabricated; an empty envelope renders nothing.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShieldCheck,
  FileText,
  Table2,
  CalendarClock,
  Receipt,
  MessageSquare,
  Link2,
  HelpCircle,
  Cpu,
  ThumbsUp,
  ThumbsDown,
  Loader2,
  CheckCircle2,
  XCircle,
  Pencil,
  type LucideIcon,
} from 'lucide-react';
import clsx from 'clsx';

import { useToastStore } from '@/stores/useToastStore';
import { aiAgentsApi, type AgentRun, type TrustSource } from '../api';
import { getIntlLocale, fmtFixed } from '@/shared/lib/formatters';

// -- Helpers -------------------------------------------------------------------

function clamp01(x: number): number {
  if (!Number.isFinite(x)) return 0;
  if (x < 0) return 0;
  if (x > 1) return 1;
  return x;
}

/** Colour + label tone for a confidence in [0, 1]. */
function confidenceTone(p: number): {
  bar: string;
  text: string;
  key: string;
  label: string;
} {
  if (p >= 0.75)
    return { bar: 'bg-semantic-success', text: 'text-semantic-success', key: 'high', label: 'High confidence' };
  if (p >= 0.5)
    return { bar: 'bg-oe-blue', text: 'text-oe-blue-text', key: 'moderate', label: 'Moderate confidence' };
  if (p >= 0.25)
    return { bar: 'bg-semantic-warning', text: 'text-[#b45309]', key: 'low', label: 'Low confidence' };
  return { bar: 'bg-semantic-error', text: 'text-semantic-error', key: 'very_low', label: 'Very low confidence' };
}

// Source-kind -> icon for the citation list (graceful default for unknown kinds).
const SOURCE_ICON: Record<string, LucideIcon> = {
  document: FileText,
  boq: Table2,
  schedule: CalendarClock,
  cost_item: Receipt,
  rfi: MessageSquare,
};

/** Render a source's relevance score: 0..1 as a percentage, else two decimals. */
function formatScore(score: number): string {
  if (score >= 0 && score <= 1) return `${Math.round(score * 100)}%`;
  return fmtFixed(score, 2);
}

function formatDate(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(getIntlLocale());
}

// -- Sub-views ---------------------------------------------------------------

function SourceRow({ source }: { source: TrustSource }): JSX.Element {
  const Icon = SOURCE_ICON[(source.kind ?? '').toLowerCase()] ?? Link2;
  return (
    <li className="flex items-center gap-2 rounded-md bg-surface-secondary/50 px-2.5 py-1.5 text-xs">
      <Icon className="h-3.5 w-3.5 shrink-0 text-content-tertiary" aria-hidden="true" />
      <span className="shrink-0 rounded bg-surface-elevated px-1.5 py-0.5 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
        {source.kind || 'ref'}
      </span>
      <code className="min-w-0 flex-1 truncate font-mono text-content-secondary" title={source.ref}>
        {source.ref}
      </code>
      {source.label && (
        <span className="hidden min-w-0 max-w-[40%] truncate text-content-tertiary sm:inline" title={source.label}>
          {source.label}
        </span>
      )}
      {typeof source.score === 'number' && (
        <span className="shrink-0 text-2xs font-medium text-content-tertiary">{formatScore(source.score)}</span>
      )}
    </li>
  );
}

// -- Card ----------------------------------------------------------------------

export function TrustEnvelopeCard({ run }: { run: AgentRun }): JSX.Element | null {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [note, setNote] = useState('');
  // Lets a user reopen the verdict controls after a prior verdict was recorded.
  const [editing, setEditing] = useState(false);

  const trust = run.trust;

  const mutation = useMutation({
    mutationFn: (correct: boolean) =>
      aiAgentsApi.recordRunOutcome(run.id, {
        correct,
        note: note.trim() ? note.trim() : undefined,
      }),
    onSuccess: (_res, correct) => {
      addToast({
        type: 'success',
        title: t('agents.trust.verdict_saved', { defaultValue: 'Verdict recorded' }),
        message: correct
          ? t('agents.trust.verdict_saved_correct', {
              defaultValue: 'Marked correct. It now feeds the accuracy scoreboard.',
            })
          : t('agents.trust.verdict_saved_wrong', {
              defaultValue: 'Marked incorrect. It now feeds the accuracy scoreboard.',
            }),
      });
      setEditing(false);
      setNote('');
      void queryClient.invalidateQueries({ queryKey: ['ai-agents', 'run', run.id] });
      void queryClient.invalidateQueries({ queryKey: ['ai-agents', 'accuracy'] });
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('agents.trust.verdict_error', { defaultValue: 'Could not record the verdict' }),
      });
    },
  });

  // Render nothing unless this is a finished run carrying a non-empty envelope.
  const sources = trust?.sources ?? [];
  const hasContent =
    trust != null &&
    (trust.confidence != null ||
      !!trust.rationale ||
      sources.length > 0 ||
      !!trust.what_would_increase_confidence ||
      trust.actual_outcome != null);
  if (run.status !== 'completed' || !trust || !hasContent) return null;

  const confidence = trust.confidence != null ? clamp01(trust.confidence) : null;
  const tone = confidence != null ? confidenceTone(confidence) : null;
  const recorded = trust.actual_outcome != null;
  const recordedDate = formatDate(trust.outcome_recorded_at);
  const showControls = !recorded || editing;

  return (
    <section className="space-y-4 rounded-xl border border-border-light bg-surface-elevated p-4 shadow-xs">
      <header className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        <ShieldCheck className="h-3.5 w-3.5 text-oe-blue" aria-hidden="true" />
        {t('agents.trust.title', { defaultValue: 'Trust & verification' })}
      </header>

      {/* Calibrated confidence */}
      {confidence != null && tone != null && (
        <div>
          <div className="mb-1 flex items-baseline justify-between gap-3">
            <span className={clsx('text-xs font-semibold', tone.text)}>
              {t(`agents.trust.confidence_${tone.key}`, { defaultValue: tone.label })}
            </span>
            <span className="text-sm font-semibold tabular-nums text-content-primary">
              {Math.round(confidence * 100)}%
            </span>
          </div>
          <div
            className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary"
            role="progressbar"
            aria-valuenow={Math.round(confidence * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={t('agents.trust.confidence_aria', { defaultValue: 'Stated confidence' })}
          >
            <div
              className={clsx('h-full rounded-full transition-all', tone.bar)}
              style={{ width: `${Math.round(confidence * 100)}%` }}
            />
          </div>
          {trust.rationale && (
            <p className="mt-2 text-xs leading-relaxed text-content-secondary">{trust.rationale}</p>
          )}
        </div>
      )}

      {/* Cited sources (real ids / paths the user can open) */}
      {sources.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            <FileText className="h-3.5 w-3.5" aria-hidden="true" />
            {t('agents.trust.sources', { defaultValue: 'Sources cited' })}
          </div>
          <ul className="mt-1.5 space-y-1">
            {sources.map((s, i) => (
              <SourceRow key={`${s.kind}-${s.ref}-${i}`} source={s} />
            ))}
          </ul>
        </div>
      )}

      {/* What would increase confidence */}
      {trust.what_would_increase_confidence && (
        <div className="flex items-start gap-1.5 rounded-lg bg-surface-secondary/50 px-3 py-2 text-xs text-content-secondary">
          <HelpCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-content-tertiary" aria-hidden="true" />
          <span>
            <span className="font-medium text-content-primary">
              {t('agents.trust.to_be_more_sure', { defaultValue: 'To be more certain' })}:
            </span>{' '}
            {trust.what_would_increase_confidence}
          </span>
        </div>
      )}

      {/* Verdict loop - records the actual outcome (feeds the scoreboard) */}
      <div className="border-t border-border-light pt-3">
        {recorded && !editing && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span
              className={clsx(
                'inline-flex items-center gap-1.5 text-xs font-medium',
                trust.actual_outcome ? 'text-semantic-success' : 'text-semantic-error',
              )}
            >
              {trust.actual_outcome ? (
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              ) : (
                <XCircle className="h-4 w-4" aria-hidden="true" />
              )}
              {trust.actual_outcome
                ? t('agents.trust.marked_correct', { defaultValue: 'You marked this correct' })
                : t('agents.trust.marked_wrong', { defaultValue: 'You marked this incorrect' })}
              {recordedDate && (
                <span className="font-normal text-content-tertiary">
                  {' '}
                  {t('agents.trust.on_date', { defaultValue: 'on {{date}}', date: recordedDate })}
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-secondary hover:text-content-primary"
            >
              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
              {t('agents.trust.change_verdict', { defaultValue: 'Change' })}
            </button>
          </div>
        )}

        {recorded && !editing && trust.outcome_note && (
          <p className="mt-2 rounded-md bg-surface-secondary/50 px-2.5 py-1.5 text-xs italic text-content-secondary">
            {trust.outcome_note}
          </p>
        )}

        {showControls && (
          <div className="space-y-2.5">
            <p className="text-xs font-medium text-content-primary">
              {t('agents.trust.verdict_prompt', { defaultValue: 'Did this answer turn out correct?' })}
            </p>
            <p className="text-2xs text-content-tertiary">
              {t('agents.trust.verdict_help', {
                defaultValue:
                  'Your verdict scores the stated confidence against reality on the accuracy scoreboard. Nothing is shared.',
              })}
            </p>
            <label htmlFor={`verdict-note-${run.id}`} className="sr-only">
              {t('agents.trust.note_label', { defaultValue: 'Optional correction note' })}
            </label>
            <textarea
              id={`verdict-note-${run.id}`}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder={t('agents.trust.note_placeholder', {
                defaultValue: 'Optional: what was the right answer, or why was it off?',
              })}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-xs text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
            />
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={mutation.isPending}
                onClick={() => mutation.mutate(true)}
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-lg border border-semantic-success/40 bg-semantic-success-bg/60 px-3 py-1.5 text-xs font-semibold text-semantic-success transition-all',
                  'hover:bg-semantic-success-bg disabled:cursor-not-allowed disabled:opacity-50',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-semantic-success/40',
                )}
              >
                {mutation.isPending && mutation.variables === true ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {t('agents.trust.mark_correct', { defaultValue: 'Correct' })}
              </button>
              <button
                type="button"
                disabled={mutation.isPending}
                onClick={() => mutation.mutate(false)}
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-lg border border-semantic-error/40 bg-semantic-error-bg/60 px-3 py-1.5 text-xs font-semibold text-semantic-error transition-all',
                  'hover:bg-semantic-error-bg disabled:cursor-not-allowed disabled:opacity-50',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-semantic-error/40',
                )}
              >
                {mutation.isPending && mutation.variables === false ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <ThumbsDown className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {t('agents.trust.mark_wrong', { defaultValue: 'Incorrect' })}
              </button>
              {editing && (
                <button
                  type="button"
                  onClick={() => {
                    setEditing(false);
                    setNote('');
                  }}
                  className="inline-flex items-center rounded-md px-2 py-1 text-xs font-medium text-content-tertiary transition-colors hover:text-content-secondary"
                >
                  {t('common.cancel', { defaultValue: 'Cancel' })}
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Model footer */}
      {trust.model && (
        <div className="flex items-center gap-1.5 text-2xs text-content-tertiary">
          <Cpu className="h-3 w-3" aria-hidden="true" />
          {t('agents.trust.model', { defaultValue: 'Model' })}: {trust.model}
        </div>
      )}
    </section>
  );
}

export default TrustEnvelopeCard;
