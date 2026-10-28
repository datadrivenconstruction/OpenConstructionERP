// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// <AITrustNote> — one consistent trust signal under any AI output.
//
// The #1 stated barrier construction teams report to trusting AI is not knowing
// whether they can rely on what it said, or check it. The agents surface
// already answers that (a calibrated confidence, cited sources, a record-the-
// outcome loop scored on the accuracy scoreboard), but the AI Estimator, the
// match suggestions and the cost advisor showed none of it - so every other AI
// output dead-ended the trust loop.
//
// This is the small, reusable piece that closes that gap everywhere the
// assistant speaks. It renders:
//   1. a compact "how this was produced / your data stays in your project" note
//      (with an optional confidence badge when the surface has a real score),
//   2. a correct / incorrect verdict with an optional note, posted to the
//      generic AI-feedback sink so the user's judgement is recorded.
//
// It is deliberately self-contained (no feature import) so any surface can drop
// it in. The fuller per-run TrustEnvelopeCard still lives in the agents feature
// for runs that carry a structured envelope; this is the lightweight signal for
// everything else.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { ShieldCheck, Lock, ThumbsUp, ThumbsDown, Loader2, CheckCircle2, Pencil } from 'lucide-react';
import clsx from 'clsx';

import { apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { ConfidenceBadge } from './ConfidenceBadge';

/** Acknowledgement shape returned by POST /api/v1/ai-agents/feedback. */
interface AIFeedbackResult {
  id: string;
  surface: string;
  correct: boolean;
}

export interface AITrustNoteProps {
  /** Which AI surface this note sits under (short slug, e.g. "ai_estimator").
   *  Recorded with the verdict so feedback can be grouped by surface later. */
  surface: string;
  /** Optional pointer to the specific output (a run / session / message id).
   *  Stored opaquely so a later review can line a verdict up with what
   *  produced it. */
  refId?: string | null;
  /** Optional project scope - verified against the caller's access on the
   *  server before the verdict is attributed to the project. */
  projectId?: string | null;
  /** One-line, surface-specific explanation of how the output was produced.
   *  Falls back to a generic line when omitted. */
  producedBy?: string;
  /** A real 0..1 confidence/score the surface already has, if any. When given
   *  it is shown as a confidence badge; when absent no confidence is implied. */
  confidence?: number | null;
  /** Hide the feedback verdict (show the trust line only). Default: show it. */
  showFeedback?: boolean;
  className?: string;
}

/**
 * Compact, reusable trust + feedback strip for any AI output.
 *
 * Renders a short "how this was produced / data stays in your project" line
 * (plus an optional confidence badge) and a correct/incorrect verdict that
 * posts to the generic AI-feedback endpoint. Records nothing money-related.
 */
export function AITrustNote({
  surface,
  refId,
  projectId,
  producedBy,
  confidence,
  showFeedback = true,
  className,
}: AITrustNoteProps): JSX.Element {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [note, setNote] = useState('');
  const [open, setOpen] = useState(false);
  // Once a verdict is recorded we collapse to a quiet confirmation with a
  // "change" affordance, mirroring the agents TrustEnvelopeCard pattern.
  const [recorded, setRecorded] = useState<boolean | null>(null);

  const mutation = useMutation({
    mutationFn: (correct: boolean) =>
      apiPost<AIFeedbackResult>('/v1/ai-agents/feedback', {
        surface,
        correct,
        ref: refId ?? undefined,
        project_id: projectId ?? undefined,
        note: note.trim() ? note.trim() : undefined,
      }),
    onSuccess: (_res, correct) => {
      setRecorded(correct);
      setOpen(false);
      setNote('');
      addToast({
        type: 'success',
        title: t('ai_trust.feedback_saved', { defaultValue: 'Thanks - your feedback was recorded' }),
      });
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('ai_trust.feedback_error', { defaultValue: 'Could not record your feedback' }),
      });
    },
  });

  const hasConfidence = typeof confidence === 'number' && Number.isFinite(confidence);

  return (
    <section
      aria-label={t('ai_trust.title', { defaultValue: 'How to trust this' })}
      className={clsx(
        'rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2.5 text-xs',
        className,
      )}
    >
      {/* Trust signal: how produced + data residency (+ confidence if real) */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 font-medium text-content-secondary">
          <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-oe-blue" aria-hidden="true" />
          {producedBy ??
            t('ai_trust.produced_generic', {
              defaultValue: 'AI-assisted - review before you rely on it.',
            })}
        </span>
        {hasConfidence && <ConfidenceBadge score={confidence as number} showScore />}
        <span className="inline-flex items-center gap-1 text-content-tertiary">
          <Lock className="h-3 w-3 shrink-0" aria-hidden="true" />
          {t('ai_trust.data_stays', { defaultValue: 'Your data stays in your project.' })}
        </span>
      </div>

      {/* Feedback verdict */}
      {showFeedback && (
        <div className="mt-2 border-t border-border-light pt-2">
          {recorded !== null && !open ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 font-medium text-semantic-success">
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                {recorded
                  ? t('ai_trust.marked_correct', { defaultValue: 'You marked this helpful' })
                  : t('ai_trust.marked_wrong', { defaultValue: 'You flagged this as off' })}
              </span>
              <button
                type="button"
                onClick={() => setOpen(true)}
                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-secondary"
              >
                <Pencil className="h-3 w-3" aria-hidden="true" />
                {t('ai_trust.change', { defaultValue: 'Change' })}
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <span className="font-medium text-content-secondary">
                {t('ai_trust.prompt', { defaultValue: 'Was this helpful?' })}
              </span>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                maxLength={2000}
                placeholder={t('ai_trust.note_placeholder', {
                  defaultValue: 'Optional: what was off, or what the right answer was?',
                })}
                aria-label={t('ai_trust.note_label', { defaultValue: 'Optional feedback note' })}
                className="w-full rounded-md border border-border bg-surface-primary px-2.5 py-1.5 text-xs text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
              />
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={mutation.isPending}
                  onClick={() => mutation.mutate(true)}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-md border border-semantic-success/40 bg-semantic-success-bg/60 px-2.5 py-1 font-semibold text-semantic-success transition-all',
                    'hover:bg-semantic-success-bg disabled:cursor-not-allowed disabled:opacity-50',
                  )}
                >
                  {mutation.isPending && mutation.variables === true ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  ) : (
                    <ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {t('ai_trust.yes', { defaultValue: 'Helpful' })}
                </button>
                <button
                  type="button"
                  disabled={mutation.isPending}
                  onClick={() => mutation.mutate(false)}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-md border border-semantic-error/40 bg-semantic-error-bg/60 px-2.5 py-1 font-semibold text-semantic-error transition-all',
                    'hover:bg-semantic-error-bg disabled:cursor-not-allowed disabled:opacity-50',
                  )}
                >
                  {mutation.isPending && mutation.variables === false ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  ) : (
                    <ThumbsDown className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {t('ai_trust.no', { defaultValue: 'Not right' })}
                </button>
                {recorded !== null && (
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      setNote('');
                    }}
                    className="inline-flex items-center rounded px-1.5 py-0.5 text-content-tertiary transition-colors hover:text-content-secondary"
                  >
                    {t('common.cancel', { defaultValue: 'Cancel' })}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default AITrustNote;
