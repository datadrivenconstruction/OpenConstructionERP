// Design module (ERP side of the design editor link).
import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, FileText } from 'lucide-react';
import clsx from 'clsx';
import { Badge, Button, type BadgeVariant } from '@/shared/ui';
import { ApiError } from '@/shared/lib/api';
import {
  fieldSpec,
  formatValue,
  getAt,
  labelKey,
  parseInput,
  type BriefDoc,
  type DisplayStatus,
  type FieldSpec,
  type Provenance,
} from './data/briefModel';
import type { SchemaError } from './data/schemaCheck';
import { fmtList } from '@/shared/lib/formatters';

type T = ReturnType<typeof useTranslation>['t'];

/** The server refuses a job when a queue is configured but no worker answers (503, code no_worker). */
export function noWorkerText(err: unknown, t: T): string | null {
  if (!(err instanceof ApiError) || err.status !== 503) return null;
  const detail = (err.body as { detail?: { code?: string } } | null)?.detail;
  return detail && typeof detail === 'object' && detail.code === 'no_worker' ? tr(t, 'design.generate.no_worker') : null;
}

/** One module string in the page language; the locale bundles fall back to English. */
export function tr(t: T, key: string, options: Record<string, unknown> = {}): string {
  return t(key, options) as string;
}

/** Whether the locale bundles carry a text for `key` (codes from the server may be new to this build). */
export function hasText(t: T, key: string): boolean {
  return (t(key, { defaultValue: '' }) as string) !== '';
}

export function fieldLabel(t: T, pointer: string): string {
  return tr(t, labelKey(pointer));
}

export function errorText(t: T, e: SchemaError): string {
  if (e.code === 'pattern') {
    const last = e.pointer.split('/').pop();
    if (last === 'country' || last === 'currency' || last === 'locale') return tr(t, `design.error.pattern.${last}`);
  }
  if (e.code.startsWith('property_name_')) return tr(t, 'design.error.not_allowed');
  return tr(t, `design.error.${e.code}`, { param: e.param });
}

const STATUS_VARIANT: Record<DisplayStatus, BadgeVariant> = {
  confirmed: 'success',
  proposed: 'warning',
  default: 'blue',
  none: 'neutral',
};

function provenanceTitle(t: T, entry: Provenance | undefined): string {
  if (!entry) return '';
  const lines: string[] = [];
  if (entry.status === 'confirmed' && entry.confirmed_at) {
    lines.push(tr(t, 'design.status.confirmed_by', { at: new Date(entry.confirmed_at).toLocaleString() }));
  }
  for (const s of entry.sources ?? []) {
    const parts = [tr(t, `design.source.${s.kind}`)];
    if (s.page) parts.push(tr(t, 'design.source.page', { page: s.page }));
    if (s.quote) parts.push(`“${s.quote}”`);
    lines.push(fmtList(parts));
  }
  if (entry.note) lines.push(entry.note);
  return lines.join('\n');
}

export interface ProvenanceProps {
  doc: BriefDoc;
  pointer: string;
  /** Null when confirming is not possible now; the reason is shown as a tooltip. */
  onConfirm: ((pointer: string) => void) | null;
  confirmBlockedReason?: string;
  /** Opens the "cite a document" dialog for this value; absent hides the button. */
  onCite?: (pointer: string) => void;
}

export function ProvenanceControl({ doc, pointer, onConfirm, confirmBlockedReason, onCite }: ProvenanceProps) {
  const { t } = useTranslation();
  const entry = doc.provenance?.[pointer];
  const status: DisplayStatus = entry?.status ?? 'none';
  const hasValue = getAt(doc, pointer) !== undefined;
  if (!hasValue) return null;
  const named = { field: fieldLabel(t, pointer), status: tr(t, `design.status.${status}`) };
  const focusRing = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue';
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5" data-testid={`prov-${pointer}`}>
      <span title={provenanceTitle(t, entry)}>
        <Badge variant={STATUS_VARIANT[status]} size="sm">
          {tr(t, `design.status.${status}`)}
        </Badge>
      </span>
      {onCite && (
        <button
          type="button"
          className={clsx('inline-flex items-center rounded p-0.5 text-content-tertiary hover:text-oe-blue-text', focusRing)}
          title={tr(t, 'design.cite.button')}
          aria-label={tr(t, 'design.cite.button_for', named)}
          onClick={() => onCite(pointer)}
        >
          <FileText size={13} aria-hidden />
        </button>
      )}
      {status !== 'confirmed' && (
        <button
          type="button"
          className={clsx(
            'inline-flex items-center gap-0.5 rounded px-1 text-xs font-medium',
            focusRing,
            onConfirm ? 'text-oe-blue-text hover:underline' : 'cursor-not-allowed text-content-tertiary',
          )}
          disabled={!onConfirm}
          aria-label={tr(t, 'design.brief.confirm_value', named)}
          title={onConfirm ? undefined : confirmBlockedReason}
          onClick={() => onConfirm?.(pointer)}
        >
          <Check size={12} aria-hidden />
          {tr(t, 'design.brief.confirm')}
        </button>
      )}
    </span>
  );
}

export interface FieldProps {
  doc: BriefDoc;
  pointer: string;
  errors: SchemaError[];
  onChange: (pointer: string, value: unknown) => void;
  provenance: Omit<ProvenanceProps, 'doc' | 'pointer'>;
  /** Suggestions for a free-text field (room kinds). */
  suggestions?: string[];
  compact?: boolean;
  currency?: string;
  /** Called with true while the typed text cannot be read as a value (blocks saving), false when it can. */
  onParseError?: (pointer: string, bad: boolean) => void;
}

export function optionLabel(t: T, value: string): string {
  return t(`design.option.${value}`, { defaultValue: value }) as string;
}

/** One brief value: label, typed input, unit, provenance, validation message. */
export function Field({ doc, pointer, errors, onChange, provenance, suggestions, currency, onParseError }: FieldProps) {
  const { t } = useTranslation();
  const id = useId();
  const spec: FieldSpec = fieldSpec(pointer);
  const value = getAt(doc, pointer);
  const [text, setText] = useState(() => formatValue(value));
  const [parseError, setParseError] = useState<string | null>(null);

  // Follow outside changes (reload, confirm) unless the text already means the same value.
  useEffect(() => {
    const parsed = parseInput(spec, text);
    if (!parsed.ok || JSON.stringify(parsed.value) !== JSON.stringify(value)) {
      setText(formatValue(value));
      setParseError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(value)]);

  // The page must know: an unreadable entry never reaches the document, so Save would store the old value.
  useEffect(() => {
    onParseError?.(pointer, parseError !== null);
    return () => onParseError?.(pointer, false);
  }, [parseError, pointer, onParseError]);

  const commit = (next: string) => {
    setText(next);
    const parsed = parseInput(spec, next);
    if (!parsed.ok) {
      setParseError(tr(t, `design.error.${parsed.code}`));
      return;
    }
    setParseError(null);
    onChange(pointer, parsed.value);
  };

  const messages = parseError ? [parseError] : errors.map((e) => errorText(t, e));
  const invalid = messages.length > 0;
  const errorId = `${id}-error`;
  const describedBy = invalid ? errorId : undefined;
  const unit = spec.unit === 'currency' ? currency || tr(t, 'design.unit.currency') : spec.unit;
  const inputClass = clsx(
    'h-9 w-full rounded-lg border bg-surface-primary px-3 text-sm text-content-primary',
    'focus:outline-none focus:ring-2 focus:ring-oe-blue/30',
    invalid ? 'border-semantic-error' : 'border-border',
  );

  let control;
  if (spec.kind === 'choice' || spec.kind === 'boolean') {
    const options = spec.kind === 'boolean' ? ['true', 'false'] : spec.options;
    control = (
      <select id={id} className={inputClass} value={text} aria-invalid={invalid} aria-required={spec.required || undefined}
        aria-describedby={describedBy} onChange={(e) => commit(e.target.value)}>
        <option value="">{tr(t, 'design.option.empty')}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {spec.kind === 'boolean' ? tr(t, o === 'true' ? 'design.option.yes' : 'design.option.no') : optionLabel(t, o)}
          </option>
        ))}
      </select>
    );
  } else {
    const listId = suggestions ? `${id}-list` : undefined;
    control = (
      <>
        <input
          id={id}
          name={pointer}
          autoComplete="off"
          className={inputClass}
          inputMode={spec.kind === 'integer' || spec.kind === 'number' ? 'decimal' : undefined}
          value={text}
          list={listId}
          maxLength={spec.maxLength}
          aria-invalid={invalid}
          aria-required={spec.required || undefined}
          aria-describedby={describedBy}
          placeholder={spec.kind.endsWith('_list') ? tr(t, 'design.brief.list_hint') : undefined}
          onChange={(e) => commit(e.target.value)}
        />
        {suggestions && (
          <datalist id={listId}>
            {suggestions.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
        )}
      </>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex min-h-[2.75rem] flex-col items-start gap-0.5">
        <label htmlFor={id} className="text-sm font-medium leading-5 text-content-primary">
          {fieldLabel(t, pointer)}
          {spec.required && <span className="ml-0.5 text-semantic-error" aria-hidden>*</span>}
        </label>
        <ProvenanceControl doc={doc} pointer={pointer} {...provenance} />
      </div>
      <div className="flex items-center gap-2">
        {control}
        {unit && <span className="shrink-0 text-xs text-content-tertiary">{unit}</span>}
      </div>
      {invalid && (
        <span id={errorId} role="alert" className="flex flex-col text-xs text-semantic-error">
          {messages.map((m) => (
            <span key={m}>{m}</span>
          ))}
        </span>
      )}
    </div>
  );
}

export function RemoveButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <Button variant="ghost" size="sm" onClick={onClick}>
      {label}
    </Button>
  );
}
