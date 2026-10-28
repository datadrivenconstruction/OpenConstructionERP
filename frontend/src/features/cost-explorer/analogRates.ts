// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure, dependency-free helpers for the Analog rates panel. Kept out of the
// component (which imports React and the UI kit) so they can be unit-tested in a
// plain .ts test without a DOM or a query client, the same split this folder
// uses for parts.tsx vs api.ts.

/** Minimal shape of a candidate rate the clipboard row needs. */
export interface InsertRowInput {
  code?: string;
  description?: string;
  unit?: string;
  rate?: number | string | null;
  currency?: string | null;
}

/**
 * Build a tab-separated clipboard line for one candidate rate:
 * ``code<TAB>description<TAB>unit<TAB>rate<TAB>currency``. Pasting the line into
 * a spreadsheet or the estimate grid fills those columns from the active cell.
 * Whitespace in the description is collapsed so a multi-line scope never breaks
 * the single-row paste. A non-finite rate yields an empty rate field rather than
 * the string ``"NaN"``.
 */
export function buildInsertRow(item: InsertRowInput): string {
  let rate = '';
  if (item.rate !== null && item.rate !== undefined && item.rate !== '') {
    const n = typeof item.rate === 'number' ? item.rate : Number(item.rate);
    if (Number.isFinite(n)) rate = String(n);
  }
  const description = (item.description ?? '').replace(/\s+/g, ' ').trim();
  return [item.code ?? '', description, item.unit ?? '', rate, item.currency ?? ''].join('\t');
}

/** The distinct, non-empty currencies present across the candidates. */
export function distinctCurrencies(items: ReadonlyArray<{ currency?: string | null }>): string[] {
  const seen = new Set<string>();
  for (const it of items) {
    const c = (it.currency ?? '').trim();
    if (c) seen.add(c);
  }
  return [...seen];
}

/**
 * Index of the cheapest candidate, or -1 when none has a comparable price.
 * Only strictly positive, finite rates count (a zero or negative rate is bad
 * data, not "the cheapest"). Trust this only when every candidate shares one
 * currency - see {@link distinctCurrencies}.
 */
export function lowestPriceIndex(items: ReadonlyArray<{ rate?: number | string | null }>): number {
  let best = -1;
  let bestRate = Number.POSITIVE_INFINITY;
  items.forEach((it, i) => {
    const n = typeof it.rate === 'number' ? it.rate : Number(it.rate);
    if (Number.isFinite(n) && n > 0 && n < bestRate) {
      bestRate = n;
      best = i;
    }
  });
  return best;
}

/** First ``n`` items plus a count of how many were left out. Null-safe. */
export function topItems<T>(
  items: readonly T[] | null | undefined,
  n: number,
): { shown: T[]; more: number } {
  const all = items ? items.filter((v): v is T => v != null) : [];
  return { shown: all.slice(0, n), more: Math.max(0, all.length - n) };
}

/**
 * The ordered work steps ("application conditions" / what the rate includes),
 * read defensively from ``metadata_.scope_of_work`` and capped at ``n``.
 * Non-string and blank entries are dropped.
 */
export function scopeSteps(
  item: { metadata_?: { scope_of_work?: unknown } | null } | null | undefined,
  n = 3,
): { shown: string[]; more: number } {
  const raw = item?.metadata_?.scope_of_work;
  const all = Array.isArray(raw)
    ? raw.filter((s): s is string => typeof s === 'string' && s.trim().length > 0).map((s) => s.trim())
    : [];
  return { shown: all.slice(0, n), more: Math.max(0, all.length - n) };
}
