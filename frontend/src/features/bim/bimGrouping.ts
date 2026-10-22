// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure grouping and filtering logic for the BIM viewer sidebar.
 *
 * Group by any element property (category, level, type, family, material,
 * IFC class, discipline or a custom parameter), two levels deep, with element
 * counts and summed length / area / volume per group. Property conditions
 * (equals / contains / numeric range) and the URL codec that lets a link
 * reproduce the filtered view live here too, so every rule is unit tested
 * without rendering the viewer.
 */
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import type { BIMElementGroup } from './api';

/* ── Properties an element can be grouped or filtered by ─────────────── */

export const BUILTIN_GROUP_KEYS = [
  'category',
  'level',
  'type',
  'family',
  'material',
  'ifc_class',
  'discipline',
] as const;
export type BuiltinGroupKey = (typeof BUILTIN_GROUP_KEYS)[number];
/** A built-in key or `prop:<name>` for a custom parameter. */
export type GroupKey = BuiltinGroupKey | `prop:${string}`;

/** Numeric fields a range condition can test besides custom parameters. */
export const QUANTITY_KEYS = ['qty:length', 'qty:area', 'qty:volume'] as const;
export type QuantityKey = (typeof QUANTITY_KEYS)[number];
export type FilterField = GroupKey | QuantityKey;

const EMPTY_TOKENS = new Set(['', 'none', 'null', 'n/a', '-', 'notdefined', 'undefined']);

function lowerIndex(props: Record<string, unknown> | undefined): Map<string, unknown> {
  const out = new Map<string, unknown>();
  if (!props) return out;
  for (const k of Object.keys(props)) out.set(k.toLowerCase(), props[k]);
  return out;
}

function readText(props: Map<string, unknown>, keys: readonly string[]): string {
  for (const key of keys) {
    const v = props.get(key.toLowerCase());
    if (v === null || v === undefined || typeof v === 'object') continue;
    const text = String(v).trim();
    if (!EMPTY_TOKENS.has(text.toLowerCase())) return text;
  }
  return '';
}

const CATEGORY_KEYS = ['category', 'revit_category', '[other] category', 'Category'];
const TYPE_KEYS = ['type_name', 'family_and_type', 'family and type', 'objecttype', 'object_type', 'object type', 'type'];
const FAMILY_KEYS = ['family', 'family_name', 'family name'];
const MATERIAL_KEYS = [
  'material',
  'materials',
  'material_name',
  'structural material',
  'structural_material',
  'material name',
  '[other] material',
];

/**
 * The text an element shows for a grouping key. An empty string means the
 * element has no value; the panel renders that as "(not set)".
 */
export function groupValueOf(el: BIMElementData, key: GroupKey): string {
  const props = lowerIndex(el.properties as Record<string, unknown> | undefined);
  switch (key) {
    case 'level':
      return (el.storey ?? '').trim();
    case 'ifc_class':
      return (el.element_type ?? '').trim();
    case 'discipline':
      return (el.discipline ?? '').trim();
    case 'category': {
      // IFC exports from Revit carry the Revit category ("Walls") next to the
      // IFC class; prefer the human category, fall back to the class.
      const human = readText(props, ['[other] category', 'revit_category']);
      if (human) return human;
      const cat = (el.category ?? '').trim() || readText(props, CATEGORY_KEYS);
      return cat || (el.element_type ?? '').trim();
    }
    case 'type':
      return readText(props, TYPE_KEYS);
    case 'family':
      return readText(props, FAMILY_KEYS);
    case 'material':
      return readText(props, MATERIAL_KEYS);
    default: {
      const name = key.slice('prop:'.length);
      return readText(props, [name]);
    }
  }
}

/* ── Quantities ──────────────────────────────────────────────────────── */

const QTY_ALIASES: Record<'length' | 'area' | 'volume', string[]> = {
  length: ['length_m', 'length', 'Length'],
  area: ['area_m2', 'area', 'NetArea', 'GrossArea', 'net_area', 'gross_area', 'NetSideArea', 'Area'],
  volume: ['volume_m3', 'volume', 'NetVolume', 'GrossVolume', 'net_volume', 'gross_volume', 'Volume'],
};

function toNumber(raw: unknown): number | null {
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
  if (typeof raw === 'string') {
    const cleaned = raw.trim().replace(',', '.');
    if (!cleaned) return null;
    const n = Number.parseFloat(cleaned);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** First numeric quantity among the aliases, read from quantities then properties. */
export function quantityOf(el: BIMElementData, kind: 'length' | 'area' | 'volume'): number {
  const sources = [el.quantities as Record<string, unknown> | undefined, el.properties as Record<string, unknown> | undefined];
  for (const src of sources) {
    if (!src) continue;
    for (const alias of QTY_ALIASES[kind]) {
      if (alias in src) {
        const n = toNumber(src[alias]);
        if (n !== null) return n;
      }
    }
  }
  return 0;
}

/* ── Group tree ──────────────────────────────────────────────────────── */

export interface GroupTotals {
  count: number;
  length: number;
  area: number;
  volume: number;
}

export interface GroupNode extends GroupTotals {
  /** Stable id: level-1 value, or `<level-1>\u0000<level-2>`. */
  id: string;
  /** Raw value; empty string when the property is not set. */
  value: string;
  ids: string[];
  children: GroupNode[];
}

function emptyNode(id: string, value: string): GroupNode {
  return { id, value, count: 0, length: 0, area: 0, volume: 0, ids: [], children: [] };
}

function addTo(node: GroupTotals & { ids: string[] }, el: BIMElementData): void {
  node.count += 1;
  node.length += quantityOf(el, 'length');
  node.area += quantityOf(el, 'area');
  node.volume += quantityOf(el, 'volume');
  node.ids.push(el.id);
}

function sortNodes(nodes: GroupNode[]): GroupNode[] {
  // Biggest groups first; "(not set)" always last so real values lead.
  return nodes.sort((a, b) => {
    if (!a.value !== !b.value) return a.value ? -1 : 1;
    if (b.count !== a.count) return b.count - a.count;
    return a.value.localeCompare(b.value, undefined, { numeric: true });
  });
}

/** Group elements by one key, optionally nested by a second. */
export function buildGroupTree(
  elements: readonly BIMElementData[],
  level1: GroupKey,
  level2?: GroupKey | null,
): GroupNode[] {
  const top = new Map<string, GroupNode>();
  for (const el of elements) {
    const v1 = groupValueOf(el, level1);
    let node = top.get(v1);
    if (!node) {
      node = emptyNode(v1, v1);
      top.set(v1, node);
    }
    addTo(node, el);
    if (level2 && level2 !== level1) {
      const v2 = groupValueOf(el, level2);
      let child = node.children.find((c) => c.value === v2);
      if (!child) {
        child = emptyNode(`${v1}\u0000${v2}`, v2);
        node.children.push(child);
      }
      addTo(child, el);
    }
  }
  const nodes = sortNodes([...top.values()]);
  for (const n of nodes) sortNodes(n.children);
  return nodes;
}

export function totalsOf(nodes: readonly GroupNode[]): GroupTotals {
  return nodes.reduce<GroupTotals>(
    (acc, n) => ({
      count: acc.count + n.count,
      length: acc.length + n.length,
      area: acc.area + n.area,
      volume: acc.volume + n.volume,
    }),
    { count: 0, length: 0, area: 0, volume: 0 },
  );
}

/**
 * Custom parameters worth offering in the "group by" list: present on at
 * least two elements, not a quantity, ordered by how many elements carry them.
 */
export function discoverPropertyKeys(elements: readonly BIMElementData[], limit = 60): string[] {
  const coverage = new Map<string, number>();
  for (const el of elements) {
    const props = el.properties as Record<string, unknown> | undefined;
    if (!props) continue;
    for (const [k, v] of Object.entries(props)) {
      if (v === null || v === undefined || typeof v === 'object') continue;
      coverage.set(k, (coverage.get(k) ?? 0) + 1);
    }
  }
  return [...coverage.entries()]
    .filter(([, n]) => n >= 2)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([k]) => k);
}

/* ── Colours ─────────────────────────────────────────────────────────── */

/** Categorical palette, readable on light and dark backgrounds. */
export const GROUP_PALETTE = [
  '#2563eb',
  '#16a34a',
  '#ea580c',
  '#9333ea',
  '#0891b2',
  '#dc2626',
  '#ca8a04',
  '#db2777',
  '#4f46e5',
  '#059669',
  '#7c3aed',
  '#64748b',
];

export function colourForIndex(i: number): string {
  return GROUP_PALETTE[i % GROUP_PALETTE.length]!;
}

/* ── Property conditions ─────────────────────────────────────────────── */

export type ConditionOp = 'eq' | 'neq' | 'contains' | 'between';

export interface PropertyCondition {
  field: FilterField;
  op: ConditionOp;
  /** Text operand for eq / neq / contains. */
  value?: string;
  /** Inclusive bounds for between; either may be omitted. */
  min?: number | null;
  max?: number | null;
}

export function isQuantityField(field: FilterField): field is QuantityKey {
  return (QUANTITY_KEYS as readonly string[]).includes(field);
}

function fieldText(el: BIMElementData, field: FilterField): string {
  if (isQuantityField(field)) return String(quantityOf(el, field.slice(4) as 'length' | 'area' | 'volume'));
  return groupValueOf(el, field);
}

function fieldNumber(el: BIMElementData, field: FilterField): number | null {
  if (isQuantityField(field)) return quantityOf(el, field.slice(4) as 'length' | 'area' | 'volume');
  return toNumber(groupValueOf(el, field));
}

export function matchesCondition(el: BIMElementData, c: PropertyCondition): boolean {
  if (c.op === 'between') {
    const n = fieldNumber(el, c.field);
    if (n === null) return false;
    if (c.min !== null && c.min !== undefined && n < c.min) return false;
    if (c.max !== null && c.max !== undefined && n > c.max) return false;
    return true;
  }
  const text = fieldText(el, c.field).toLowerCase();
  const operand = (c.value ?? '').trim().toLowerCase();
  if (c.op === 'contains') return text.includes(operand);
  if (c.op === 'neq') return text !== operand;
  return text === operand;
}

export function matchesAll(el: BIMElementData, conditions: readonly PropertyCondition[]): boolean {
  for (const c of conditions) if (!matchesCondition(el, c)) return false;
  return true;
}

/** A condition the user can add: text ops need a value, a range needs a bound. */
export function isConditionComplete(c: PropertyCondition): boolean {
  if (c.op === 'between') {
    const hasMin = typeof c.min === 'number' && Number.isFinite(c.min);
    const hasMax = typeof c.max === 'number' && Number.isFinite(c.max);
    if (!hasMin && !hasMax) return false;
    return !(hasMin && hasMax && (c.min as number) > (c.max as number));
  }
  return (c.value ?? '').trim().length > 0;
}

/* ── URL codec ───────────────────────────────────────────────────────── */

/** The filter state a shared link reproduces. */
export interface UrlFilterState {
  search: string;
  storeys: string[];
  types: string[];
  buildingsOnly: boolean;
  conditions: PropertyCondition[];
}

export const URL_FILTER_PARAM = 'bf';

export function encodeUrlFilter(s: UrlFilterState): string | null {
  const payload: Record<string, unknown> = {};
  if (s.search.trim()) payload.q = s.search.trim();
  if (s.storeys.length) payload.s = s.storeys;
  if (s.types.length) payload.t = s.types;
  if (!s.buildingsOnly) payload.b = 0;
  if (s.conditions.length) payload.c = s.conditions;
  if (Object.keys(payload).length === 0) return null;
  return JSON.stringify(payload);
}

const VALID_OPS: readonly ConditionOp[] = ['eq', 'neq', 'contains', 'between'];

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'string');
}

/** Parse the `bf` parameter. Anything malformed is dropped, never thrown. */
export function decodeUrlFilter(raw: string | null | undefined): UrlFilterState | null {
  if (!raw) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  const d = data as Record<string, unknown>;
  const conditions: PropertyCondition[] = [];
  if (Array.isArray(d.c)) {
    for (const item of d.c) {
      if (!item || typeof item !== 'object') continue;
      const c = item as Record<string, unknown>;
      if (typeof c.field !== 'string' || !VALID_OPS.includes(c.op as ConditionOp)) continue;
      const cond: PropertyCondition = {
        field: c.field as FilterField,
        op: c.op as ConditionOp,
        value: typeof c.value === 'string' ? c.value : undefined,
        min: typeof c.min === 'number' ? c.min : null,
        max: typeof c.max === 'number' ? c.max : null,
      };
      if (isConditionComplete(cond)) conditions.push(cond);
    }
  }
  return {
    search: typeof d.q === 'string' ? d.q : '',
    storeys: isStringArray(d.s) ? d.s : [],
    types: isStringArray(d.t) ? d.t : [],
    buildingsOnly: d.b !== 0,
    conditions,
  };
}

/* ── Saved groups ────────────────────────────────────────────────────── */

function asList(v: unknown): string[] {
  if (typeof v === 'string') return v ? [v] : [];
  return isStringArray(v) ? v.filter(Boolean) : [];
}

/**
 * True when a saved group's `filter_criteria` can be evaluated here. Rule
 * trees and property filters are resolved by the server only.
 */
function isClientResolvable(criteria: Record<string, unknown>): boolean {
  const keys = Object.keys(criteria);
  if (keys.length === 0) return false;
  return keys.every((k) => ['element_type', 'storey', 'discipline', 'category', 'name_contains'].includes(k));
}

/**
 * Member ids of a saved group within the loaded model.
 *
 * Dynamic groups with simple criteria are evaluated against the loaded
 * elements, so a stale or empty server snapshot never shows "0 elements".
 * Everything else uses the server's ids, narrowed to what is loaded.
 */
export function resolveGroupMembers(group: BIMElementGroup, elements: readonly BIMElementData[]): string[] {
  const criteria = (group.filter_criteria ?? {}) as Record<string, unknown>;
  if (group.is_dynamic && isClientResolvable(criteria)) {
    const types = new Set(asList(criteria.element_type).map((s) => s.toLowerCase()));
    const storeys = new Set(asList(criteria.storey));
    const disciplines = new Set(asList(criteria.discipline));
    const categories = new Set(asList(criteria.category).map((s) => s.toLowerCase()));
    const name = typeof criteria.name_contains === 'string' ? criteria.name_contains.toLowerCase() : '';
    return elements
      .filter((el) => {
        if (types.size) {
          const tpe = (el.element_type ?? '').toLowerCase();
          const typeName = groupValueOf(el, 'type').toLowerCase();
          if (!types.has(tpe) && !types.has(typeName)) return false;
        }
        if (storeys.size && !storeys.has(el.storey ?? '')) return false;
        if (disciplines.size && !disciplines.has(el.discipline ?? '')) return false;
        if (categories.size && !categories.has(groupValueOf(el, 'category').toLowerCase())) return false;
        if (name && !(el.name ?? '').toLowerCase().includes(name)) return false;
        return true;
      })
      .map((el) => el.id);
  }
  const loaded = new Set(elements.map((el) => el.id));
  const ids = Array.isArray(group.member_element_ids) ? group.member_element_ids : [];
  // Before the elements arrive keep the server's list rather than showing 0.
  if (loaded.size === 0) return ids;
  return ids.filter((id) => loaded.has(id));
}

/** The group with its members resolved against the loaded model. */
export function withResolvedMembers(group: BIMElementGroup, elements: readonly BIMElementData[]): BIMElementGroup {
  const ids = resolveGroupMembers(group, elements);
  return { ...group, member_element_ids: ids, element_count: ids.length };
}

/* ── Export ──────────────────────────────────────────────────────────── */

export interface GroupExportLabels {
  level1: string;
  level2?: string;
  count: string;
  length: string;
  area: string;
  volume: string;
  notSet: string;
  total: string;
}

export interface GroupExportRow {
  level1: string;
  level2?: string;
  count: number;
  length: number;
  area: number;
  volume: number;
}

function round3(n: number): number {
  return Math.round(n * 1000) / 1000;
}

/** Flat rows (leaf level when nested) plus a total row, for CSV and XLSX. */
export function groupExportRows(nodes: readonly GroupNode[], labels: GroupExportLabels, nested: boolean): GroupExportRow[] {
  const rows: GroupExportRow[] = [];
  for (const n of nodes) {
    const l1 = n.value || labels.notSet;
    const leaves = nested && n.children.length ? n.children : [null];
    for (const c of leaves) {
      const src = c ?? n;
      rows.push({
        level1: l1,
        level2: nested ? (c ? c.value || labels.notSet : '') : undefined,
        count: src.count,
        length: round3(src.length),
        area: round3(src.area),
        volume: round3(src.volume),
      });
    }
  }
  const t = totalsOf(nodes);
  rows.push({
    level1: labels.total,
    level2: nested ? '' : undefined,
    count: t.count,
    length: round3(t.length),
    area: round3(t.area),
    volume: round3(t.volume),
  });
  return rows;
}

function csvCell(v: string | number): string {
  const s = String(v);
  // Neutralise spreadsheet formula injection from model property values.
  const safe = /^[=+\-@\t\r]/.test(s) && typeof v === 'string' ? `'${s}` : s;
  return /[",;\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function groupsToCsv(nodes: readonly GroupNode[], labels: GroupExportLabels, nested: boolean): string {
  const header = [labels.level1, ...(nested ? [labels.level2 ?? ''] : []), labels.count, labels.length, labels.area, labels.volume];
  const lines = [header.map(csvCell).join(',')];
  for (const r of groupExportRows(nodes, labels, nested)) {
    const cells: (string | number)[] = [r.level1, ...(nested ? [r.level2 ?? ''] : []), r.count, r.length, r.area, r.volume];
    lines.push(cells.map(csvCell).join(','));
  }
  return lines.join('\r\n');
}
