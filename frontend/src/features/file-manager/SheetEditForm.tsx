// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Edit form for one drawing sheet's title block fields.
 *
 * The register reads number, title, revision, scale and date off the page, and
 * a reading can be wrong or missing. This form is how somebody puts it right.
 * It sends only the fields that changed, and a cleared field as `null`, so the
 * backend never stores an empty string a revision stack could key on.
 *
 * The limits mirror `SheetUpdate` on the backend, so a value the server would
 * refuse is caught here with a message next to the field instead of a 422.
 */
import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';
import type { SheetPatch } from './api';
import type { SheetRow } from './types';

type Translate = ReturnType<typeof useTranslation>['t'];

type FieldKey = 'sheet_number' | 'sheet_title' | 'revision' | 'discipline' | 'scale' | 'revision_date';

/** Same ceilings as the backend schema's `max_length`. */
const MAX_LENGTH: Record<Exclude<FieldKey, 'revision_date'>, number> = {
  sheet_number: 100,
  sheet_title: 500,
  revision: 50,
  discipline: 100,
  scale: 50,
};

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** The date part of a stored instant, in the shape `<input type="date">` takes. */
function toDateInput(value: string | null): string {
  if (!value) return '';
  return value.slice(0, 10);
}

function initialValues(sheet: SheetRow): Record<FieldKey, string> {
  return {
    sheet_number: sheet.sheet_number ?? '',
    sheet_title: sheet.sheet_title ?? '',
    revision: sheet.revision ?? '',
    discipline: sheet.discipline ?? '',
    scale: sheet.scale ?? '',
    revision_date: toDateInput(sheet.revision_date),
  };
}

/** Validate the form. Returns one message per invalid field. */
export function validateSheetForm(
  values: Record<FieldKey, string>,
  t: Translate,
): Partial<Record<FieldKey, string>> {
  const errors: Partial<Record<FieldKey, string>> = {};
  for (const [key, max] of Object.entries(MAX_LENGTH) as [keyof typeof MAX_LENGTH, number][]) {
    if (values[key].trim().length > max) {
      errors[key] = t('sheets.edit_too_long', { defaultValue: 'At most {{max}} characters.', max });
    }
  }
  const date = values.revision_date.trim();
  if (date && (!DATE_RE.test(date) || Number.isNaN(new Date(`${date}T00:00:00Z`).getTime()))) {
    errors.revision_date = t('sheets.edit_date_invalid', { defaultValue: 'Enter a complete date.' });
  }
  return errors;
}

/** Only the fields that differ from the sheet, a blank one as `null`. */
export function buildSheetPatch(sheet: SheetRow, values: Record<FieldKey, string>): SheetPatch {
  const before = initialValues(sheet);
  const patch: SheetPatch = {};
  for (const key of Object.keys(before) as FieldKey[]) {
    const next = values[key].trim();
    if (next === before[key].trim()) continue;
    patch[key] = next === '' ? null : next;
  }
  return patch;
}

export interface SheetEditFormProps {
  sheet: SheetRow;
  /** Disciplines already used on the project, offered as suggestions. */
  disciplines: string[];
  saving: boolean;
  error: string | null;
  onSubmit: (patch: SheetPatch) => void;
  onCancel: () => void;
}

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function SheetEditForm({ sheet, disciplines, saving, error, onSubmit, onCancel }: SheetEditFormProps) {
  const { t } = useTranslation();
  const [values, setValues] = useState<Record<FieldKey, string>>(() => initialValues(sheet));
  const [submitted, setSubmitted] = useState(false);

  const errors = useMemo(() => validateSheetForm(values, t), [values, t]);
  const patch = useMemo(() => buildSheetPatch(sheet, values), [sheet, values]);
  const dirty = Object.keys(patch).length > 0;
  const listId = `sheet-disciplines-${sheet.id}`;

  const fields: { key: FieldKey; label: string; type?: string; list?: string }[] = [
    { key: 'sheet_number', label: t('sheets.col_number', { defaultValue: 'Sheet #' }) },
    { key: 'sheet_title', label: t('sheets.col_title', { defaultValue: 'Title' }) },
    { key: 'revision', label: t('sheets.col_revision', { defaultValue: 'Rev' }) },
    { key: 'revision_date', label: t('sheets.col_issue_date', { defaultValue: 'Issue Date' }), type: 'date' },
    { key: 'discipline', label: t('sheets.col_discipline', { defaultValue: 'Discipline' }), list: listId },
    { key: 'scale', label: t('sheets.col_scale', { defaultValue: 'Scale' }) },
  ];

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    if (Object.keys(errors).length > 0 || !dirty) return;
    onSubmit(patch);
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-3">
      <p className="text-2xs text-content-tertiary">
        {t('sheets.edit_hint', {
          defaultValue:
            'Correct anything that was read wrongly from the drawing. Changing the number or revision moves the sheet to its place in the revision stack.',
        })}
      </p>
      {fields.map((f) => {
        const id = `sheet-edit-${f.key}`;
        const fieldError = submitted || values[f.key] !== initialValues(sheet)[f.key] ? errors[f.key] : undefined;
        return (
          <div key={f.key} className="flex flex-col gap-1">
            <label htmlFor={id} className="text-2xs uppercase tracking-wider text-content-tertiary">
              {f.label}
            </label>
            <input
              id={id}
              type={f.type ?? 'text'}
              list={f.list}
              value={values[f.key]}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              aria-invalid={fieldError ? true : undefined}
              aria-describedby={fieldError ? `${id}-error` : undefined}
              className={inputCls}
            />
            {fieldError && (
              <p id={`${id}-error`} className="text-2xs text-semantic-error">
                {fieldError}
              </p>
            )}
          </div>
        );
      })}
      <datalist id={listId}>
        {disciplines.map((d) => (
          <option key={d} value={d} />
        ))}
      </datalist>

      {error && (
        <p
          role="alert"
          className="rounded-lg border border-semantic-error/30 bg-semantic-error/5 px-3 py-2 text-xs text-semantic-error"
        >
          {t('sheets.edit_failed', { defaultValue: 'The changes could not be saved.' })} {error}
        </p>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={saving}>
          {t('sheets.edit_cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button type="submit" variant="primary" loading={saving} disabled={!dirty}>
          {t('sheets.edit_save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </form>
  );
}
