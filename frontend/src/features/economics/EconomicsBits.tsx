// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the three economics panels share: an amount in the reader's
// number format (a decimal string is never turned into a float), the findings
// list, and a one-line form for adding a row.

import { useState, type FormEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CircleAlert, Trash2 } from 'lucide-react';

import { formatDecimalText, formatMoneyText } from '@/features/contracts/hakedis/hakedisText';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';

import type { Finding } from './api';
import { FINDING } from './labels';

/** An amount in the plan's currency; empty where the server has no figure. */
export function useMoney(currency: string) {
  const { i18n } = useTranslation();
  const locale = i18n.language || 'en';
  return {
    money: (value: string | null | undefined) =>
      value === null || value === undefined ? '' : `${formatMoneyText(value, currency, locale)} ${currency}`.trim(),
    plain: (value: string | null | undefined, minDecimals = 0) => formatDecimalText(value, locale, minDecimals),
  };
}

/** A calendar day (YYYY-MM-DD) in the reader's format; empty where there is none. */
export function useDay() {
  const { i18n } = useTranslation();
  const locale = i18n.language || 'en';
  return (iso: string | null | undefined): string => {
    if (!iso) return '';
    const [y, m, d] = iso.split('-').map(Number);
    if (!y || !m || !d) return iso;
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(y, m - 1, d));
  };
}

/** `-` where a figure cannot be computed: an unknown figure is never shown as zero. */
export function orDash(text: string): string {
  return text === '' ? '-' : text;
}

/** A decimal string is negative when it starts with a minus sign. */
export const isNegative = (value: string | null | undefined): boolean => !!value && value.trim().startsWith('-');

/** What a finding says in the reader's language; an unknown code reads as its own words. */
function findingText(t: (key: string, options?: Record<string, unknown>) => string, f: Finding): string {
  const entry = FINDING[f.code];
  if (!entry) return f.code.replace(/_/g, ' ');
  // The ref of a process finding is the area token; the reader gets the area's name.
  const ref = f.code === 'process_not_set_up' ? t(`economics.process.${f.ref}`, { defaultValue: f.ref }) : f.ref;
  return t(entry[0], { defaultValue: entry[1], ref });
}

export function FindingList({ findings }: { findings: Finding[] }) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;
  return (
    <ul className="space-y-1.5" data-testid="economics-findings">
      {findings.map((f, i) => (
        <li
          key={`${f.code}:${f.ref}:${i}`}
          className={
            f.severity === 'error'
              ? 'flex items-start gap-2 rounded-md bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error'
              : 'flex items-start gap-2 rounded-md bg-semantic-warning-bg px-3 py-2 text-sm text-semantic-warning'
          }
        >
          {f.severity === 'error' ? <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
          <span>
            {findingText(t, f)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** A trash button that asks before it deletes: the row is only removed after the dialog is confirmed. */
export function ConfirmDelete({
  label,
  title,
  message,
  onConfirm,
}: {
  label: string;
  title: string;
  message: string;
  onConfirm: () => Promise<unknown> | unknown;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const confirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };
  return (
    <>
      <button
        type="button"
        aria-label={label}
        className="text-content-tertiary hover:text-semantic-error"
        onClick={() => setOpen(true)}
      >
        <Trash2 className="h-4 w-4" />
      </button>
      <ConfirmDialog open={open} title={title} message={message} loading={busy} onConfirm={confirm} onCancel={() => setOpen(false)} />
    </>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-content-secondary">
      {label}
      {children}
    </label>
  );
}

export const inputClass =
  'h-9 rounded-md border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue';

/** A row of inputs and one submit button; the form clears itself after a submit that went through. */
export function AddRow({
  submitLabel,
  onSubmit,
  children,
  disabled,
}: {
  submitLabel: string;
  onSubmit: () => Promise<unknown> | unknown;
  children: ReactNode;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await onSubmit();
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
      {children}
      <Button type="submit" size="sm" loading={busy} disabled={disabled || busy}>
        {submitLabel}
      </Button>
    </form>
  );
}

/** A decimal as typed: digits, an optional minus and one decimal point (a comma is read as the point). */
export function cleanDecimal(text: string): string {
  return text.trim().replace(',', '.');
}

export const isDecimal = (text: string): boolean => /^-?\d+(\.\d+)?$/.test(cleanDecimal(text));
