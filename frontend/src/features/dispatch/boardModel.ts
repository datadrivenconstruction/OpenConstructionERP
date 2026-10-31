// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Pure helpers for the dispatch board: dates, status colours, grouping and selection. */
import type { CardStatus, Conflict, ConflictKind, DispatchLocation, LocationKind, Placement } from './api';

/** Local calendar date as YYYY-MM-DD, never shifted by the UTC offset. */
export function isoDay(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

export function addDays(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number);
  const dt = new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
  dt.setDate(dt.getDate() + n);
  return isoDay(dt);
}

export function mondayOf(day: string): string {
  const [y, m, d] = day.split('-').map(Number);
  const dt = new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
  const shift = (dt.getDay() + 6) % 7;
  return addDays(day, -shift);
}

export const STATUS_CLASS: Record<Exclude<CardStatus, ''>, string> = {
  available: 'border-l-emerald-500',
  assigned: 'border-l-oe-blue',
  maintenance: 'border-l-red-500',
  in_transit: 'border-l-amber-500',
  absent: 'border-l-purple-500',
};

export const LOCATION_ORDER: Record<LocationKind, number> = { project: 0, yard: 1, shop: 2, rental_return: 3 };

export function sortLocations(locations: DispatchLocation[]): DispatchLocation[] {
  return [...locations].sort(
    (a, b) =>
      LOCATION_ORDER[a.kind] - LOCATION_ORDER[b.kind] || a.sort_order - b.sort_order || a.name.localeCompare(b.name),
  );
}

export function groupByLocation(placements: Placement[]): Record<string, Placement[]> {
  const out: Record<string, Placement[]> = {};
  for (const p of placements) {
    (out[p.location_id] ??= []).push(p);
  }
  for (const list of Object.values(out)) {
    list.sort((a, b) => a.start_time.localeCompare(b.start_time) || a.label.localeCompare(b.label));
  }
  return out;
}

export function toggle(selected: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

/** Conflicts counted by kind, errors first, for the summary strip. */
export function conflictSummary(conflicts: Conflict[]): { kind: ConflictKind; count: number; severity: string }[] {
  const by = new Map<ConflictKind, { count: number; severity: string }>();
  for (const c of conflicts) {
    const cur = by.get(c.kind) ?? { count: 0, severity: c.severity };
    cur.count += 1;
    if (c.severity === 'error') cur.severity = 'error';
    by.set(c.kind, cur);
  }
  return [...by.entries()]
    .map(([kind, v]) => ({ kind, ...v }))
    .sort((a, b) => (a.severity === b.severity ? b.count - a.count : a.severity === 'error' ? -1 : 1));
}
