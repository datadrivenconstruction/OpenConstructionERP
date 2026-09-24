// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What a proposal will write, field by field.
 *
 * For a change to an existing record the old value is shown struck through and
 * muted, followed by the new one in full weight, so "80 m³ → 120 m³" is read
 * in one glance. Values are formatted in the reader's locale by kind (see
 * actionFormat.ts). Long text is clamped to three lines with a toggle.
 */
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import { AlertTriangle, ArrowRight, Info } from 'lucide-react';
import {
  fieldLabel,
  formatFieldValue,
  isChangedField,
  refParts,
} from './actionFormat';
import type { ActionField, ActionNote } from './types';

export interface ActionFieldTableProps {
  fields: readonly ActionField[];
  /** Things to know before applying; a note naming a field sits under that field. */
  notes?: readonly ActionNote[];
  /** Show old -> new for changed fields (default true). */
  showBefore?: boolean;
  className?: string;
}

/** Text longer than this, or with more than two line breaks, starts clamped. */
const CLAMP_CHARS = 160;

function isNumericKind(field: ActionField): boolean {
  return field.kind === 'number' || field.kind === 'money' || field.kind === 'percent';
}

function ClampedText({ text }: { text: string }) {
  const { t } = useTranslation();
  const id = useId();
  const [open, setOpen] = useState(false);
  const long = text.length > CLAMP_CHARS || (text.match(/\n/g)?.length ?? 0) > 2;
  if (!long) return <span className="whitespace-pre-line break-words">{text}</span>;
  return (
    <span className="block">
      <span id={id} className={clsx('block whitespace-pre-line break-words', !open && 'line-clamp-3')}>
        {text}
      </span>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="mt-0.5 rounded text-[11px] font-medium text-[var(--act-accent)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)]"
      >
        {open
          ? t('erp_chat.action.show_less', { defaultValue: 'Show less' })
          : t('erp_chat.action.show_more', { defaultValue: 'Show more' })}
      </button>
    </span>
  );
}

function FieldValue({ field, value }: { field: ActionField; value: unknown }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  if (field.kind === 'ref') {
    const ref = refParts(value);
    if (ref?.url && ref.url.startsWith('/')) {
      const url = ref.url;
      return (
        <button
          type="button"
          onClick={() => navigate(url)}
          className="rounded text-start text-[var(--act-accent)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)]"
        >
          {ref.label}
        </button>
      );
    }
  }
  const text = formatFieldValue(field, value, t, i18n.language ?? 'en');
  if (field.kind === 'longtext' || field.kind === 'text') return <ClampedText text={text} />;
  return <span className={clsx(isNumericKind(field) && 'tabular-nums')}>{text}</span>;
}

function NoteLine({ note }: { note: ActionNote }) {
  const { t } = useTranslation();
  const text = note.key ? String(t(note.key, { ...note.params, defaultValue: note.text })) : note.text;
  const warning = note.tone === 'warning';
  return (
    <p
      className={clsx('flex items-start gap-1.5 text-[11px] leading-snug', warning ? 'text-[var(--act-text)]' : 'text-[var(--act-text-2)]')}
      data-testid="action-note"
      data-tone={note.tone}
    >
      {warning ? (
        <AlertTriangle size={12} className="mt-px shrink-0 text-[var(--act-warning)]" aria-hidden="true" />
      ) : (
        <Info size={12} className="mt-px shrink-0 text-[var(--act-accent)]" aria-hidden="true" />
      )}
      <span>{text}</span>
    </p>
  );
}

export function ActionFieldTable({ fields, notes = [], showBefore = true, className }: ActionFieldTableProps) {
  const { t } = useTranslation();
  const fieldKeys = new Set(fields.map((f) => f.key));
  const looseNotes = notes.filter((n) => !n.field || !fieldKeys.has(n.field));
  if (fields.length === 0) {
    return (
      <div className={clsx('space-y-1.5', className)}>
        <p className="text-xs text-[var(--act-text-3)]">
          {t('erp_chat.action.no_fields', { defaultValue: 'No details to show.' })}
        </p>
        {looseNotes.map((n, i) => (
          <NoteLine key={`${n.key}-${i}`} note={n} />
        ))}
      </div>
    );
  }
  return (
    <div className={className}>
    <dl
      className={clsx(
        'grid grid-cols-[minmax(84px,36%)_1fr] gap-x-3 text-[13px] leading-snug',
      )}
      data-testid="action-field-table"
    >
      {fields.map((field, index) => {
        const changed = showBefore && isChangedField(field);
        const rowBorder = index > 0 ? 'border-t border-[var(--act-border-subtle)]' : '';
        return (
          <div key={field.key} className="contents" data-field-key={field.key} data-changed={changed || undefined}>
            <dt className={clsx('py-1.5 text-xs text-[var(--act-text-3)]', rowBorder)}>{fieldLabel(field, t)}</dt>
            <dd className={clsx('min-w-0 py-1.5 text-[var(--act-text)]', rowBorder)}>
              {changed ? (
                <span className="inline-flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
                  <del className="text-[var(--act-text-3)] decoration-[var(--act-text-3)]" data-testid="field-before">
                    <span className="sr-only">
                      {t('erp_chat.action.before_sr', { defaultValue: 'Before:' })}{' '}
                    </span>
                    <FieldValue field={field} value={field.before} />
                  </del>
                  <ArrowRight
                    size={12}
                    aria-hidden="true"
                    className="shrink-0 self-center text-[var(--act-text-3)] rtl:rotate-180"
                  />
                  <ins className="font-semibold no-underline text-[var(--act-text)]" data-testid="field-after">
                    <span className="sr-only">
                      {t('erp_chat.action.after_sr', { defaultValue: 'After:' })}{' '}
                    </span>
                    <FieldValue field={field} value={field.value} />
                  </ins>
                </span>
              ) : (
                <FieldValue field={field} value={field.value} />
              )}
              {notes
                .filter((n) => n.field === field.key)
                .map((n, i) => (
                  <div key={`${n.key}-${i}`} className="mt-1">
                    <NoteLine note={n} />
                  </div>
                ))}
            </dd>
          </div>
        );
      })}
    </dl>
    {looseNotes.length > 0 && (
      <div className="mt-1.5 space-y-1">
        {looseNotes.map((n, i) => (
          <NoteLine key={`${n.key}-${i}`} note={n} />
        ))}
      </div>
    )}
    </div>
  );
}
