// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The part of a form that makes a drawing number: one field for each part of
// the scheme a person types, the request the numbering endpoints read from
// those fields, and the box that shows the number the server would hand out.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';

import { fmtList } from '@/shared/lib/formatters';

import { designKeys, previewNumber, type NumberRequest, type NumberingField } from './api';
import type { DesignContext } from './DesignBits';
import { str, type FieldSpec, type FormValues } from './FormDialog';
import { refusalText } from './hooks';
import { catalogueLabel, errorText, fieldLabel, ui, type LabelContext, type TFn } from './labels';

const PART = 'part_';

/** The form fields for the parts of a number a person types, a list where the scheme has one. */
export function numberPartFields(labels: LabelContext, fields: NumberingField[]): FieldSpec[] {
  return fields.map((f) => ({
    name: `${PART}${f.code}`,
    label: fieldLabel(labels, f),
    type: f.code_list === 'free' ? ('text' as const) : ('select' as const),
    options:
      f.code_list === 'free'
        ? undefined
        : f.code_list.map((c) => ({
            value: c.code,
            label: `${c.code} ${catalogueLabel(labels, { key: c.label_key, labels: c.labels, code: c.code })}`,
          })),
  }));
}

/** What the numbering endpoints need, read from a form's values. */
export function numberRequest(values: FormValues): NumberRequest {
  const fields: Record<string, string> = {};
  for (const [name, value] of Object.entries(values)) {
    if (name.startsWith(PART) && typeof value === 'string' && value.trim()) fields[name.slice(PART.length)] = value.trim();
  }
  return {
    role_id: str(values, 'role_id') || null,
    phase_code: str(values, 'phase_code') || null,
    sheet_size: str(values, 'sheet_size') || null,
    wbs_node_id: str(values, 'wbs_node_id') || null,
    fields,
  };
}

function useSettled<T>(value: T, delayMs = 350): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return settled;
}

/** The number the drawing will get, asked from the server as the form changes; nothing is taken yet. */
export function NumberPreviewBox({ ctx, values }: { ctx: DesignContext; values: FormValues }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const request = useSettled(JSON.stringify(numberRequest(values)));
  const preview = useQuery({
    queryKey: [...designKeys.list(ctx.projectId, 'number-preview'), request],
    queryFn: () => previewNumber(ctx.projectId, JSON.parse(request) as NumberRequest),
    retry: false,
  });
  if (str(values, 'number').trim()) return null;
  if (preview.isError) {
    return (
      <p role="alert" className="text-sm text-semantic-error" data-testid="number-preview-failed">
        {refusalText(t, preview.error)}
      </p>
    );
  }
  const data = preview.data;
  const fieldName = (code: string) => {
    const field = ctx.setup.scheme.fields.find((f) => f.code === code);
    return field ? fieldLabel(ctx.labels, field) : code;
  };
  return (
    <div className="rounded-md bg-surface-secondary p-3 text-sm" data-testid="number-preview">
      <p className="text-xs text-content-secondary">{ui(t, 'design.ui.drawings.next_number')}</p>
      <p className="font-mono text-base font-semibold text-content-primary">{data ? data.number : ui(t, 'design.ui.loading')}</p>
      {data && data.missing.length > 0 && (
        <p className="mt-1 text-xs text-semantic-warning" data-testid="number-missing">
          {ui(t, 'design.ui.drawings.number_missing', { fields: fmtList(data.missing.map(fieldName)) })}
        </p>
      )}
      {data && data.missing.length === 0 && !data.validation.valid && (
        <ul className="ml-4 mt-1 list-disc text-xs text-semantic-error">
          {data.validation.issues.map((issue, i) => (
            <li key={`${issue.code}-${i}`}>
              {issue.field && <span className="font-medium">{fieldName(issue.field)}: </span>}
              {errorText(t, issue.code)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
