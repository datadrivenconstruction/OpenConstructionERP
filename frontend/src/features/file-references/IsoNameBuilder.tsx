// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** ISO 19650 filename builder wizard.
 *
 * Seven required inputs + two optional inputs build a structurally
 * compliant filename. The user can pre-fill from the currently-broken
 * name (when the parent passes ``initialParts``). The live preview is
 * validated client-side on every keystroke — that's a free check, so
 * the user sees green / red feedback before hitting "Apply".
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Button } from '@/shared/ui/Button';
import { useValidateName } from './hooks';
import type { Iso19650Parts } from './types';
import { fmtList } from '@/shared/lib/formatters';

export interface IsoNameBuilderProps {
  /** Initial part values — typically from a failed validation. */
  initialParts?: Iso19650Parts;
  /** Initial file extension (e.g. ``"pdf"``) — kept as-is in the output. */
  extension?: string | null;
  /** Called when the user confirms — receives the assembled filename. */
  onApply?: (filename: string) => void;
  /** Called when the user cancels. */
  onCancel?: () => void;
  className?: string;
}

interface Field {
  key: keyof Iso19650Parts;
  labelKey: string;
  labelDefault: string;
  placeholder: string;
  helpKey: string;
  helpDefault: string;
  required: boolean;
}

const FIELDS: Field[] = [
  {
    key: 'project',
    labelKey: 'iso.project',
    labelDefault: 'Project',
    placeholder: 'PRJ1',
    helpKey: 'iso.project_help',
    helpDefault: '2-6 alphanumeric',
    required: true,
  },
  {
    key: 'originator',
    labelKey: 'iso.originator',
    labelDefault: 'Originator',
    placeholder: 'ABC',
    helpKey: 'iso.originator_help',
    helpDefault: '2-6 alphanumeric (company code)',
    required: true,
  },
  {
    key: 'volume',
    labelKey: 'iso.volume',
    labelDefault: 'Volume',
    placeholder: '01',
    helpKey: 'iso.volume_help',
    helpDefault: '1-2 chars or "XX"',
    required: true,
  },
  {
    key: 'level',
    labelKey: 'iso.level',
    labelDefault: 'Level',
    placeholder: '02',
    helpKey: 'iso.level_help',
    helpDefault: '2 chars (e.g. 00, 01, XX)',
    required: true,
  },
  {
    key: 'type',
    labelKey: 'iso.type',
    labelDefault: 'Type',
    placeholder: 'DR',
    helpKey: 'iso.type_help',
    helpDefault: '2-4 chars (Drawing, Spec, Model)',
    required: true,
  },
  {
    key: 'role',
    labelKey: 'iso.role',
    labelDefault: 'Role',
    placeholder: 'AR',
    helpKey: 'iso.role_help',
    helpDefault: '2-4 chars (A/S/M/E discipline)',
    required: true,
  },
  {
    key: 'number',
    labelKey: 'iso.number',
    labelDefault: 'Number',
    placeholder: '0001',
    helpKey: 'iso.number_help',
    helpDefault: '4 digits',
    required: true,
  },
  {
    key: 'status',
    labelKey: 'iso.status',
    labelDefault: 'Status (optional)',
    placeholder: 'S2',
    helpKey: 'iso.status_help',
    helpDefault: '2 chars (e.g. S0..S6)',
    required: false,
  },
  {
    key: 'revision',
    labelKey: 'iso.revision',
    labelDefault: 'Revision (optional)',
    placeholder: 'P01',
    helpKey: 'iso.revision_help',
    helpDefault: '2-3 chars (P01, C01, etc.)',
    required: false,
  },
];

const EMPTY: Iso19650Parts = {
  project: null,
  originator: null,
  volume: null,
  level: null,
  type: null,
  role: null,
  number: null,
  status: null,
  revision: null,
};

function partsToValues(parts: Iso19650Parts | undefined): Record<keyof Iso19650Parts, string> {
  const seed = parts ?? EMPTY;
  return {
    project: seed.project ?? '',
    originator: seed.originator ?? '',
    volume: seed.volume ?? '',
    level: seed.level ?? '',
    type: seed.type ?? '',
    role: seed.role ?? '',
    number: seed.number ?? '',
    status: seed.status ?? '',
    revision: seed.revision ?? '',
  };
}

function assemble(
  values: Record<keyof Iso19650Parts, string>,
  extension: string | null,
): string {
  const required: (keyof Iso19650Parts)[] = [
    'project',
    'originator',
    'volume',
    'level',
    'type',
    'role',
    'number',
  ];
  const reqParts = required.map((k) => values[k] ?? '');
  const optionalParts: string[] = [];
  if (values.status) optionalParts.push(values.status);
  if (values.revision) optionalParts.push(values.revision);
  const stem = [...reqParts, ...optionalParts].join('-');
  const ext = extension ? extension.replace(/^\.+/, '') : '';
  return ext ? `${stem}.${ext}` : stem;
}

export function IsoNameBuilder({
  initialParts,
  extension = null,
  onApply,
  onCancel,
  className,
}: IsoNameBuilderProps) {
  const { t } = useTranslation();
  const [values, setValues] = useState(() => partsToValues(initialParts));
  const validateMut = useValidateName();

  const filename = useMemo(() => assemble(values, extension), [values, extension]);

  useEffect(() => {
    // Re-validate on every change. The mutation is debounced naturally
    // by React Query's de-dupe — the same payload back-to-back is a
    // single in-flight request.
    if (!filename) return;
    validateMut.mutate({ filename });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filename]);

  const result = validateMut.data;
  const codes = result?.violation_codes ?? [];
  const isValid = result?.is_valid ?? false;

  return (
    <div
      className={clsx(
        'rounded-lg border border-border bg-surface-primary p-4',
        className,
      )}
      data-testid="iso-name-builder"
    >
      <h3 className="text-sm font-semibold text-content-primary">
        {t('iso.builder_title', { defaultValue: 'ISO 19650 filename builder' })}
      </h3>
      <p className="mt-0.5 text-xs text-content-tertiary">
        {t('iso.builder_desc', {
          defaultValue:
            'Fill in each segment - the preview below updates live.',
        })}
      </p>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {FIELDS.map((f) => (
          <label
            key={f.key}
            className="flex flex-col gap-1"
            data-testid={`iso-field-${String(f.key)}`}
          >
            <span className="text-xs font-medium text-content-secondary">
              {t(f.labelKey, { defaultValue: f.labelDefault })}
              {f.required && (
                <span className="ml-0.5 text-semantic-error">*</span>
              )}
            </span>
            <input
              type="text"
              value={values[f.key]}
              onChange={(e) =>
                setValues((v) => ({ ...v, [f.key]: e.target.value }))
              }
              placeholder={f.placeholder}
              className="rounded-md border border-border bg-surface-primary px-2 py-1 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
            <span className="text-[10px] text-content-tertiary">
              {t(f.helpKey, { defaultValue: f.helpDefault })}
            </span>
          </label>
        ))}
      </div>

      <div className="mt-4 rounded-md border border-border bg-surface-secondary p-3">
        <div className="text-xs font-medium uppercase text-content-tertiary">
          {t('iso.preview', { defaultValue: 'Preview' })}
        </div>
        <div
          className={clsx(
            'mt-1 break-all font-mono text-sm',
            isValid ? 'text-semantic-success' : 'text-content-primary',
          )}
          data-testid="iso-preview"
        >
          {filename}
        </div>
        {codes.length > 0 && (
          <div className="mt-2 text-xs text-semantic-warning">
            {fmtList(codes)}
          </div>
        )}
        {isValid && (
          <div className="mt-1 text-xs text-semantic-success">
            {t('iso.preview_valid', {
              defaultValue: 'Looks good - matches ISO 19650.',
            })}
          </div>
        )}
      </div>

      <div className="mt-3 flex justify-end gap-2">
        {onCancel && (
          <Button variant="ghost" size="sm" onClick={onCancel} type="button">
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        )}
        <Button
          variant="primary"
          size="sm"
          onClick={() => onApply?.(filename)}
          disabled={!onApply || !isValid}
          type="button"
          data-testid="iso-apply"
        >
          {t('iso.apply', { defaultValue: 'Apply to file' })}
        </Button>
      </div>
    </div>
  );
}
