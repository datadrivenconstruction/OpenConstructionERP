// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tool-result data normalization.
 *
 * The backend tool handlers (`backend/app/modules/erp_chat/tools.py`) return
 * a `data` envelope shaped per-tool, e.g. `{ projects: [...], total }`,
 * `{ positions: [...], grand_total }`, `{ risks: [...], summary }`. The
 * renderers historically expected a bare array, so every tool result fell
 * through to an empty state ("No data to display"). This module unwraps the
 * envelope back to the shape each renderer wants, while staying backward
 * compatible with anything that already passes a bare array.
 *
 * Keep the key list in sync with the tool handlers' `data` payloads.
 */

/** Pull the first present array out of a `data` envelope, by key priority. */
export function unwrapList(data: unknown, keys: string[]): Record<string, unknown>[] {
  if (Array.isArray(data)) return data as Record<string, unknown>[];
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    for (const key of keys) {
      const v = obj[key];
      if (Array.isArray(v)) return v as Record<string, unknown>[];
    }
  }
  return [];
}

/** Coerce a value to a finite number, or undefined. */
export function toNum(v: unknown): number | undefined {
  if (v == null || v === '') return undefined;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : undefined;
}
