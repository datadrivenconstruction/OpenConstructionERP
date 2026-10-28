// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small shared presentational helpers for the Cost Explorer tabs: money and
// percentage formatting, and a compact 0..1 meter bar. The price-base picker
// that used to live here moved to ``BasePicker.tsx`` when it stopped being a
// bare dropdown of region ids.

import { getNumberLocale } from '@/stores/usePreferencesStore';

/**
 * Format a Decimal-as-string (or number) for display, optionally suffixed with
 * its currency code.
 *
 * Money and quantities arrive from the API as Decimal-compatible strings; this
 * coerces for DISPLAY only (never arithmetic) and groups the number in the
 * user's ACTIVE app locale via {@link getIntlLocale} - the same locale
 * primitive the shared formatCurrency / fmtNumber helpers use - so a German or
 * Turkish user sees "1.234,5" instead of the browser-default "1,234.5". A
 * missing value renders a dash (clearer than "0"); a non-numeric value is
 * echoed back untouched rather than shown as "NaN".
 */
export function fmtMoney(value: string | number | null | undefined, currency?: string): string {
  if (value === null || value === undefined || value === '') return currency ? `- ${currency}` : '-';
  const n = typeof value === 'number' ? value : Number(value);
  const body = Number.isFinite(n)
    ? new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 2 }).format(n)
    : String(value);
  return currency ? `${body} ${currency}` : body;
}

/** A 0..1 fraction as a whole percentage. */
export function pct(fraction: number): string {
  const f = Number.isFinite(fraction) ? fraction : 0;
  return `${Math.round(f * 100)}%`;
}

/** A signed percentage (already in percent units, e.g. -10 -> "-10%"). */
export function signedPct(value: number): string {
  const v = Number.isFinite(value) ? value : 0;
  const rounded = Math.round(v * 10) / 10;
  return `${rounded > 0 ? '+' : ''}${rounded}%`;
}

export type MeterTone = 'blue' | 'green' | 'amber';

/** Compact horizontal bar for a 0..1 value with a trailing label. */
export function Meter({ value, label, tone = 'blue' }: { value: number; label: string; tone?: MeterTone }) {
  const safe = Number.isFinite(value) ? value : 0;
  const w = Math.max(0, Math.min(1, safe)) * 100;
  const bar = tone === 'green' ? 'bg-semantic-success' : tone === 'amber' ? 'bg-semantic-warning' : 'bg-oe-blue';
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-surface-tertiary">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${w}%` }} />
      </div>
      <span className="text-xs tabular-nums text-content-tertiary">{label}</span>
    </div>
  );
}

/** Muted inline meta line: code · region · unit (skips empties). */
export function MetaLine({ parts }: { parts: Array<string | null | undefined> }) {
  const shown = parts.filter((p): p is string => Boolean(p && p.trim()));
  return <span className="text-xs text-content-tertiary">{shown.join('  ·  ')}</span>;
}
