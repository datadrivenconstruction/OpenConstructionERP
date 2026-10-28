// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// FormPreview - a live, interactive preview of a template as the end user will
// see it, driven by the same field controls, conditional-visibility resolver and
// formula engine the real filler uses. Kept read-through: it holds its own throw-
// away answer state so the builder can watch branching and computed fields react,
// without touching any submission.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FieldControl } from './FormFiller';
import type { AnswerMap, AnswerValue, FormFieldDef } from './api';
import {
  LAYOUT_TYPES,
  COMPUTED_TYPES,
  resolveVisibility,
  computeFormulas,
  applyDefaults,
} from './fieldTypes';

export interface FormPreviewProps {
  fields: FormFieldDef[];
}

export function FormPreview({ fields }: FormPreviewProps) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<AnswerMap>({});

  // Seed configured defaults so the preview opens as the filler would.
  const seeded = useMemo(() => applyDefaults(fields, answers), [fields, answers]);
  const visibility = useMemo(() => resolveVisibility(fields, seeded), [fields, seeded]);
  const computed = useMemo(() => computeFormulas(fields, seeded), [fields, seeded]);

  const setAnswer = (key: string, value: AnswerValue) =>
    setAnswers((prev) => ({ ...prev, [key]: value }));

  const fillable = fields.filter((f) => !LAYOUT_TYPES.has(f.type));
  if (fillable.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-content-tertiary">
        {t('forms.preview_empty', { defaultValue: 'Add a field to see the form preview.' })}
      </p>
    );
  }

  return (
    <div className="space-y-3.5">
      {fields.map((field, idx) => {
        const state = field.key ? visibility[field.key] : undefined;
        if (state && !state.visible) return null;
        if (LAYOUT_TYPES.has(field.type)) {
          return (
            <h4
              key={field.key || idx}
              className="border-b border-border-light pb-1 pt-1 text-xs font-semibold text-content-primary"
            >
              {field.label || t('forms.untitled_section', { defaultValue: 'Section' })}
            </h4>
          );
        }
        const isFormula = COMPUTED_TYPES.has(field.type);
        const required = state ? state.required : field.required;
        const value = isFormula ? (computed[field.key] ?? null) : seeded[field.key] ?? null;
        return (
          <div key={field.key || idx}>
            <label className="mb-1 flex items-start gap-1 text-xs font-medium text-content-secondary">
              <span>{field.label || t('forms.untitled_field', { defaultValue: 'Untitled' })}</span>
              {required && <span className="text-semantic-error">*</span>}
            </label>
            {field.help_text && (
              <p className="mb-1 text-[11px] text-content-tertiary">{field.help_text}</p>
            )}
            <FieldControl field={field} value={value} onChange={(v) => setAnswer(field.key, v)} />
          </div>
        );
      })}
    </div>
  );
}
