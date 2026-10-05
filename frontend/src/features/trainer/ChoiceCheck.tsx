// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A trace or explain question (frontend design §4, ChoiceCheck).
//
// The options never carry `correct`: picking one saves it with the task's other
// answers and runs the check (TaskPanel does both), and the check answers with
// a verdict and the chosen option's feedback. A wrong pick shows its feedback
// and the learner picks again; a right pick closes the question, and the
// options turn into a plain list with the chosen one marked, so no button is
// left on screen that does nothing.

import { useTranslation } from 'react-i18next';
import { Check, Loader2, X } from 'lucide-react';

import { courseDir } from './courseLocale';
import { renderCourseText } from './courseText';
import type { ChoiceCheckView, FieldResult } from './types';

/** The DOM id of a question's heading; focus lands there after a pick is checked. */
export function trainerChoiceHeadingId(checkId: string): string {
  return `oe-trainer-choice-${checkId}`.replace(/[^A-Za-z0-9_-]/g, '_');
}

export interface ChoiceCheckProps {
  check: ChoiceCheckView;
  courseLocale: string;
  /** The option the learner holds now (saved or just picked), or null. */
  chosen: number | null;
  /** The option being saved and checked right now, or null. */
  pendingIndex: number | null;
  /** The check's verdict on this question, only when it is about `chosen`. */
  result: FieldResult | null;
  onPick: (optionIndex: number) => void;
}

export function ChoiceCheck({ check, courseLocale, chosen, pendingIndex, result, onPick }: ChoiceCheckProps) {
  const { t } = useTranslation();
  const dir = courseDir(courseLocale);
  const title =
    check.kind === 'trace'
      ? t('trainer.trace.title', { defaultValue: 'Trace' })
      : t('trainer.explain.title', { defaultValue: 'Explain' });
  const verdict = result?.verdict ?? null;
  const closed = verdict === 'ok';
  const headingId = trainerChoiceHeadingId(check.id);

  return (
    <section
      className="oe-trainer-pop flex flex-col gap-3 rounded-2xl bg-surface-elevated px-5 py-4"
      aria-labelledby={headingId}
      data-testid={`trainer-choice-${check.id}`}
      data-kind={check.kind}
    >
      <div className="flex flex-col gap-1">
        <span className="text-xs font-bold uppercase tracking-wider text-content-secondary">{title}</span>
        <h3
          id={headingId}
          tabIndex={-1}
          className="m-0 text-base font-bold leading-snug text-content-primary focus:outline-none"
          lang={courseLocale}
          dir={dir}
        >
          {renderCourseText(check.prompt, courseLocale)}
        </h3>
      </div>

      {closed ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-0" lang={courseLocale} dir={dir}>
          {check.options.map((option) => {
            const picked = option.index === chosen;
            return (
              <li
                key={option.index}
                className={[
                  'rounded-xl border-[1.5px] px-3.5 py-3 text-sm leading-relaxed',
                  picked
                    ? 'border-semantic-success bg-semantic-success-bg font-semibold text-content-primary'
                    : 'border-border-light text-content-secondary',
                ].join(' ')}
                data-picked={picked || undefined}
              >
                {picked && <Check size={14} strokeWidth={3} className="me-1.5 inline text-semantic-success" aria-hidden="true" />}
                {renderCourseText(option.text, courseLocale)}
              </li>
            );
          })}
        </ul>
      ) : (
        <div role="group" aria-labelledby={headingId} className="flex flex-col gap-2" lang={courseLocale} dir={dir}>
          {check.options.map((option) => {
            const picked = option.index === chosen;
            const pending = option.index === pendingIndex;
            const wrong = picked && verdict === 'wrong';
            return (
              <button
                key={option.index}
                type="button"
                aria-pressed={picked}
                aria-busy={pending || undefined}
                onClick={() => {
                  if (pendingIndex !== null) return;
                  onPick(option.index);
                }}
                className={[
                  'flex min-h-[44px] w-full items-start gap-2 rounded-xl border-[1.5px] px-3.5 py-3 text-start text-sm leading-relaxed text-content-primary',
                  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oe-blue',
                  wrong
                    ? 'border-semantic-warning bg-semantic-warning-bg'
                    : picked
                      ? 'border-oe-blue bg-oe-blue-subtle'
                      : 'border-border bg-surface-primary hover:border-oe-blue',
                ].join(' ')}
                data-testid="trainer-choice-option"
              >
                {pending && <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin" aria-hidden="true" />}
                <span>{renderCourseText(option.text, courseLocale)}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Always mounted, so the verdict of a pick is read out. */}
      <div aria-live="polite" data-testid="trainer-choice-live">
        {verdict === 'ok' || verdict === 'wrong' ? (
          <div
            className={`flex flex-col gap-1 text-sm leading-relaxed ${verdict === 'ok' ? 'text-semantic-success' : 'text-semantic-warning'}`}
            data-testid="trainer-choice-verdict"
            data-verdict={verdict}
          >
            <span className="inline-flex items-center gap-1.5 font-bold">
              {verdict === 'ok' ? (
                <Check size={14} strokeWidth={3} aria-hidden="true" />
              ) : (
                <X size={14} strokeWidth={3} aria-hidden="true" />
              )}
              {verdict === 'ok'
                ? t('trainer.choice.correct', { defaultValue: 'Right' })
                : t('trainer.choice.wrong', { defaultValue: 'Not this one' })}
            </span>
            {result?.feedback ? (
              <p className="m-0 text-content-primary" lang={courseLocale} dir={dir}>
                {renderCourseText(result.feedback, courseLocale)}
              </p>
            ) : null}
          </div>
        ) : verdict === 'error' ? (
          <p className="m-0 text-sm text-content-secondary" data-testid="trainer-choice-verdict" data-verdict="error">
            {t('trainer.check.field_error', { defaultValue: 'Could not be checked this time. Check again.' })}
          </p>
        ) : null}
      </div>
    </section>
  );
}
