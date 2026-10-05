// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Why a figure is wrong, in plain words (frontend design §4, Diagnosis).
//
// The message and the related values are course content, written by the
// course author in the course language. A related value shows its `label`;
// its `name` is a ledger key and never reaches the DOM. The card shows the learner's mistake
// and never the expected value: the API does not send one, and there is no
// signed delta either (backend `Diagnosis` docstring: with the observed value
// it would give the answer away), so the headline is always "What happened".

import { useTranslation } from 'react-i18next';
import { AlertCircle } from 'lucide-react';

import { courseDir } from './courseLocale';
import { formatCourseValue, renderCourseText } from './courseText';
import type { Diagnosis as DiagnosisData } from './types';

export interface DiagnosisProps {
  diagnosis: DiagnosisData;
  courseLocale: string;
  currency: string;
  /** The figure it is about, in the course language (a field label or a readback line). */
  subject?: string | null;
}

export function Diagnosis({ diagnosis, courseLocale, currency, subject }: DiagnosisProps) {
  const { t } = useTranslation();
  const ctx = { locale: courseLocale, currency };
  // `name` is a ledger key, never shown. A row without a label is hidden.
  const related = diagnosis.related.filter((item) => item.label !== null && item.label.trim() !== '');
  return (
    <section
      className="oe-trainer-pop flex flex-col gap-2.5 rounded-2xl border-2 border-semantic-warning bg-surface-elevated px-5 py-4"
      data-testid="trainer-diagnosis"
      data-diagnosis-id={diagnosis.id}
    >
      <div className="flex items-center gap-2 text-base font-bold text-semantic-warning">
        <AlertCircle size={18} strokeWidth={2.4} aria-hidden="true" />
        <span>{t('trainer.check.diagnosis_title', { defaultValue: 'What happened' })}</span>
        {subject ? (
          <span className="font-semibold text-content-secondary" lang={courseLocale} dir={courseDir(courseLocale)}>
            · {subject}
          </span>
        ) : null}
      </div>
      <div lang={courseLocale} dir={courseDir(courseLocale)} className="flex flex-col gap-2">
        <p className="m-0 text-sm leading-relaxed text-content-primary">
          {renderCourseText(diagnosis.message, courseLocale)}
        </p>
        {related.length > 0 && (
          <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm" data-testid="trainer-diagnosis-related">
            {related.map((item, i) => (
              <div key={i} className="contents">
                <dt className="text-content-secondary">{renderCourseText(item.label ?? '', courseLocale)}</dt>
                <dd className="m-0 text-end font-mono tabular-nums text-content-primary">
                  {formatCourseValue(item.value, item.kind, ctx)}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      <p className="m-0 text-xs leading-relaxed text-content-secondary">
        {t('trainer.check.try_again', {
          defaultValue: 'Change the figure and check again. A changed answer always clears the last check.',
        })}
      </p>
    </section>
  );
}
