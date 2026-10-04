// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the resource-index method (Russia).
 *
 * Mounted at /api/v1/price-index/resource-index/. Money, indices and
 * percentages are decimal strings in and out and are displayed as served:
 * nothing on this page parses a money string into a JS Number.
 */

import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut } from '@/shared/lib/api';

/* -- Types ---------------------------------------------------------------- */

export type ResourceGroup = 'labor' | 'machine' | 'operator_wages' | 'material';
export type ResourceKind = 'labor' | 'machine' | 'operator' | 'material';

/** Display order of the index groups, as a smeta prints its cost items. */
export const RESOURCE_GROUPS: readonly ResourceGroup[] = ['labor', 'machine', 'operator_wages', 'material'];

export interface ResourceIndexValue {
  id: string;
  region_code: string;
  quarter: string;
  resource_group: ResourceGroup;
  index_value: string;
  source: string;
  is_sample: boolean;
  created_at: string;
  updated_at: string;
}

export interface OverheadNorm {
  id: string;
  work_type_code: string;
  label: string;
  nr_pct: string;
  sp_pct: string;
  source: string;
  is_sample: boolean;
  created_at: string;
  updated_at: string;
}

export interface BOQResourceIndexSettings {
  region_code: string;
  quarter: string;
  default_work_type: string;
  /** position id -> work type code */
  work_types: Record<string, string>;
  /**
   * The person's statement that the resource prices on this bill are base
   * prices of the 2022 federal base. Without it the server indexes only lines
   * whose price basis is `norm` and lists the rest as excluded, so current
   * money is never indexed a second time.
   */
  resources_at_base_prices: boolean;
}

export interface LineOut {
  code: string;
  name: string;
  unit: string;
  kind: ResourceKind;
  quantity: string;
  base_unit_price: string;
  position_quantity: string;
  base_amount: string;
  index_group: ResourceGroup;
  index: string;
  current_amount: string;
  operator_wage_index: string | null;
  operator_wage_current: string | null;
}

export interface PositionOut {
  ref: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: string;
  work_type: string;
  work_type_source: 'chosen' | 'default' | 'explicit';
  lines: LineOut[];
  base_ot: string;
  base_em: string;
  base_otm: string;
  base_m: string;
  base_direct: string;
  ot: string;
  em: string;
  otm: string;
  m: string;
  direct: string;
  fot: string;
  nr_pct: string;
  nr: string;
  sp_pct: string;
  sp: string;
  total: string;
}

export interface WorkTypeSummaryOut {
  work_type: string;
  label: string;
  nr_pct: string;
  sp_pct: string;
  fot: string;
  nr: string;
  sp: string;
}

export interface TotalsOut {
  base_ot: string;
  base_em: string;
  base_otm: string;
  base_m: string;
  base_direct: string;
  ot: string;
  em: string;
  otm: string;
  m: string;
  direct: string;
  fot: string;
  nr: string;
  sp: string;
  total: string;
  vat_rate_pct: string;
  vat: string;
  total_with_vat: string;
}

export type ExcludedReason =
  | 'no_resources'
  | 'unmapped_resource_type'
  | 'foreign_currency'
  | 'no_work_type'
  | 'bad_number'
  | 'not_base_prices'
  | 'base_prices_unconfirmed'
  | 'estimated_resources'
  | 'machine_without_operator_wages';

export interface ExcludedPositionOut {
  position_id: string;
  ordinal: string;
  description: string;
  reason: ExcludedReason;
  detail: string;
}

export interface ResourceIndexEstimate {
  region_code: string;
  quarter: string;
  on_date: string;
  currency: string;
  vat_rate_pct: string;
  vat_tax_name: string;
  indices_used: { resource_group: ResourceGroup; index_value: string; source: string; is_sample: boolean }[];
  norms_used: {
    work_type_code: string;
    label: string;
    nr_pct: string;
    sp_pct: string;
    source: string;
    is_sample: boolean;
  }[];
  uses_sample_data: boolean;
  positions: PositionOut[];
  by_work_type: WorkTypeSummaryOut[];
  totals: TotalsOut;
  excluded: ExcludedPositionOut[];
  priced_count: number;
  excluded_count: number;
  is_complete: boolean;
  boq_id: string | null;
  boq_name: string | null;
  project_id: string | null;
}

export interface ResourceLineIn {
  code?: string;
  name?: string;
  unit?: string;
  kind: ResourceKind;
  quantity: string;
  base_unit_price: string;
}

export interface PositionIn {
  ordinal?: string;
  description?: string;
  unit?: string;
  quantity: string;
  work_type: string;
  resources: ResourceLineIn[];
}

/* -- Pure helpers (unit-tested) ------------------------------------------- */

const QUARTER_RE = /^\d{4}-Q[1-4]$/;

/** Normalise "2026-q1" to "2026-Q1"; null when it is not a year and a quarter 1-4. */
export function normaliseQuarter(raw: string | null | undefined): string | null {
  const text = (raw ?? '').trim().toUpperCase();
  return QUARTER_RE.test(text) ? text : null;
}

/** Distinct region codes that carry at least one index, sorted. */
export function regionsOf(indices: readonly ResourceIndexValue[]): string[] {
  return Array.from(new Set(indices.map((i) => i.region_code))).sort();
}

/** Distinct quarters entered for a region, newest first. */
export function quartersOf(indices: readonly ResourceIndexValue[], region: string): string[] {
  return Array.from(new Set(indices.filter((i) => i.region_code === region).map((i) => i.quarter)))
    .sort()
    .reverse();
}

/** The groups with no index for a region and quarter, in display order. */
export function missingGroups(
  indices: readonly ResourceIndexValue[],
  region: string,
  quarter: string,
): ResourceGroup[] {
  const present = new Set(
    indices.filter((i) => i.region_code === region && i.quarter === quarter).map((i) => i.resource_group),
  );
  return RESOURCE_GROUPS.filter((g) => !present.has(g));
}

/**
 * Group the integer part of a decimal string in threes with a thin space,
 * keeping every digit the server sent ("58242.70" -> "58 242.70"). String work
 * only, so a kopeck is never rounded by a float.
 */
export function formatAmount(raw: string | null | undefined): string {
  if (raw == null || raw === '') return '';
  const text = String(raw).trim();
  const negative = text.startsWith('-');
  const unsigned = negative ? text.slice(1) : text;
  const [intPart = '', frac] = unsigned.split('.');
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  return `${negative ? '-' : ''}${grouped}${frac !== undefined ? `.${frac}` : ''}`;
}

/** Trim trailing zeros of a factor or percentage ("1.250000" -> "1.25", "103.0000" -> "103"). */
export function formatFactorString(raw: string | null | undefined): string {
  if (raw == null || raw === '') return '';
  const text = String(raw).trim();
  if (!text.includes('.')) return text;
  const trimmed = text.replace(/0+$/, '').replace(/\.$/, '');
  return trimmed === '' || trimmed === '-' ? '0' : trimmed;
}

/** A refusal of the computation as the server explains it (422 with a code). */
export interface ResourceIndexRefusal {
  code:
    | 'missing_index'
    | 'missing_overhead_norm'
    | 'missing_operator_wages'
    | 'invalid_index'
    | 'invalid_input'
    | 'vat_unresolved'
    | 'settings_incomplete'
    | string;
  message: string;
  groups?: ResourceGroup[];
  work_types?: string[];
  /** Ordinals of the positions with machine lines and no operator line. */
  positions?: string[];
  region_code?: string;
  quarter?: string;
  on_date?: string;
}

/** Read the structured refusal out of an API error; null for any other failure. */
export function refusalOf(err: unknown): ResourceIndexRefusal | null {
  if (!(err instanceof ApiError) || err.status !== 422) return null;
  const body = err.body as { detail?: unknown } | null | undefined;
  const detail = body && typeof body === 'object' ? body.detail : undefined;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  const d = detail as Record<string, unknown>;
  if (typeof d.code !== 'string') return null;
  return {
    code: d.code,
    message: typeof d.message === 'string' ? d.message : '',
    groups: Array.isArray(d.groups) ? (d.groups as ResourceGroup[]) : undefined,
    work_types: Array.isArray(d.work_types) ? (d.work_types as string[]) : undefined,
    positions: Array.isArray(d.positions) ? (d.positions as string[]) : undefined,
    region_code: typeof d.region_code === 'string' ? d.region_code : undefined,
    quarter: typeof d.quarter === 'string' ? d.quarter : undefined,
    on_date: typeof d.on_date === 'string' ? d.on_date : undefined,
  };
}

/** The display text of the worked example; the page passes it in translated. */
export interface WorkedExampleLabels {
  concreteBlinding: string;
  handExcavation: string;
  workersGrade35: string;
  workersGrade2: string;
  concretePump: string;
  pumpOperator: string;
  concrete: string;
  sand: string;
  gravel: string;
  manHour: string;
  machineHour: string;
}

/**
 * A small worked example, the one the backend tests check figure by figure:
 * two positions with workers, a machine and its operator, and materials.
 * Lets a person see every multiplication before their own bill carries a
 * resource breakdown. Numbers are fixed; every word comes from `labels`.
 */
export function workedExamplePositions(workTypeA: string, workTypeB: string, labels: WorkedExampleLabels): PositionIn[] {
  const l = labels;
  return [
    {
      ordinal: '1',
      description: l.concreteBlinding,
      unit: '100 m3',
      quantity: '2',
      work_type: workTypeA,
      resources: [
        { code: 'L1', name: l.workersGrade35, unit: l.manHour, kind: 'labor', quantity: '12.5', base_unit_price: '400.00' },
        { code: 'M1', name: l.concretePump, unit: l.machineHour, kind: 'machine', quantity: '3', base_unit_price: '1000.00' },
        { code: 'O1', name: l.pumpOperator, unit: l.manHour, kind: 'operator', quantity: '3', base_unit_price: '500.00' },
        { code: 'MAT1', name: l.concrete, unit: 'm3', kind: 'material', quantity: '10', base_unit_price: '250.00' },
      ],
    },
    {
      ordinal: '2',
      description: l.handExcavation,
      unit: 'm3',
      quantity: '1.5',
      work_type: workTypeB,
      resources: [
        { code: 'L2', name: l.workersGrade2, unit: l.manHour, kind: 'labor', quantity: '2.4', base_unit_price: '280.75' },
        { code: 'MAT2A', name: l.sand, unit: 'm3', kind: 'material', quantity: '0.5', base_unit_price: '13.47' },
        { code: 'MAT2B', name: l.gravel, unit: 'm3', kind: 'material', quantity: '0.5', base_unit_price: '13.47' },
      ],
    },
  ];
}

/* -- Reference data ------------------------------------------------------- */

/** One page of a reference list as the server sends it. */
export interface ListPage<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

/**
 * Read every page of a reference list. The page picks regions and quarters
 * and names missing index groups from these lists, so a first page read as the
 * whole set would be wrong rather than short. Stops on an empty page as well,
 * so a total that moves under the reader cannot loop forever.
 */
export async function collectPages<T>(fetchPage: (offset: number) => Promise<ListPage<T> | null | undefined>): Promise<T[]> {
  const all: T[] = [];
  for (;;) {
    const page = await fetchPage(all.length);
    const items = page && Array.isArray(page.items) ? page.items : [];
    all.push(...items);
    if (items.length === 0 || !page || all.length >= page.total) return all;
  }
}

export async function listResourceIndices(): Promise<ResourceIndexValue[]> {
  return collectPages((offset) =>
    apiGet<ListPage<ResourceIndexValue>>(`/v1/price-index/resource-index/indices/?offset=${offset}`),
  );
}

export async function createResourceIndex(data: {
  region_code: string;
  quarter: string;
  resource_group: ResourceGroup;
  index_value: string;
  source: string;
}): Promise<ResourceIndexValue> {
  return apiPost<ResourceIndexValue>(`/v1/price-index/resource-index/indices/`, data);
}

export async function updateResourceIndex(
  id: string,
  data: { index_value?: string; source?: string },
): Promise<ResourceIndexValue> {
  return apiPatch<ResourceIndexValue>(`/v1/price-index/resource-index/indices/${id}/`, data);
}

export async function deleteResourceIndex(id: string): Promise<void> {
  return apiDelete(`/v1/price-index/resource-index/indices/${id}/`);
}

export async function listOverheadNorms(): Promise<OverheadNorm[]> {
  return collectPages((offset) =>
    apiGet<ListPage<OverheadNorm>>(`/v1/price-index/resource-index/norms/?offset=${offset}`),
  );
}

export async function createOverheadNorm(data: {
  work_type_code: string;
  label: string;
  nr_pct: string;
  sp_pct: string;
  source: string;
}): Promise<OverheadNorm> {
  return apiPost<OverheadNorm>(`/v1/price-index/resource-index/norms/`, data);
}

export async function updateOverheadNorm(
  id: string,
  data: { label?: string; nr_pct?: string; sp_pct?: string; source?: string },
): Promise<OverheadNorm> {
  return apiPatch<OverheadNorm>(`/v1/price-index/resource-index/norms/${id}/`, data);
}

export async function deleteOverheadNorm(id: string): Promise<void> {
  return apiDelete(`/v1/price-index/resource-index/norms/${id}/`);
}

/* -- BOQ ------------------------------------------------------------------ */

export async function getBoqSettings(boqId: string): Promise<BOQResourceIndexSettings> {
  return apiGet<BOQResourceIndexSettings>(`/v1/price-index/resource-index/boqs/${boqId}/settings/`);
}

export async function saveBoqSettings(
  boqId: string,
  settings: BOQResourceIndexSettings,
): Promise<BOQResourceIndexSettings> {
  return apiPut<BOQResourceIndexSettings>(`/v1/price-index/resource-index/boqs/${boqId}/settings/`, settings);
}

export async function computeBoq(
  boqId: string,
  settings: BOQResourceIndexSettings & { on_date?: string | null },
): Promise<ResourceIndexEstimate> {
  return apiPost<ResourceIndexEstimate>(`/v1/price-index/resource-index/boqs/${boqId}/compute/`, {
    ...settings,
    on_date: settings.on_date || null,
  });
}

export async function computeExplicit(data: {
  region_code: string;
  quarter: string;
  on_date?: string | null;
  positions: PositionIn[];
}): Promise<ResourceIndexEstimate> {
  return apiPost<ResourceIndexEstimate>(`/v1/price-index/resource-index/compute/`, { ...data, on_date: data.on_date || null });
}
