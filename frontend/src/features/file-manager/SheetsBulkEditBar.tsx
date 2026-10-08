// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';
import type { SheetBulkPatch } from './api';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

type BulkKey = 'discipline' | 'revision' | 'revision_date' | 'scale';

/**
 * The fields filled in, trimmed. A field left empty is not part of the edit,
 * so a bulk edit never clears a value on the sheets it touches.
 */
export function buildBulkPatch(values: Record<BulkKey, string>): SheetBulkPatch {
  const patch: SheetBulkPatch = {};
  for (const key of Object.keys(values) as BulkKey[]) {
    const value = values[key].trim();
    if (value) patch[key] = value;
  }
  return patch;
}

interface SheetsBulkEditBarProps {
  selectedCount: number;
  disciplines: string[];
  saving: boolean;
  error: string | null;
  onApply: (patch: SheetBulkPatch) => void;
  onClear: () => void;
}

/** Sets one discipline, revision, issue date or scale on every selected sheet. */
export function SheetsBulkEditBar({
  selectedCount,
  disciplines,
  saving,
  error,
  onApply,
  onClear,
}: SheetsBulkEditBarProps) {
  const { t } = useTranslation();
  const [values, setValues] = useState<Record<BulkKey, string>>({
    discipline: '',
    revision: '',
    revision_date: '',
    scale: '',
  });
  const patch = buildBulkPatch(values);
  const empty = Object.keys(patch).length === 0;

  const fields: { key: BulkKey; label: string; type?: string; list?: string }[] = [
    { key: 'discipline', label: t('sheets.col_discipline', { defaultValue: 'Discipline' }), list: 'sheets-bulk-disciplines' },
    { key: 'revision', label: t('sheets.col_revision', { defaultValue: 'Rev' }) },
    { key: 'revision_date', label: t('sheets.col_issue_date', { defaultValue: 'Issue Date' }), type: 'date' },
    { key: 'scale', label: t('sheets.col_scale', { defaultValue: 'Scale' }) },
  ];

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!empty) onApply(patch);
  }

  return (
    <form
      onSubmit={handleSubmit}
      aria-label={t('sheets.bulk_title', { defaultValue: 'Edit selected sheets' })}
      className="mb-3 rounded-xl border border-oe-blue/30 bg-oe-blue/5 px-4 py-3"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-content-primary">
          {t('sheets.bulk_selected', { defaultValue: '{{count}} sheets selected', count: selectedCount })}
        </p>
        <p className="text-2xs text-content-tertiary">
          {t('sheets.bulk_hint', {
            defaultValue: 'Fill in only what should change. Empty fields are left as they are on every sheet.',
          })}
        </p>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {fields.map((f) => {
          const id = `sheets-bulk-${f.key}`;
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
                className={inputCls}
              />
            </div>
          );
        })}
      </div>
      <datalist id="sheets-bulk-disciplines">
        {disciplines.map((d) => (
          <option key={d} value={d} />
        ))}
      </datalist>
      {error && (
        <p
          role="alert"
          className="mt-2 rounded-lg border border-semantic-error/30 bg-semantic-error/5 px-3 py-2 text-xs text-semantic-error"
        >
          {t('sheets.bulk_failed', { defaultValue: 'The selected sheets could not be updated.' })} {error}
        </p>
      )}
      <div className="mt-3 flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onClear} disabled={saving}>
          {t('sheets.bulk_clear', { defaultValue: 'Clear selection' })}
        </Button>
        <Button type="submit" variant="primary" loading={saving} disabled={empty}>
          {t('sheets.bulk_apply', { defaultValue: 'Apply to {{count}} sheets', count: selectedCount })}
        </Button>
      </div>
    </form>
  );
}
