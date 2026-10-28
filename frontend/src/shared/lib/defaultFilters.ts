// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The filter a person wants a list to open with (tasks, RFIs, inbox), kept on
 * this device. Only plain string / boolean fields are stored; a page decides
 * which of its fields are worth keeping (never an id that belongs to one project).
 */
import { createLocalPref } from './localPref';

export const DEFAULT_FILTER_PAGES = ['tasks', 'rfi', 'inbox'] as const;
export type DefaultFilterPage = (typeof DEFAULT_FILTER_PAGES)[number];
export type FilterValues = Record<string, string | boolean>;
export type DefaultFilters = Partial<Record<DefaultFilterPage, FilterValues>>;

export const defaultFilterPref = createLocalPref<DefaultFilters>('oe_default_filters_v1', (raw) => {
  const out: DefaultFilters = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const page of DEFAULT_FILTER_PAGES) {
    const src = (raw as Record<string, unknown>)[page];
    if (!src || typeof src !== 'object') continue;
    const values: FilterValues = {};
    for (const [k, v] of Object.entries(src as Record<string, unknown>)) {
      if (typeof v === 'string' || typeof v === 'boolean') values[k] = v;
    }
    if (Object.keys(values).length > 0) out[page] = values;
  }
  return out;
});

/** The neutral literals ('' / false) as their plain types, so state can take other values. */
type Widen<T> = { [K in keyof T]: T[K] extends string ? string : T[K] extends boolean ? boolean : T[K] };

export const sameFilter = (a: FilterValues, b: FilterValues): boolean => {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) if (a[k] !== b[k]) return false;
  return true;
};

/** The saved filter laid over the page's neutral one, so a missing field stays neutral. */
export function initialFilter<T extends FilterValues>(page: DefaultFilterPage, neutral: T): Widen<T> {
  const saved = defaultFilterPref.read()[page];
  if (!saved) return neutral as Widen<T>;
  const out = { ...neutral } as FilterValues;
  for (const k of Object.keys(neutral)) {
    if (typeof saved[k] === typeof neutral[k]) out[k] = saved[k]!;
  }
  return out as Widen<T>;
}
