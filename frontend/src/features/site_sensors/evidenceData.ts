// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Pure helpers for the claim evidence form and the BIM element picker. */

export const MAX_WINDOW_DAYS = 366;

/** The window around an alert: an hour either side of it, as ISO instants. */
export function windowAround(raisedAt: string, minutes = 60): { from: string; to: string } | null {
  const t = Date.parse(raisedAt);
  if (Number.isNaN(t)) return null;
  return { from: new Date(t - minutes * 60_000).toISOString(), to: new Date(t + minutes * 60_000).toISOString() };
}

/** Whether a window runs forward and stays within a year (the server enforces the same). */
export function windowIsValid(from: string | null, to: string | null): boolean {
  if (!from || !to) return false;
  const a = Date.parse(from);
  const b = Date.parse(to);
  if (Number.isNaN(a) || Number.isNaN(b) || b <= a) return false;
  return b - a <= MAX_WINDOW_DAYS * 86_400_000;
}

/** First characters of an integrity code, for a toast. */
export function shortHash(hash: string, length = 16): string {
  return hash.slice(0, length);
}

export interface PickableElement {
  id: string;
  name: string;
  element_type: string;
  storey?: string;
  is_type_definition?: boolean;
}

/** Elements matching a query on name, type or storey; type definitions are never pickable. */
export function filterElements<T extends PickableElement>(
  elements: T[],
  query: string,
  limit = 100,
): { items: T[]; truncated: boolean } {
  const q = query.trim().toLowerCase();
  const hits = elements.filter(
    (e) =>
      !e.is_type_definition &&
      (!q || `${e.name} ${e.element_type} ${e.storey ?? ''}`.toLowerCase().includes(q)),
  );
  return { items: hits.slice(0, limit), truncated: hits.length > limit };
}
