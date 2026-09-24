// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Adjust a proposal before applying it, the way a manager corrects a draft a
 * colleague prepared: only the editable fields become inputs, the rest stay
 * visible as context.
 *
 * Only the keys the person actually changed are sent. Numbers are edited as
 * canonical text and read back with the shared tolerant parser, so a German
 * reader typing "1.234,5" and an English one typing "1,234.5" both send
 * 1234.5. Server-side field errors (422) appear under the matching input.
 */
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check, X } from 'lucide-react';
import { onlyChangedFields } from '@/shared/lib/apiHelpers';
import { localizedUnitCode } from '@/shared/lib/unitLabels';
import {
  draftFromValue,
  fieldLabel,
  formatFieldValue,
  optionLabel,
  parseDraft,
  type DraftError,
} from './actionFormat';
import { ActionButton } from './ActionControls';
import type { ActionField, ChatAction } from './types';

export interface ActionEditFormProps {
  action: ChatAction;
  busy: boolean;
  /** Field messages from a refused save, keyed by payload key. */
  serverFieldErrors?: Record<string, string>;
  /** Called with the changed keys only; never called with an empty object. */
  onSubmit: (payload: Record<string, unknown>) => void;
  onCancel: () => void;
}

const INPUT_CLASS = clsx(
  'w-full min-w-0 rounded-md border bg-[var(--act-bg)] px-2 py-1 text-[13px] text-[var(--act-text)]',
  'placeholder:text-[var(--act-text-3)]',
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)] focus:border-[var(--act-accent)]',
);

function draftErrorText(error: DraftError, t: ReturnType<typeof useTranslation>['t']): string {
  switch (error) {
    case 'required':
      return String(t('erp_chat.action.form.required', { defaultValue: 'This field is required.' }));
    case 'number':
      return String(t('erp_chat.action.form.invalid_number', { defaultValue: 'Enter a number, for example 120 or 12.5.' }));
    case 'date':
      return String(t('erp_chat.action.form.invalid_date', { defaultValue: 'Enter a valid date.' }));
    default:
      return '';
  }
}

export function ActionEditForm({ action, busy, serverFieldErrors = {}, onSubmit, onCancel }: ActionEditFormProps) {
  const { t, i18n } = useTranslation();
  const formRef = useRef<HTMLFormElement>(null);
  const editable = useMemo(() => action.fields.filter((f) => f.editable && f.kind !== 'ref'), [action.fields]);
  // The starting point is frozen when the form opens, so "changed" means
  // changed by this person in this form, not by a refetch underneath it.
  const [initial] = useState<Record<string, string>>(() =>
    Object.fromEntries(editable.map((f) => [f.key, draftFromValue(f)])),
  );
  const [drafts, setDrafts] = useState<Record<string, string>>(initial);
  const [clientErrors, setClientErrors] = useState<Record<string, DraftError>>({});

  const inputFor = (key: string): HTMLElement | null => {
    const nodes = formRef.current?.querySelectorAll<HTMLElement>('[data-field-input]') ?? [];
    return Array.from(nodes).find((n) => n.getAttribute('data-field-input') === key) ?? null;
  };

  // Put the cursor in the first editable field when the form opens.
  useEffect(() => {
    const first = formRef.current?.querySelector<HTMLElement>('[data-field-input]');
    first?.focus();
  }, []);

  const setDraft = (key: string, value: string) => {
    setDrafts((d) => ({ ...d, [key]: value }));
    if (clientErrors[key]) {
      setClientErrors((e) => {
        const next = { ...e };
        delete next[key];
        return next;
      });
    }
  };

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (busy) return;
    const parsed: Record<string, unknown> = {};
    const errors: Record<string, DraftError> = {};
    for (const field of editable) {
      const result = parseDraft(field, drafts[field.key] ?? '');
      if (result.ok) parsed[field.key] = result.value;
      else errors[field.key] = result.error;
    }
    if (Object.keys(errors).length > 0) {
      setClientErrors(errors);
      const first = editable.find((f) => errors[f.key]);
      if (first) inputFor(first.key)?.focus();
      return;
    }
    const changed = onlyChangedFields(parsed, drafts, initial);
    if (Object.keys(changed).length === 0) {
      onCancel();
      return;
    }
    onSubmit(changed);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLFormElement>) => {
    if (e.key === 'Escape') {
      // Close the form, not the dock around it.
      e.stopPropagation();
      e.preventDefault();
      onCancel();
    } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      submit();
    }
  };

  const renderInput = (field: ActionField, inputId: string, describedBy: string | undefined, invalid: boolean) => {
    const common = {
      id: inputId,
      'data-field-input': field.key,
      'aria-invalid': invalid || undefined,
      'aria-describedby': describedBy,
      'aria-required': field.required || undefined,
      disabled: busy,
      className: clsx(INPUT_CLASS, invalid ? 'border-[var(--act-error)]' : 'border-[var(--act-border)]'),
    };
    const value = drafts[field.key] ?? '';
    switch (field.kind) {
      case 'longtext':
        return <textarea {...common} rows={3} value={value} onChange={(e) => setDraft(field.key, e.target.value)} />;
      case 'enum':
        return (
          <select {...common} value={value} onChange={(e) => setDraft(field.key, e.target.value)}>
            {(!field.required || value === '') && (
              <option value="">{t('erp_chat.action.form.choose', { defaultValue: 'Choose…' })}</option>
            )}
            {(field.options ?? []).map((o) => (
              <option key={o.value} value={o.value}>
                {optionLabel(o, t)}
              </option>
            ))}
          </select>
        );
      case 'date':
        return <input {...common} type="date" value={value} onChange={(e) => setDraft(field.key, e.target.value)} />;
      case 'number':
      case 'money':
      case 'percent': {
        const suffix =
          field.kind === 'money'
            ? (field.currency ?? '')
            : field.kind === 'percent'
              ? '%'
              : field.unit
                ? localizedUnitCode(field.unit, i18n.language ?? 'en')
                : '';
        return (
          <span className="flex min-w-0 items-center gap-1.5">
            <input
              {...common}
              type="text"
              inputMode="decimal"
              autoComplete="off"
              value={value}
              onChange={(e) => setDraft(field.key, e.target.value)}
              className={clsx(common.className, 'tabular-nums')}
            />
            {suffix && (
              <span className="shrink-0 text-xs text-[var(--act-text-3)]" aria-hidden="true">
                {suffix}
              </span>
            )}
          </span>
        );
      }
      default:
        return (
          <input
            {...common}
            type="text"
            autoComplete="off"
            value={value}
            onChange={(e) => setDraft(field.key, e.target.value)}
          />
        );
    }
  };

  return (
    <form
      ref={formRef}
      onSubmit={submit}
      onKeyDown={onKeyDown}
      noValidate
      aria-label={String(t('erp_chat.action.form.label', { defaultValue: 'Edit proposed change' }))}
      className="space-y-2"
      data-testid="action-edit-form"
    >
      {action.fields.map((field) => {
        const isEditable = field.editable && field.kind !== 'ref';
        const inputId = `act-${action.id}-${field.key}`;
        const errorId = `${inputId}-error`;
        const clientError = clientErrors[field.key];
        const serverError = serverFieldErrors[field.key];
        const errorText = clientError ? draftErrorText(clientError, t) : serverError;
        const label = fieldLabel(field, t);
        if (!isEditable) {
          return (
            <div key={field.key} className="grid grid-cols-[minmax(84px,36%)_1fr] gap-x-3 text-[13px]">
              <span className="text-xs text-[var(--act-text-3)]">{label}</span>
              <span className="min-w-0 break-words text-[var(--act-text-2)]">
                {formatFieldValue(field, field.value, t, i18n.language ?? 'en')}
              </span>
            </div>
          );
        }
        return (
          <div key={field.key} className="grid grid-cols-[minmax(84px,36%)_1fr] items-start gap-x-3">
            <label htmlFor={inputId} className="pt-1 text-xs text-[var(--act-text-2)]">
              {label}
              {field.required && (
                <>
                  <span aria-hidden="true" className="ms-0.5 text-[var(--act-error)]">
                    *
                  </span>
                  <span className="sr-only">
                    {' '}
                    {t('erp_chat.action.form.required_sr', { defaultValue: '(required)' })}
                  </span>
                </>
              )}
            </label>
            <div className="min-w-0">
              {renderInput(field, inputId, errorText ? errorId : undefined, Boolean(errorText))}
              {errorText && (
                <p id={errorId} className="mt-0.5 text-[11px] text-[var(--act-error)]">
                  {errorText}
                </p>
              )}
            </div>
          </div>
        );
      })}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <ActionButton
          type="submit"
          tone="primary"
          busy={busy}
          busyLabel={String(t('erp_chat.action.busy.save', { defaultValue: 'Saving…' }))}
          icon={<Check size={13} />}
        >
          {t('erp_chat.action.form.save', { defaultValue: 'Save changes' })}
        </ActionButton>
        <ActionButton tone="ghost" onClick={onCancel} disabled={busy} icon={<X size={13} />}>
          {t('erp_chat.action.form.cancel', { defaultValue: 'Cancel' })}
        </ActionButton>
        <span className="text-[11px] text-[var(--act-text-3)]">
          {t('erp_chat.action.form.hint', { defaultValue: 'Saving updates the proposal. Nothing is written until you apply it.' })}
        </span>
      </div>
    </form>
  );
}
