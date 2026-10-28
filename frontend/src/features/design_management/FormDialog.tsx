// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One dialog for every write of the design screens. A caller describes the
// fields and hands over the request; the dialog keeps the draft, names what
// is still missing, and when the server refuses the write it shows the
// server's reason and every field problem the refusal listed, and stays open
// so nothing typed is lost.

import { useId, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';

import { Button } from '@/shared/ui/Button';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtList } from '@/shared/lib/formatters';

import { designViolations, type Violation } from './api';
import { refusalText } from './hooks';
import { errorText, humanizeCode, ui, type TFn } from './labels';

export type FormValue = string | boolean | string[];
export type FormValues = Record<string, FormValue>;

export interface FieldOption {
  value: string;
  label: string;
}

export interface FieldSpec {
  name: string;
  label: string;
  type: 'text' | 'textarea' | 'number' | 'date' | 'checkbox' | 'select' | 'multi' | 'person';
  options?: FieldOption[];
  required?: boolean;
  hint?: string;
  /** Leave the field out while the rest of the draft makes it meaningless. */
  showIf?: (values: FormValues) => boolean;
}

export interface FormDialogProps {
  title: string;
  subtitle?: string;
  fields: FieldSpec[];
  initial: FormValues;
  submitLabel: string;
  /** Sends the draft. A rejection keeps the dialog open and shows why. */
  submit: (values: FormValues) => Promise<unknown>;
  /** Extra problems of the draft as sentences; the server repeats every check. */
  problems?: (values: FormValues) => string[];
  /** Content under the fields that follows the draft, such as a preview. */
  extra?: (values: FormValues) => ReactNode;
  /** Names a field of a refused write, so a violation reads as a label and not a column. */
  violationField?: (field: string) => string;
  projectId: string;
  danger?: boolean;
  onClose: () => void;
  onDone: () => void;
  testId?: string;
}

const CONTROL = 'w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary';

export function str(values: FormValues, name: string): string {
  const v = values[name];
  return typeof v === 'string' ? v : '';
}

export function flag(values: FormValues, name: string): boolean {
  return values[name] === true;
}

export function list(values: FormValues, name: string): string[] {
  const v = values[name];
  return Array.isArray(v) ? v : [];
}

function isEmpty(value: FormValue | undefined): boolean {
  return value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
}

export function FormDialog({
  title,
  subtitle,
  fields,
  initial,
  submitLabel,
  submit,
  problems,
  extra,
  violationField,
  projectId,
  danger = false,
  onClose,
  onDone,
  testId = 'design-form',
}: FormDialogProps) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const baseId = useId();
  const [values, setValues] = useState<FormValues>(initial);
  const [tried, setTried] = useState(false);
  const [refusal, setRefusal] = useState<{ text: string; violations: Violation[] } | null>(null);

  const shown = fields.filter((f) => !f.showIf || f.showIf(values));
  const missing = shown.filter((f) => f.required && isEmpty(values[f.name])).map((f) => f.label);
  const draftProblems = [
    ...(missing.length > 0 ? [ui(t, 'design.ui.form.missing', { fields: fmtList(missing) })] : []),
    ...(problems ? problems(values) : []),
  ];

  const send = useMutation({
    mutationFn: () => submit(values),
    onSuccess: () => {
      onDone();
      onClose();
    },
    onError: (err) => setRefusal({ text: refusalText(t, err), violations: designViolations(err) }),
  });

  const set = (name: string, value: FormValue) => {
    setValues((v) => ({ ...v, [name]: value }));
    setRefusal(null);
  };
  const onSubmit = () => {
    setTried(true);
    if (draftProblems.length > 0) return;
    send.mutate();
  };

  const control = (f: FieldSpec, id: string) => {
    const common = { id, 'data-testid': `field-${f.name}`, 'aria-required': f.required || undefined };
    switch (f.type) {
      case 'textarea':
        return <textarea {...common} rows={3} className={CONTROL} value={str(values, f.name)} onChange={(e) => set(f.name, e.target.value)} />;
      case 'checkbox':
        return (
          <input
            {...common}
            type="checkbox"
            className="h-4 w-4"
            checked={flag(values, f.name)}
            onChange={(e) => set(f.name, e.target.checked)}
          />
        );
      case 'select':
        return (
          <select {...common} className={CONTROL} value={str(values, f.name)} onChange={(e) => set(f.name, e.target.value)}>
            {(!f.required || isEmpty(values[f.name])) && <option value="">{ui(t, 'design.ui.form.none')}</option>}
            {(f.options ?? []).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        );
      case 'multi': {
        const chosen = list(values, f.name);
        return (
          <div {...common} role="group" aria-label={f.label} className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-border-light bg-surface-elevated p-2">
            {(f.options ?? []).length === 0 && <p className="text-xs text-content-tertiary">{ui(t, 'design.ui.form.no_choices')}</p>}
            {(f.options ?? []).map((o) => (
              <label key={o.value} className="flex items-center gap-2 text-sm text-content-primary">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={chosen.includes(o.value)}
                  onChange={(e) => set(f.name, e.target.checked ? [...chosen, o.value] : chosen.filter((x) => x !== o.value))}
                />
                {o.label}
              </label>
            ))}
          </div>
        );
      }
      case 'person':
        return <ProjectPeopleSelect id={id} projectId={projectId} value={str(values, f.name)} onChange={(userId) => set(f.name, userId)} />;
      default:
        return (
          <input
            {...common}
            type={f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text'}
            min={f.type === 'number' ? 0 : undefined}
            autoComplete="off"
            className={CONTROL}
            value={str(values, f.name)}
            onChange={(e) => set(f.name, e.target.value)}
          />
        );
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={title}
      subtitle={subtitle}
      size={shown.length > 4 ? 'md' : 'sm'}
      busy={send.isPending}
      testId={testId}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={send.isPending}>
            {ui(t, 'design.ui.form.cancel')}
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} loading={send.isPending} onClick={onSubmit} data-testid="form-submit">
            {submitLabel}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        {refusal && (
          <div role="alert" data-testid="form-refusal" className="rounded-md border border-semantic-error/30 bg-semantic-error-bg px-3 py-2 text-sm text-content-primary">
            <p>{refusal.text}</p>
            {refusal.violations.length > 0 && (
              <ul className="ml-4 mt-1 list-disc text-xs text-content-secondary">
                {refusal.violations.map((v, i) => (
                  <li key={`${v.code ?? ''}-${v.field ?? ''}-${i}`}>
                    {v.field && <span className="font-medium">{violationField ? violationField(v.field) : humanizeCode(v.field)}: </span>}
                    {v.code && errorText(t, v.code)}
                    {v.label ? <span className="ml-1">{v.label}</span> : (v.value || v.ref || v.recipient) && <span className="ml-1 font-mono">{v.value || v.ref || v.recipient}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className={shown.length > 4 ? 'grid grid-cols-1 gap-3 sm:grid-cols-2' : 'space-y-3'}>
          {shown.map((f) => {
            const id = `${baseId}-${f.name}`;
            const wide = f.type === 'textarea' || f.type === 'multi';
            return (
              <div key={f.name} className={wide ? 'sm:col-span-2' : undefined}>
                <label htmlFor={id} className={f.type === 'checkbox' ? 'mr-2 text-sm text-content-primary' : 'mb-1 block text-xs font-medium text-content-secondary'}>
                  {f.label}
                  {f.required && <span aria-hidden className="ml-0.5 text-semantic-error">*</span>}
                </label>
                {control(f, id)}
                {f.hint && <p className="mt-1 text-2xs text-content-tertiary">{f.hint}</p>}
              </div>
            );
          })}
        </div>
        {extra?.(values)}
        {tried && draftProblems.length > 0 && (
          <ul role="alert" data-testid="form-problems" className="ml-4 list-disc text-xs text-semantic-error">
            {draftProblems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        )}
      </div>
    </WideModal>
  );
}
