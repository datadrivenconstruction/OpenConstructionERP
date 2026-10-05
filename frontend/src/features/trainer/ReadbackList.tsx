// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "What the app shows now": the live ERP values behind a task (frontend
// design §4, NumbersCheck readback). Each line is match, mismatch (with the
// value the project holds) or unknown. The expected value is never shown; the
// API does not send it.
//
// An unknown may carry a `reason_key` (decision 40) that tells the learner what
// to do, e.g. open the levelling view. Keys are translated through a literal
// map, never `t(reasonKey)`, so the i18n computed-key gate stays green; an
// unmapped key falls back to "Not readable yet".
//
// Only a change in the summary is announced (polite), never every refetch.

import { useTranslation } from 'react-i18next';
import { Check, CircleHelp, X } from 'lucide-react';

import { courseDir } from './courseLocale';
import { formatCourseValue, renderCourseText } from './courseText';
import type { ReadbackItemView, ReadbackValue } from './types';

export interface ReadbackListProps {
  items: ReadbackItemView[];
  values: ReadbackValue[] | undefined;
  courseLocale: string;
  currency: string;
  /** True while the first read is in flight. */
  loading?: boolean;
}

function useReasonText(): (key: string | null | undefined) => string | null {
  const { t } = useTranslation();
  return (key) => {
    switch (key) {
      case 'trainer.readback.open_leveling':
        return t('trainer.readback.open_leveling', {
          defaultValue: 'Open the levelling view and press Compute Leveling, then this line can be read.',
        });
      default:
        return null;
    }
  };
}

export function ReadbackList({ items, values, courseLocale, currency, loading = false }: ReadbackListProps) {
  const { t } = useTranslation();
  const reasonText = useReasonText();
  if (items.length === 0) return null;
  const byId = new Map((values ?? []).map((v) => [v.id, v]));
  const matched = items.filter((item) => byId.get(item.id)?.state === 'match').length;
  const ctx = { locale: courseLocale, currency };

  return (
    <section
      className="flex flex-col gap-2.5 rounded-2xl bg-surface-elevated px-5 py-4"
      aria-labelledby="oe-trainer-readback-title"
      data-testid="trainer-readback"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h3 id="oe-trainer-readback-title" className="m-0 text-sm font-bold text-content-primary">
          {t('trainer.check.readback_title', { defaultValue: 'What the app shows now' })}
        </h3>
        <span className="text-xs text-content-secondary" aria-live="polite" data-testid="trainer-readback-summary">
          {loading
            ? t('trainer.state.loading', { defaultValue: 'Loading your course' })
            : t('trainer.readback.summary', {
                defaultValue: '{{done}} of {{total}} match',
                done: matched,
                total: items.length,
              })}
        </span>
      </div>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {items.map((item) => {
          const value = byId.get(item.id);
          const state = value?.state ?? 'unknown';
          const reason = state === 'unknown' ? reasonText(value?.reason_key) : null;
          return (
            <li
              key={item.id}
              className="flex items-start gap-2.5 border-b border-border-light pb-2 last:border-b-0 last:pb-0"
              data-testid={`trainer-readback-${item.id}`}
              data-state={state}
            >
              <span
                className={[
                  'mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full',
                  state === 'match'
                    ? 'bg-semantic-success text-white'
                    : state === 'mismatch'
                      ? 'bg-semantic-warning text-white'
                      : 'bg-surface-tertiary text-content-secondary',
                ].join(' ')}
                aria-hidden="true"
              >
                {state === 'match' ? (
                  <Check size={12} strokeWidth={3} />
                ) : state === 'mismatch' ? (
                  <X size={12} strokeWidth={3} />
                ) : (
                  <CircleHelp size={12} strokeWidth={2.5} />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm text-content-primary" lang={courseLocale} dir={courseDir(courseLocale)}>
                  {renderCourseText(item.what, courseLocale)}
                </div>
                <div className="text-xs leading-relaxed text-content-secondary">
                  {state === 'match' && t('trainer.check.readback_match', { defaultValue: 'Matches your answer' })}
                  {state === 'mismatch' &&
                    (value?.app_value
                      ? t('trainer.check.readback_mismatch', {
                          defaultValue: 'Your project shows {{value}}',
                          value: formatCourseValue(value.app_value, value.kind ?? item.kind, ctx),
                        })
                      : t('trainer.check.field_wrong', { defaultValue: 'Does not match yet' }))}
                  {state === 'unknown' &&
                    (reason ?? t('trainer.check.readback_unknown', { defaultValue: 'Not readable yet' }))}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
