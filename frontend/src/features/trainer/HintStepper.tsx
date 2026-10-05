// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Hints, one at a time (frontend design §4, TaskPanel; decision 15 and 30).
//
// The server records which hints were revealed: the task view carries only
// those (`hints`) plus `hints_total`, and "Show a hint" posts the reveal, after
// which the refetched task carries the next one. Hints cost nothing. Nothing
// here counts them against the learner, warns before showing one or styles
// them as a penalty: a hint is a normal part of learning.

import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Lightbulb, Loader2 } from 'lucide-react';

import { courseDir } from './courseLocale';
import { renderCourseText } from './courseText';
import { useRevealTrainerHint } from './queries';

export interface HintStepperProps {
  taskId: string;
  /** The hints revealed so far, in order, in the course language. */
  hints: string[];
  total: number;
  courseLocale: string;
}

export function HintStepper({ taskId, hints, total, courseLocale }: HintStepperProps) {
  const { t } = useTranslation();
  const reveal = useRevealTrainerHint(taskId);
  const lastRef = useRef<HTMLLIElement>(null);
  const askedRef = useRef(false);
  // A second press before React re-renders must not post twice.
  const inFlightRef = useRef(false);
  const shown = hints.slice(0, Math.max(total, hints.length));

  // After a press, move focus to the hint that just arrived, so a keyboard or
  // screen reader user lands on it instead of on a button that moved.
  useEffect(() => {
    if (askedRef.current && lastRef.current) {
      askedRef.current = false;
      lastRef.current.focus();
    }
  }, [hints.length]);

  if (total <= 0) return null;
  const more = shown.length < total;

  return (
    <section className="flex flex-col gap-2.5 rounded-2xl bg-surface-elevated px-5 py-4" data-testid="trainer-hints">
      {shown.length > 0 && (
        <h3 className="m-0 flex items-center gap-2 text-sm font-bold text-content-primary" data-testid="trainer-hint-count">
          <Lightbulb size={16} className="text-oe-blue" aria-hidden="true" />
          {t('trainer.panel.hint_count', { defaultValue: 'Hint {{n}} of {{total}}', n: shown.length, total })}
        </h3>
      )}
      {shown.length > 0 && (
        <ol className="m-0 flex list-none flex-col gap-2 p-0" aria-live="polite">
          {shown.map((hint, i) => (
            <li
              key={i}
              ref={i === shown.length - 1 ? lastRef : undefined}
              tabIndex={-1}
              className="rounded-xl bg-oe-blue-subtle px-3 py-2 text-sm leading-relaxed text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
              data-testid="trainer-hint"
            >
              <span className="sr-only">
                {t('trainer.panel.hint_count', { defaultValue: 'Hint {{n}} of {{total}}', n: i + 1, total })}:{' '}
              </span>
              <span lang={courseLocale} dir={courseDir(courseLocale)}>
                {renderCourseText(hint, courseLocale)}
              </span>
            </li>
          ))}
        </ol>
      )}
      {more && (
        <button
          type="button"
          className="inline-flex min-h-[44px] items-center gap-2 self-start rounded-full border border-border px-4 text-sm font-semibold text-oe-blue-text hover:bg-oe-blue-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oe-blue"
          aria-busy={reveal.isPending || undefined}
          onClick={() => {
            if (inFlightRef.current) return;
            inFlightRef.current = true;
            askedRef.current = true;
            reveal.mutate(undefined, {
              onSettled: () => {
                inFlightRef.current = false;
              },
            });
          }}
          data-testid="trainer-hint-next"
        >
          {reveal.isPending ? (
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          ) : (
            <Lightbulb size={14} aria-hidden="true" />
          )}
          {shown.length === 0
            ? t('trainer.panel.hint_show', { defaultValue: 'Show a hint' })
            : t('trainer.panel.hint_next', { defaultValue: 'Show the next hint' })}
        </button>
      )}
      {reveal.isError && (
        <p role="alert" className="m-0 text-xs text-semantic-error">
          {t('trainer.panel.hint_error', { defaultValue: 'The hint did not load. Press the button again.' })}
        </p>
      )}
    </section>
  );
}
