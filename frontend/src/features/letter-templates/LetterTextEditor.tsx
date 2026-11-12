// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Editor for one letter text: subject, heading, body and closing, with the
 * letter's fields as chips that insert `{name}` where the cursor is, and the
 * rule findings underneath. Shared by the settings page and the one-off edit
 * before downloading a single letter.
 */

import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { AlertTriangle, XCircle } from 'lucide-react';
import {
  checkLetterText,
  insertPlaceholder,
  type LetterField,
  type LetterIssue,
  type LetterPlaceholder,
  type LetterText,
} from './letterRules';

export interface LetterTextEditorProps {
  value: LetterText;
  onChange: (next: LetterText) => void;
  placeholders: readonly LetterPlaceholder[];
  readOnly?: boolean;
}

/** Readable label of a placeholder; unknown names show as written. */
export function usePlaceholderLabel(): (name: string) => string {
  const { t } = useTranslation();
  const labels: Record<string, string> = {
    bidder: t('letter_templates.ph_bidder', { defaultValue: 'Bidder' }),
    project: t('letter_templates.ph_project', { defaultValue: 'Project' }),
    package: t('letter_templates.ph_package', { defaultValue: 'Tender package' }),
    amount: t('letter_templates.ph_amount', { defaultValue: 'Contract sum' }),
    award_date: t('letter_templates.ph_award_date', { defaultValue: 'Award date' }),
    date: t('letter_templates.ph_date', { defaultValue: 'Date' }),
    deadline: t('letter_templates.ph_deadline', { defaultValue: 'Deadline' }),
    sender: t('letter_templates.ph_sender', { defaultValue: 'Signed by' }),
    company: t('letter_templates.ph_company', { defaultValue: 'Your company' }),
  };
  return (name: string) => labels[name] ?? name;
}

export function issueMessage(
  t: ReturnType<typeof useTranslation>['t'],
  issue: LetterIssue,
  label: (name: string) => string,
): string {
  const name = issue.placeholder ? `{${issue.placeholder}}` : '';
  switch (issue.code) {
    case 'empty_body':
      return t('letter_templates.issue_empty_body', { defaultValue: 'The text is empty.' });
    case 'unknown_placeholder':
      return t('letter_templates.issue_unknown', {
        defaultValue: '{{name}} is not a field of this letter and would print as written.',
        name,
      });
    case 'missing_required':
      return t('letter_templates.issue_required', {
        defaultValue: 'The letter usually states {{name}} ({{label}}).',
        name,
        label: label(issue.placeholder),
      });
    default:
      return t('letter_templates.issue_too_long', { defaultValue: 'This field is too long.' });
  }
}

export function LetterTextEditor({ value, onChange, placeholders, readOnly = false }: LetterTextEditorProps) {
  const { t } = useTranslation();
  const label = usePlaceholderLabel();
  const refs = useRef<Partial<Record<LetterField, HTMLInputElement | HTMLTextAreaElement | null>>>({});
  const lastField = useRef<LetterField>('body');
  const issues = checkLetterText(value, placeholders);

  const insert = (name: string) => {
    const field = lastField.current;
    const el = refs.current[field];
    const current = value[field] || '';
    const start = el?.selectionStart ?? current.length;
    const end = el?.selectionEnd ?? current.length;
    const next = insertPlaceholder(current, start, end, name);
    onChange({ ...value, [field]: next.value });
    requestAnimationFrame(() => {
      const target = refs.current[field];
      if (target) {
        target.focus();
        target.setSelectionRange(next.caret, next.caret);
      }
    });
  };

  const fieldProps = (field: LetterField) => ({
    ref: (el: HTMLInputElement | HTMLTextAreaElement | null) => {
      refs.current[field] = el;
    },
    value: value[field] ?? '',
    readOnly,
    onFocus: () => {
      lastField.current = field;
    },
    onChange: (e: { target: { value: string } }) => onChange({ ...value, [field]: e.target.value }),
    'data-testid': `letter-field-${field}`,
  });

  return (
    <div className="space-y-3">
      {!readOnly && (
        <div>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('letter_templates.fields', { defaultValue: 'Fields' })}>
            {placeholders.map((p) => (
              <button
                key={p.name}
                type="button"
                onClick={() => insert(p.name)}
                title={`{${p.name}} = ${p.sample}`}
                data-testid={`letter-chip-${p.name}`}
                className={clsx(
                  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs',
                  'border-border bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
                  p.required && 'border-oe-blue/40 text-content-primary',
                )}
              >
                {label(p.name)}
              </button>
            ))}
          </div>
          <p className="mt-1 text-2xs text-content-tertiary">
            {t('letter_templates.fields_hint', { defaultValue: 'Click a field to insert it where the cursor is.' })}
          </p>
        </div>
      )}
      <label className="block">
        <span className="oe-label">{t('letter_templates.field_subject', { defaultValue: 'Subject' })}</span>
        <input type="text" className="oe-input w-full" maxLength={500} {...fieldProps('subject')} />
      </label>
      <label className="block">
        <span className="oe-label">{t('letter_templates.field_heading', { defaultValue: 'Heading' })}</span>
        <input type="text" className="oe-input w-full" maxLength={500} {...fieldProps('heading')} />
      </label>
      <label className="block">
        <span className="oe-label">{t('letter_templates.field_body', { defaultValue: 'Text' })}</span>
        <textarea className="oe-textarea w-full font-normal" rows={12} maxLength={20000} {...fieldProps('body')} />
      </label>
      <label className="block">
        <span className="oe-label">{t('letter_templates.field_closing', { defaultValue: 'Closing' })}</span>
        <textarea className="oe-textarea w-full" rows={2} maxLength={500} {...fieldProps('closing')} />
      </label>
      {issues.length > 0 && (
        <ul className="space-y-1" data-testid="letter-issues">
          {issues.map((issue, i) => (
            <li
              key={`${issue.code}-${issue.field}-${issue.placeholder}-${i}`}
              className={clsx(
                'flex items-start gap-1.5 text-xs',
                issue.severity === 'error' ? 'text-semantic-error' : 'text-semantic-warning',
              )}
            >
              {issue.severity === 'error' ? <XCircle size={14} className="mt-px shrink-0" /> : <AlertTriangle size={14} className="mt-px shrink-0" />}
              <span>{issueMessage(t, issue, label)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function hasBlockingIssue(value: LetterText, placeholders: readonly LetterPlaceholder[]): boolean {
  return checkLetterText(value, placeholders).some((i) => i.severity === 'error');
}
