// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// AI Estimate Builder — conversational intake v2 (per-question control).
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Renders one IntakeQuestion as the right editable control for its kind:
// number/length -> numeric input with a unit suffix; choice -> chips;
// bool -> a yes/no toggle pair. Both the AI and offline paths reuse this.

import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';
import clsx from 'clsx';
import type { IntakeQuestion } from './types';

interface QuestionControlProps {
  question: IntakeQuestion;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
}

export function QuestionControl({ question, value, onChange, disabled }: QuestionControlProps) {
  const { t } = useTranslation();
  const inputId = useId();
  const whyId = useId();

  // The prompt is EITHER an LLM-phrased sentence (AI path) OR the literal i18n
  // key `aiest.q.<param_key>` (offline / no-key path). Translate the key form
  // with a humanized fallback so a missing key never leaks raw to the user;
  // pass an LLM sentence through unchanged.
  const label = question.prompt.startsWith('aiest.')
    ? t(question.prompt, { defaultValue: humanizeParamKey(question.param_key) })
    : question.prompt;
  // `why` is an i18n key carrying the "unlocks" justification; degrade a
  // missing key to empty (no tooltip) rather than showing the raw key.
  const why = question.why
    ? t(question.why, { defaultValue: question.why.startsWith('aiest.') ? '' : question.why })
    : '';

  const renderControl = () => {
    if (question.kind === 'bool') {
      const current = value === true || value === 'true';
      const isSet = value !== undefined && value !== null && value !== '';
      return (
        <div className="inline-flex rounded-lg border border-border bg-surface-primary p-0.5" role="group" aria-labelledby={inputId}>
          {[
            { v: true, key: 'aiest.answer.yes', fb: 'Yes' },
            { v: false, key: 'aiest.answer.no', fb: 'No' },
          ].map((opt) => {
            const active = isSet && current === opt.v;
            return (
              <button
                key={String(opt.v)}
                type="button"
                disabled={disabled}
                aria-pressed={active}
                onClick={() => onChange(opt.v)}
                className={clsx(
                  'h-8 min-w-[3.5rem] rounded-md px-3 text-sm font-medium transition',
                  active
                    ? 'bg-oe-blue text-content-inverse shadow-xs'
                    : 'text-content-secondary hover:bg-surface-secondary',
                  disabled && 'opacity-50',
                )}
              >
                {t(opt.key, { defaultValue: opt.fb })}
              </button>
            );
          })}
        </div>
      );
    }

    if (question.kind === 'choice') {
      return (
        <div className="flex flex-wrap gap-1.5" role="group" aria-labelledby={inputId}>
          {question.options.map((opt) => {
            const active = value === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                disabled={disabled}
                aria-pressed={active}
                onClick={() => onChange(opt.value)}
                className={clsx(
                  'inline-flex h-8 items-center rounded-full border px-3 text-sm font-medium transition',
                  active
                    ? 'border-oe-blue bg-oe-blue text-content-inverse shadow-xs'
                    : 'border-border bg-surface-primary text-content-secondary hover:border-oe-blue/50 hover:text-content-primary',
                  disabled && 'opacity-50',
                )}
              >
                {t(opt.label_key, { defaultValue: opt.value })}
              </button>
            );
          })}
        </div>
      );
    }

    // number | length
    return (
      <div className="relative inline-flex items-center">
        <input
          id={inputId}
          type="number"
          inputMode="decimal"
          step="any"
          disabled={disabled}
          value={value === undefined || value === null ? '' : String(value)}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={why ? whyId : undefined}
          className={clsx(
            'h-9 w-40 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary',
            'focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30',
            question.unit && 'pr-12',
            disabled && 'opacity-50',
          )}
          placeholder={question.unit ?? ''}
        />
        {question.unit && (
          <span className="pointer-events-none absolute right-3 text-xs font-medium text-content-tertiary">
            {question.unit}
          </span>
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-start gap-1.5">
        <label id={inputId} htmlFor={question.kind === 'number' || question.kind === 'length' ? inputId : undefined} className="text-sm font-medium text-content-primary">
          {label}
          {question.required && <span className="ml-0.5 text-semantic-error" aria-hidden>*</span>}
        </label>
        {why && (
          <span className="group relative inline-flex" tabIndex={0} aria-label={why}>
            <Info size={13} className="mt-0.5 text-content-tertiary" />
            <span
              id={whyId}
              role="tooltip"
              className="pointer-events-none absolute left-5 top-0 z-20 hidden w-56 rounded-lg border border-border bg-surface-primary px-2.5 py-1.5 text-xs text-content-secondary shadow-lg group-hover:block group-focus-within:block"
            >
              {why}
            </span>
          </span>
        )}
      </div>
      {renderControl()}
    </div>
  );
}

// Turn a snake_case param key into a readable label when no translation exists
// (e.g. "gross_floor_area_m2" -> "Gross floor area m2"). Mirrors the helper in
// ParameterSheet.tsx so an untranslated offline question never shows a raw key.
function humanizeParamKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .trim()
    .replace(/^./, (c) => c.toUpperCase());
}
