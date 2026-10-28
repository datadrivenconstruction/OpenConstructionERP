// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which BOQ columns this person shows and in what order, kept on this device
 * (like the column widths). Only the data columns in the middle of the grid are
 * movable; the position number, description, the row controls and the columns
 * driven by their own toolbar switches stay where they are.
 */
import type { ColDef } from 'ag-grid-community';
import { createLocalPref } from '@/shared/lib/localPref';

export interface BoqColumnPrefs {
  /** Per column id: true shows it, false hides it. Missing = the grid default. */
  visible: Record<string, boolean>;
  /** Column ids in the wanted order; unknown ids are ignored. */
  order: string[];
}

/** Built-in columns the picker offers; custom columns (`custom_*`) are added by the caller. */
export const BOQ_PICKER_COLUMNS = [
  { id: 'classification', labelKey: 'boq.classification', fallback: 'Code' },
  { id: 'unit', labelKey: 'boq.unit', fallback: 'Unit' },
  { id: 'quantity', labelKey: 'boq.quantity', fallback: 'Qty' },
  { id: 'unit_rate', labelKey: 'boq.unit_rate', fallback: 'Unit Rate' },
  { id: 'net_cost_rate', labelKey: 'boq.net_cost_rate', fallback: 'Net Cost' },
  { id: 'target_rate', labelKey: 'boq.target_rate', fallback: 'Target' },
  { id: 'sale_rate', labelKey: 'boq.sale_rate', fallback: 'Sale Rate' },
  { id: 'total', labelKey: 'boq.total', fallback: 'Total' },
] as const;

/** Columns a person must always be able to see: a bill without them is unreadable. */
export const BOQ_ALWAYS_SHOWN = ['quantity', 'unit', 'total'] as const;

/** Columns the grid hides until asked; every other picker column starts shown. */
export const BOQ_HIDDEN_BY_DEFAULT: ReadonlySet<string> = new Set(['net_cost_rate', 'target_rate', 'sale_rate']);

export interface PickerEntry {
  id: string;
  label: string;
}

/** Orders entries by the saved order; those never placed keep their built-in spot after the placed ones. */
export function orderEntries(entries: PickerEntry[], prefs: BoqColumnPrefs): PickerEntry[] {
  const rank = (e: PickerEntry) => {
    const at = prefs.order.indexOf(e.id);
    return at < 0 ? Number.MAX_SAFE_INTEGER : at;
  };
  return entries
    .map((e, i) => ({ e, i }))
    .sort((a, b) => rank(a.e) - rank(b.e) || a.i - b.i)
    .map(({ e }) => e);
}

const BUILT_IN = new Set<string>(BOQ_PICKER_COLUMNS.map((c) => c.id));

export const isMovableColumn = (id: string | undefined): id is string =>
  !!id && (BUILT_IN.has(id) || id.startsWith('custom_'));

function sanitize(raw: unknown): BoqColumnPrefs {
  const src = (raw && typeof raw === 'object' ? raw : {}) as Partial<Record<keyof BoqColumnPrefs, unknown>>;
  const visible: Record<string, boolean> = {};
  if (src.visible && typeof src.visible === 'object') {
    for (const [id, v] of Object.entries(src.visible as Record<string, unknown>)) {
      if (typeof v === 'boolean' && isMovableColumn(id) && !(BOQ_ALWAYS_SHOWN as readonly string[]).includes(id)) {
        visible[id] = v;
      }
    }
  }
  const order = Array.isArray(src.order)
    ? [...new Set((src.order as unknown[]).filter((id): id is string => typeof id === 'string' && isMovableColumn(id)))]
    : [];
  return { visible, order };
}

export const boqColumnPref = createLocalPref<BoqColumnPrefs>('oe_boq_columns_v1', sanitize);

export const isDefaultBoqColumnPrefs = (p: BoqColumnPrefs): boolean =>
  p.order.length === 0 && Object.keys(p.visible).length === 0;

const colKey = (c: ColDef): string | undefined => c.colId ?? (c.field as string | undefined);

/** Returns the column list with the person's order and visibility applied. */
export function applyColumnPrefs(defs: ColDef[], prefs: BoqColumnPrefs): ColDef[] {
  if (isDefaultBoqColumnPrefs(prefs)) return defs;
  const slots: number[] = [];
  const movable: ColDef[] = [];
  defs.forEach((c, i) => {
    if (isMovableColumn(colKey(c))) {
      slots.push(i);
      movable.push(c);
    }
  });
  const rank = (c: ColDef) => {
    const at = prefs.order.indexOf(colKey(c)!);
    return at < 0 ? Number.MAX_SAFE_INTEGER : at;
  };
  // Stable sort: columns the person never placed keep their built-in order after the placed ones.
  const sorted = movable
    .map((c, i) => ({ c, i }))
    .sort((a, b) => rank(a.c) - rank(b.c) || a.i - b.i)
    .map(({ c }) => {
      const shown = prefs.visible[colKey(c)!];
      return shown === undefined ? c : { ...c, hide: !shown };
    });
  const out = defs.slice();
  slots.forEach((slot, k) => {
    out[slot] = sorted[k]!;
  });
  return out;
}
