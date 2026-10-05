// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The figures a learner types for a task (frontend design §4, NumbersCheck).
//
// Every number is parsed under the COURSE locale by `parseCourseNumber`, which
// refuses what it cannot read instead of guessing. A refusal shows an inline
// note in plain words: when the learner used the other decimal mark, the note
// says which one this course uses ("Use a comma for decimals in this course"),
// otherwise "This does not read as a number". A readable value echoes "Read as
// £2,433.12" under the field, so the learner sees how it was understood.
//
// The note shows after the field loses focus or after a press of Check, never
// while a half-typed "12," is on screen. Verdicts come from the last check and
// sit under each field with an icon and text, not colour alone; editing a field
// hides its verdict (the parent decides, it owns the attempt).
//
// The submit button is not here: TaskPanel owns the one Check press that saves
// every answer and runs the check, because a task may have no numbers at all.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Minus, X, AlertTriangle } from 'lucide-react';

import { courseDir, numberSeparators, parseCourseNumber } from './courseLocale';
import { formatCourseValue, parseIsoDate, renderCourseText } from './courseText';
import type { CheckField, ItemVerdict, NumbersCheckView } from './types';

/** Why a typed value was refused. */
export type TypedValueProblem = 'use_comma' | 'use_point' | 'unreadable';

export type TypedValue =
  | { status: 'empty' }
  | { status: 'ok'; value: string }
  | { status: 'error'; problem: TypedValueProblem };

/**
 * Read what a learner typed into a field, under the course locale. Numbers
 * become decimal strings; dates must be real `YYYY-MM-DD` days; text is
 * trimmed. Never guesses: a number that does not fit the locale is an error.
 */
export function readTypedValue(text: string, kind: CheckField['kind'], courseLocale: string): TypedValue {
  const trimmed = text.trim();
  if (trimmed.length === 0) return { status: 'empty' };
  if (kind === 'text') return { status: 'ok', value: trimmed };
  if (kind === 'date') {
    return parseIsoDate(trimmed) ? { status: 'ok', value: trimmed } : { status: 'error', problem: 'unreadable' };
  }
  const parsed = parseCourseNumber(trimmed, courseLocale);
  if (parsed !== null) return { status: 'ok', value: parsed };
  // Did the learner use the other decimal mark? Ask a locale that writes the
  // other one: if it reads the input, say which mark this course uses.
  const decimal = numberSeparators(courseLocale).decimal;
  if (decimal === ',' && trimmed.includes('.') && parseCourseNumber(trimmed, 'en-US') !== null) {
    return { status: 'error', problem: 'use_comma' };
  }
  if (decimal === '.' && trimmed.includes(',') && parseCourseNumber(trimmed, 'de-DE') !== null) {
    return { status: 'error', problem: 'use_point' };
  }
  return { status: 'error', problem: 'unreadable' };
}

/** The DOM id of a field's input, for focus and labels. */
export function trainerFieldInputId(checkId: string, key: string): string {
  return `oe-trainer-field-${checkId}-${key}`.replace(/[^A-Za-z0-9_-]/g, '_');
}

export interface NumbersCheckProps {
  check: NumbersCheckView;
  courseLocale: string;
  currency: string;
  /** The text in each field, by field key. */
  values: Record<string, string>;
  /** The verdict to show under each field; absent when there is none or the field changed since. */
  verdicts: Record<string, ItemVerdict | undefined>;
  /** Show every refusal now (after a press of Check), not only on blur. */
  showAllProblems: boolean;
  onChange: (key: string, text: string) => void;
}

export function NumbersCheck({
  check,
  courseLocale,
  currency,
  values,
  verdicts,
  showAllProblems,
  onChange,
}: NumbersCheckProps) {
  const { t } = useTranslation();
  const [blurred, setBlurred] = useState<Record<string, boolean>>({});
  const dir = courseDir(courseLocale);

  const problemText = (problem: TypedValueProblem): string => {
    switch (problem) {
      case 'use_comma':
        return t('trainer.check.use_comma', { defaultValue: 'Use a comma for decimals in this course' });
      case 'use_point':
        return t('trainer.check.use_point', { defaultValue: 'Use a point for decimals in this course' });
      case 'unreadable':
        return t('trainer.check.unreadable', { defaultValue: 'This does not read as a number' });
    }
  };

  const verdictLine = (verdict: ItemVerdict) => {
    switch (verdict) {
      case 'ok':
        return {
          icon: <Check size={14} strokeWidth={3} aria-hidden="true" />,
          cls: 'text-semantic-success',
          text: t('trainer.check.field_ok', { defaultValue: 'Matches' }),
        };
      case 'wrong':
        return {
          icon: <X size={14} strokeWidth={3} aria-hidden="true" />,
          cls: 'text-semantic-warning',
          text: t('trainer.check.field_wrong', { defaultValue: 'Does not match yet' }),
        };
      case 'missing':
        return {
          icon: <Minus size={14} strokeWidth={3} aria-hidden="true" />,
          cls: 'text-content-secondary',
          text: t('trainer.check.field_missing', { defaultValue: 'Missing' }),
        };
      case 'error':
        return {
          icon: <AlertTriangle size={14} strokeWidth={2.5} aria-hidden="true" />,
          cls: 'text-content-secondary',
          text: t('trainer.check.field_error', { defaultValue: 'Could not be checked this time. Check again.' }),
        };
    }
  };

  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0" data-testid={`trainer-numbers-${check.id}`}>
      <legend
        className="mb-1 p-0 text-sm font-semibold leading-relaxed text-content-primary"
        lang={courseLocale}
        dir={dir}
      >
        {renderCourseText(check.prompt, courseLocale)}
      </legend>
      {check.fields.map((field) => {
        const inputId = trainerFieldInputId(check.id, field.key);
        const text = values[field.key] ?? '';
        const typed = readTypedValue(text, field.kind, courseLocale);
        const showProblem = typed.status === 'error' && (showAllProblems || blurred[field.key] === true);
        const verdict = verdicts[field.key];
        const line = verdict ? verdictLine(verdict) : null;
        const echoId = `${inputId}-echo`;
        const verdictId = `${inputId}-verdict`;
        const described = [showProblem || typed.status === 'ok' ? echoId : null, line ? verdictId : null]
          .filter(Boolean)
          .join(' ');
        return (
          <div key={field.key} className="flex flex-col gap-1">
            <label htmlFor={inputId} className="text-sm font-medium text-content-primary" lang={courseLocale} dir={dir}>
              {renderCourseText(field.label, courseLocale)}
            </label>
            <input
              id={inputId}
              type={field.kind === 'date' ? 'date' : 'text'}
              inputMode={field.kind === 'date' || field.kind === 'text' ? undefined : 'decimal'}
              autoComplete="off"
              spellCheck={false}
              lang={courseLocale}
              value={text}
              onChange={(e) => onChange(field.key, e.target.value)}
              onBlur={() => setBlurred((b) => (b[field.key] ? b : { ...b, [field.key]: true }))}
              aria-invalid={showProblem || verdict === 'wrong' ? true : undefined}
              aria-describedby={described || undefined}
              data-field-key={field.key}
              className={[
                'min-h-[44px] w-full rounded-xl border bg-surface-primary px-3 font-mono text-base tabular-nums text-content-primary',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                showProblem
                  ? 'border-semantic-error'
                  : verdict === 'wrong'
                    ? 'border-semantic-warning'
                    : verdict === 'ok'
                      ? 'border-semantic-success'
                      : 'border-border',
              ].join(' ')}
            />
            {showProblem && typed.status === 'error' ? (
              <p id={echoId} className="m-0 text-xs font-medium text-semantic-error" data-testid="trainer-field-problem">
                {problemText(typed.problem)}
              </p>
            ) : typed.status === 'ok' && field.kind !== 'text' ? (
              <p id={echoId} className="m-0 text-xs text-content-secondary" data-testid="trainer-field-echo">
                {t('trainer.check.read_as', {
                  defaultValue: 'Read as {{value}}',
                  value: formatCourseValue(typed.value, field.kind, { locale: courseLocale, currency }, field.currency),
                })}
              </p>
            ) : null}
            {line && (
              <p
                id={verdictId}
                className={`m-0 inline-flex items-center gap-1.5 text-xs font-semibold ${line.cls}`}
                data-testid="trainer-field-verdict"
                data-verdict={verdict}
              >
                {line.icon}
                {line.text}
              </p>
            )}
          </div>
        );
      })}
    </fieldset>
  );
}
