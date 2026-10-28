// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Carbon & Sustainability module.
 *
 * Backed by /api/v1/carbon/ — see backend/app/modules/carbon/router.py
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type EPDSource = 'oekobaudat' | 'ice' | 'ec3' | 'custom';
export type Stage = 'a1a3' | 'a4' | 'a5' | 'b' | 'c' | 'd';

/** How an embodied-carbon entry got into the inventory.
 *  - `manual`: keyed in by a user.
 *  - `auto_enriched`: proposed by the BIM auto-enrich pass (6D).
 *  - `boq_derived`: created from a priced BOQ position. */
export type EmbodiedSource = 'manual' | 'auto_enriched' | 'boq_derived';
export type InventoryStatus = 'draft' | 'baseline' | 'current' | 'archived';
export type TargetStatus = 'active' | 'met' | 'missed' | 'abandoned';
export type Framework = 'ghg_protocol' | 'gri' | 'issb' | 'custom';

export interface EPDRecord {
  id: string;
  epd_id: string;
  source: EPDSource;
  material_class: string;
  product_name: string;
  manufacturer?: string | null;
  region: string;
  declared_unit: string;
  gwp_a1a3: number | string;
  gwp_a4?: number | string | null;
  gwp_a5?: number | string | null;
  gwp_b_total?: number | string | null;
  gwp_c_total?: number | string | null;
  gwp_d_credits?: number | string | null;
  validity_until?: string | null;
  document_url?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MaterialCarbonFactor {
  id: string;
  cost_item_id?: string | null;
  epd_id?: string | null;
  manual_override_factor?: number | string | null;
  unit_for_factor: string;
  region: string;
  last_reviewed_at?: string | null;
  confidence: 'high' | 'medium' | 'low';
  notes?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CarbonInventory {
  id: string;
  project_id: string;
  name: string;
  scope: 'cradle_to_gate' | 'cradle_to_grave' | 'operational';
  as_of_date?: string | null;
  status: InventoryStatus;
  totals: Record<string, unknown>;
  notes?: string | null;
  created_by?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EmbodiedEntry {
  id: string;
  inventory_id: string;
  /** Free-text human label for the element (name/type), e.g. "Wall - C30/37".
   *  Carried for every entry regardless of source. */
  element_ref?: string | null;
  /** Plain GUID link to the BIM element this entry was enriched from, when it
   *  came from a BIM model. `null` for manual / BOQ-derived entries. */
  element_id?: string | null;
  /** Provenance of the entry. Absent on legacy rows (treated as manual). */
  source?: EmbodiedSource | null;
  /** Confidence of the material -> factor match for auto-enriched entries. */
  match_confidence?: 'high' | 'medium' | 'low' | null;
  description: string;
  quantity: number | string;
  unit: string;
  factor_id?: string | null;
  factor_value_used: number | string;
  carbon_kg: number | string;
  stage: Stage;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ScopeEntry {
  id: string;
  inventory_id: string;
  period_start: string;
  period_end: string;
  total_co2e_kg: number | string;
  notes?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Scope1Entry extends ScopeEntry {
  fuel_type: string;
  litres_or_m3: number | string;
  emission_factor_kg_co2e_per_unit: number | string;
  source: string;
  source_ref?: string | null;
}

export interface Scope2Entry extends ScopeEntry {
  energy_type: string;
  kwh: number | string;
  emission_factor_kg_co2e_per_kwh: number | string;
  market_or_location: string;
  supplier_name?: string | null;
}

export interface Scope3Entry extends ScopeEntry {
  category: string;
  description: string;
  activity_data: number | string;
  activity_unit: string;
  emission_factor: number | string;
}

export interface InventoryTotals {
  inventory_id: string;
  embodied_a1a3: number | string;
  embodied_a4: number | string;
  embodied_a5: number | string;
  embodied_a1a5: number | string;
  embodied_b: number | string;
  embodied_c: number | string;
  embodied_d: number | string;
  scope1: number | string;
  scope2: number | string;
  scope3: number | string;
  operational: number | string;
  end_of_life: number | string;
  total: number | string;
}

export interface CarbonTarget {
  id: string;
  project_id: string;
  name: string;
  target_type: 'intensity_per_m2' | 'intensity_per_unit' | 'absolute';
  baseline_value: number | string;
  target_value: number | string;
  baseline_year: number;
  target_year: number;
  scope_set: string[];
  status: TargetStatus;
  notes?: string | null;
  created_by?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TargetProgress {
  target_id: string;
  current_value: number | string;
  baseline_value: number | string;
  target_value: number | string;
  progress_pct: number;
  met: boolean;
  as_of_date?: string | null;
}

export interface SustainabilityReport {
  id: string;
  project_id: string;
  inventory_id?: string | null;
  period_start: string;
  period_end: string;
  framework: Framework;
  totals: Record<string, unknown>;
  narrative?: string | null;
  generated_at?: string | null;
  generated_by?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CarbonDashboard {
  project_id: string;
  total_embodied_kg: number | string;
  total_operational_kg: number | string;
  total_kg: number | string;
  inventory_count: number;
  target_count: number;
  targets_met: number;
  targets_missed: number;
  intensity_per_m2?: number | string | null;
  latest_report_id?: string | null;
}

export interface AlternativeOption {
  factor_id: string;
  factor_value: number | string;
  carbon_kg: number | string;
  savings_kg: number | string;
  savings_pct: number;
  confidence: string;
}

export interface AlternativeComparison {
  entry_id: string;
  current_factor_value: number | string;
  current_carbon_kg: number | string;
  options: AlternativeOption[];
}

/* ── EPDs ──────────────────────────────────────────────────────────────── */

export function listEPDs(params?: {
  material_class?: string;
  region?: string;
  limit?: number;
}): Promise<EPDRecord[]> {
  const qs = new URLSearchParams();
  if (params?.material_class) qs.set('material_class', params.material_class);
  if (params?.region) qs.set('region', params.region);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<EPDRecord[]>(`/v1/carbon/epd${q ? `?${q}` : ''}`);
}

export function createEPD(data: {
  epd_id: string;
  source?: EPDSource;
  material_class: string;
  product_name: string;
  manufacturer?: string | null;
  region?: string;
  declared_unit?: string;
  gwp_a1a3?: number | string;
  gwp_a4?: number | string | null;
  gwp_a5?: number | string | null;
  gwp_b_total?: number | string | null;
  gwp_c_total?: number | string | null;
  gwp_d_credits?: number | string | null;
  validity_until?: string | null;
  document_url?: string | null;
}): Promise<EPDRecord> {
  return apiPost<EPDRecord>('/v1/carbon/epd', data);
}

export function updateEPD(
  id: string,
  data: Partial<{
    source: EPDSource;
    material_class: string;
    product_name: string;
    manufacturer: string | null;
    region: string;
    declared_unit: string;
    gwp_a1a3: number | string;
    gwp_a4: number | string | null;
    gwp_a5: number | string | null;
    gwp_b_total: number | string | null;
    gwp_c_total: number | string | null;
    gwp_d_credits: number | string | null;
    validity_until: string | null;
    document_url: string | null;
  }>,
): Promise<EPDRecord> {
  return apiPatch<EPDRecord>(`/v1/carbon/epd/${id}`, data);
}

export function deleteEPD(id: string): Promise<void> {
  return apiDelete(`/v1/carbon/epd/${id}`);
}

/* ── Inventories ───────────────────────────────────────────────────────── */

export function listInventories(projectId: string): Promise<CarbonInventory[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', projectId);
  return apiGet<CarbonInventory[]>(`/v1/carbon/inventories?${qs.toString()}`);
}

export function getInventory(id: string): Promise<CarbonInventory> {
  return apiGet<CarbonInventory>(`/v1/carbon/inventories/${id}`);
}

export function createInventory(data: {
  project_id: string;
  name?: string;
  scope?: 'cradle_to_gate' | 'cradle_to_grave' | 'operational';
  as_of_date?: string;
  status?: InventoryStatus;
  notes?: string;
}): Promise<CarbonInventory> {
  return apiPost<CarbonInventory>('/v1/carbon/inventories', data);
}

export function updateInventory(
  id: string,
  data: Partial<{
    name: string;
    scope: 'cradle_to_gate' | 'cradle_to_grave' | 'operational';
    as_of_date: string | null;
    status: InventoryStatus;
    notes: string | null;
  }>,
): Promise<CarbonInventory> {
  return apiPatch<CarbonInventory>(`/v1/carbon/inventories/${id}`, data);
}

export function deleteInventory(id: string): Promise<void> {
  return apiDelete(`/v1/carbon/inventories/${id}`);
}

export function getInventoryTotals(id: string): Promise<InventoryTotals> {
  return apiGet<InventoryTotals>(`/v1/carbon/inventories/${id}/totals`);
}

export function listEmbodiedEntries(
  inventoryId: string,
  params?: { stage?: Stage; limit?: number },
): Promise<EmbodiedEntry[]> {
  const qs = new URLSearchParams();
  if (params?.stage) qs.set('stage', params.stage);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<EmbodiedEntry[]>(
    `/v1/carbon/inventories/${inventoryId}/embodied${q ? `?${q}` : ''}`,
  );
}

export function createEmbodiedEntry(
  inventoryId: string,
  data: {
    inventory_id: string;
    element_ref?: string | null;
    description?: string;
    quantity?: number | string;
    unit?: string;
    factor_value_used?: number | string;
    carbon_kg?: number | string;
    stage?: Stage;
  },
): Promise<EmbodiedEntry> {
  return apiPost<EmbodiedEntry>(
    `/v1/carbon/inventories/${inventoryId}/embodied`,
    data,
  );
}

export function updateEmbodiedEntry(
  entryId: string,
  data: Partial<{
    element_ref: string | null;
    description: string;
    quantity: number | string;
    unit: string;
    factor_value_used: number | string;
    carbon_kg: number | string;
    stage: Stage;
  }>,
): Promise<EmbodiedEntry> {
  return apiPatch<EmbodiedEntry>(`/v1/carbon/embodied/${entryId}`, data);
}

export function deleteEmbodiedEntry(entryId: string): Promise<void> {
  return apiDelete(`/v1/carbon/embodied/${entryId}`);
}

export function listScope1(inventoryId: string): Promise<Scope1Entry[]> {
  return apiGet<Scope1Entry[]>(`/v1/carbon/inventories/${inventoryId}/scope1`);
}
export function listScope2(inventoryId: string): Promise<Scope2Entry[]> {
  return apiGet<Scope2Entry[]>(`/v1/carbon/inventories/${inventoryId}/scope2`);
}
export function listScope3(inventoryId: string): Promise<Scope3Entry[]> {
  return apiGet<Scope3Entry[]>(`/v1/carbon/inventories/${inventoryId}/scope3`);
}

/* ── Scope 1 / 2 / 3 mutations ─────────────────────────────────────────── */

export function createScope1(data: {
  inventory_id: string;
  period_start: string;
  period_end: string;
  fuel_type?: string;
  litres_or_m3?: number | string;
  emission_factor_kg_co2e_per_unit?: number | string;
  source?: string;
  notes?: string | null;
}): Promise<Scope1Entry> {
  return apiPost<Scope1Entry>('/v1/carbon/scope1', data);
}
export function updateScope1(
  id: string,
  data: Partial<{
    period_start: string;
    period_end: string;
    fuel_type: string;
    litres_or_m3: number | string;
    emission_factor_kg_co2e_per_unit: number | string;
    source: string;
    notes: string | null;
  }>,
): Promise<Scope1Entry> {
  return apiPatch<Scope1Entry>(`/v1/carbon/scope1/${id}`, data);
}
export function deleteScope1(id: string): Promise<void> {
  return apiDelete(`/v1/carbon/scope1/${id}`);
}

export function createScope2(data: {
  inventory_id: string;
  period_start: string;
  period_end: string;
  energy_type?: string;
  kwh?: number | string;
  emission_factor_kg_co2e_per_kwh?: number | string;
  market_or_location?: string;
  supplier_name?: string | null;
  notes?: string | null;
}): Promise<Scope2Entry> {
  return apiPost<Scope2Entry>('/v1/carbon/scope2', data);
}
export function updateScope2(
  id: string,
  data: Partial<{
    period_start: string;
    period_end: string;
    energy_type: string;
    kwh: number | string;
    emission_factor_kg_co2e_per_kwh: number | string;
    market_or_location: string;
    supplier_name: string | null;
    notes: string | null;
  }>,
): Promise<Scope2Entry> {
  return apiPatch<Scope2Entry>(`/v1/carbon/scope2/${id}`, data);
}
export function deleteScope2(id: string): Promise<void> {
  return apiDelete(`/v1/carbon/scope2/${id}`);
}

export function createScope3(data: {
  inventory_id: string;
  period_start: string;
  period_end: string;
  category?: string;
  description?: string;
  activity_data?: number | string;
  activity_unit?: string;
  emission_factor?: number | string;
}): Promise<Scope3Entry> {
  return apiPost<Scope3Entry>('/v1/carbon/scope3', data);
}
export function updateScope3(
  id: string,
  data: Partial<{
    period_start: string;
    period_end: string;
    category: string;
    description: string;
    activity_data: number | string;
    activity_unit: string;
    emission_factor: number | string;
  }>,
): Promise<Scope3Entry> {
  return apiPatch<Scope3Entry>(`/v1/carbon/scope3/${id}`, data);
}
export function deleteScope3(id: string): Promise<void> {
  return apiDelete(`/v1/carbon/scope3/${id}`);
}

export function getAlternatives(
  inventoryId: string,
  entryId: string,
): Promise<AlternativeComparison> {
  const qs = new URLSearchParams();
  qs.set('entry_id', entryId);
  return apiGet<AlternativeComparison>(
    `/v1/carbon/inventories/${inventoryId}/alternatives?${qs.toString()}`,
  );
}

/* ── Targets ───────────────────────────────────────────────────────────── */

export function listTargets(projectId: string): Promise<CarbonTarget[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', projectId);
  return apiGet<CarbonTarget[]>(`/v1/carbon/targets?${qs.toString()}`);
}

export function createTarget(data: {
  project_id: string;
  name?: string;
  target_type?: 'intensity_per_m2' | 'intensity_per_unit' | 'absolute';
  baseline_value: number | string;
  target_value: number | string;
  baseline_year: number;
  target_year: number;
  scope_set?: string[];
}): Promise<CarbonTarget> {
  return apiPost<CarbonTarget>('/v1/carbon/targets', data);
}

export function updateTarget(
  id: string,
  data: Partial<{
    name: string;
    baseline_value: number | string;
    target_value: number | string;
    status: TargetStatus;
  }>,
): Promise<CarbonTarget> {
  return apiPatch<CarbonTarget>(`/v1/carbon/targets/${id}`, data);
}

export function deleteTarget(id: string): Promise<void> {
  return apiDelete(`/v1/carbon/targets/${id}`);
}

export function getTargetProgress(id: string): Promise<TargetProgress> {
  return apiGet<TargetProgress>(`/v1/carbon/targets/${id}/progress`);
}

/* ── Reports ───────────────────────────────────────────────────────────── */

export function listReports(projectId: string): Promise<SustainabilityReport[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', projectId);
  return apiGet<SustainabilityReport[]>(`/v1/carbon/reports?${qs.toString()}`);
}

export function generateReport(payload: {
  project_id: string;
  inventory_id?: string | null;
  period_start: string;
  period_end: string;
  framework?: Framework;
  project_area_m2?: number;
  narrative?: string;
}): Promise<SustainabilityReport> {
  return apiPost<SustainabilityReport>('/v1/carbon/reports/generate', payload);
}

export function deleteReport(id: string): Promise<void> {
  return apiDelete(`/v1/carbon/reports/${id}`);
}

/* ── Dashboard ─────────────────────────────────────────────────────────── */

export function getCarbonDashboard(projectId: string): Promise<CarbonDashboard> {
  const qs = new URLSearchParams();
  qs.set('project_id', projectId);
  return apiGet<CarbonDashboard>(`/v1/carbon/dashboard?${qs.toString()}`);
}

/* ── Material factors ──────────────────────────────────────────────────── */

export function listMaterialFactors(params?: {
  cost_item_id?: string;
  region?: string;
  limit?: number;
}): Promise<MaterialCarbonFactor[]> {
  const qs = new URLSearchParams();
  if (params?.cost_item_id) qs.set('cost_item_id', params.cost_item_id);
  if (params?.region) qs.set('region', params.region);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<MaterialCarbonFactor[]>(
    `/v1/carbon/material-factors${q ? `?${q}` : ''}`,
  );
}

/* ── BOQ position → embodied carbon assignment ─────────────────────────── */

/** Result of assigning a BOQ position to an inventory (subset the UI needs). */
export interface AssignBoqPositionResult {
  id: string;
  inventory_id: string;
  element_ref: string | null;
  stage: string;
  carbon_kg: string;
}

/**
 * Create an embodied-carbon entry tied to a BOQ position, using a material
 * factor to compute kgCO2e. Wires the existing
 * POST /carbon/inventories/{id}/assign-boq-position endpoint (CONN-60).
 */
export function assignBoqPosition(
  inventoryId: string,
  payload: {
    boq_position_id: string;
    material_factor_id: string;
    quantity: number | string;
    quantity_unit: string;
    stage?: Stage;
    density_kg_per_m3?: number | string | null;
  },
): Promise<AssignBoqPositionResult> {
  return apiPost<AssignBoqPositionResult>(
    `/v1/carbon/inventories/${inventoryId}/assign-boq-position`,
    payload,
  );
}

/* ── BIM auto-enrich (6D) ───────────────────────────────────────────────── */

/**
 * Result of an auto-enrich pass over a BIM model.
 *
 * `entries` carries the embodied entries: when `dry_run` is true they are
 * proposals (nothing was written), otherwise they are the persisted rows.
 * The three counters always describe what the pass considered:
 * `created` matched and (would be) added, `skipped_no_match` had no material
 * factor, `skipped_no_quantity` had no usable geometry quantity.
 */
export interface AutoEnrichBimResult {
  created: number;
  skipped_no_match: number;
  skipped_no_quantity: number;
  /** Elements skipped because this inventory already has an auto-enriched
   *  entry for them (idempotency: re-running never duplicates rows). */
  skipped_existing?: number;
  entries: EmbodiedEntry[];
}

/**
 * Match a BIM model's element materials to carbon factors and propose (or
 * persist) embodied entries. Always preview with `dry_run: true` first, then
 * confirm with `dry_run: false` - AI proposes, the user confirms.
 *
 * Wires POST /carbon/inventories/{id}/auto-enrich-bim?model_id=&dry_run=.
 * Marked long-running: matching scans every element in the model.
 */
export function autoEnrichFromBim(
  inventoryId: string,
  params: { model_id: string; dry_run: boolean },
): Promise<AutoEnrichBimResult> {
  const qs = new URLSearchParams();
  qs.set('model_id', params.model_id);
  qs.set('dry_run', String(params.dry_run));
  return apiPost<AutoEnrichBimResult>(
    `/v1/carbon/inventories/${inventoryId}/auto-enrich-bim?${qs.toString()}`,
    {},
    { longRunning: true },
  );
}

/* --- 6D Phase 2: operational carbon (B6), whole-life cost, whole-life view --- */

/** Draft/confirmed status shared by the computed 6D lines. AI proposes the
 *  line as `draft`; a human confirm flips it to `confirmed`. */
export type EntryStatus = 'draft' | 'confirmed';

/** A B6 use-phase operational-carbon line. Computed rows land as `draft` with a
 *  `match_confidence` band for the human accept/reject step. */
export interface OperationalCarbonEntry {
  id: string;
  inventory_id: string;
  element_id?: string | null;
  element_ref?: string | null;
  system: string;
  description: string;
  end_use: string;
  energy_source: string;
  annual_energy_kwh: number | string;
  grid_country: string;
  grid_year?: number | null;
  grid_factor_kg_co2e_per_kwh: number | string;
  study_period_years: number;
  annual_carbon_kg: number | string;
  carbon_kg: number | string;
  stage: string;
  source: EmbodiedSource | string;
  match_confidence?: 'high' | 'medium' | 'low' | null;
  status: EntryStatus;
  assumptions?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Result of an operational-carbon compute pass (dry-run proposals or the
 *  persisted draft rows). */
export interface OperationalCarbonComputeResult {
  inventory_id: string;
  model_id?: string | null;
  dry_run: boolean;
  study_period_years: number;
  grid_factor_kg_co2e_per_kwh: number | string;
  grid_factor_source: string;
  created: number;
  skipped_existing: number;
  skipped_no_energy: number;
  total_b6_carbon_kg: number | string;
  entries: OperationalCarbonEntry[];
}

/** An ISO 15686-5 whole-life cost line. Computed rows land as `draft` with a
 *  `confidence` band for the human accept/reject step. */
export interface LifeCycleCostEntry {
  id: string;
  inventory_id: string;
  element_id?: string | null;
  element_ref?: string | null;
  description: string;
  category: string;
  currency: string;
  capex: number | string;
  annual_opex: number | string;
  replacement_cost: number | string;
  service_life_years: number;
  eol_cost: number | string;
  discount_rate: number | string;
  study_period_years: number;
  capex_pv: number | string;
  opex_pv: number | string;
  replacement_pv: number | string;
  replacement_count: number;
  eol_pv: number | string;
  whole_life_cost: number | string;
  source: EmbodiedSource | string;
  confidence?: 'high' | 'medium' | 'low' | null;
  status: EntryStatus;
  assumptions?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Result of a whole-life cost compute pass (dry-run proposals or persisted
 *  draft rows). */
export interface LifeCycleCostComputeResult {
  inventory_id: string;
  model_id?: string | null;
  dry_run: boolean;
  currency: string;
  discount_rate: number | string;
  study_period_years: number;
  created: number;
  skipped_existing: number;
  skipped_no_cost: number;
  total_whole_life_cost: number | string;
  entries: LifeCycleCostEntry[];
}

/** EN 15978 whole-life carbon A-B-C-D breakdown (kgCO2e). `whole_life_total`
 *  is A1-A5 + B + C; module D is reported separately and never in the total. */
export interface WholeLifeCarbonBreakdown {
  a1a3: number | string;
  a4: number | string;
  a5: number | string;
  a1a5: number | string;
  b_embodied: number | string;
  b6_operational: number | string;
  b_total: number | string;
  c_end_of_life: number | string;
  d_beyond: number | string;
  whole_life_total: number | string;
}

/** ISO 15686-5 whole-life cost breakdown (present values). */
export interface WholeLifeCostBreakdown {
  currency: string;
  capex: number | string;
  opex_pv: number | string;
  replacement_pv: number | string;
  eol_pv: number | string;
  residual_value_pv: number | string;
  whole_life_cost: number | string;
  entry_count: number;
}

/** How much of the project BIM each figure is linked to. */
export interface WholeLifeCoverage {
  bim_element_count: number;
  embodied_linked_count: number;
  operational_linked_count: number;
  lcc_linked_count: number;
  embodied_coverage_pct: number;
  operational_coverage_pct: number;
  lcc_coverage_pct: number;
}

/** Combined 6D whole-life rollup: carbon and cost side by side, with coverage
 *  and an optional monetised whole-life carbon figure. */
export interface WholeLifeSummary {
  inventory_id: string;
  study_period_years: number;
  carbon: WholeLifeCarbonBreakdown;
  cost: WholeLifeCostBreakdown;
  coverage: WholeLifeCoverage;
  carbon_price_per_tonne?: number | string | null;
  cost_of_whole_life_carbon?: number | string | null;
}

/** A single explicit whole-life cost line (used without BIM cost data). */
export interface LccLineInput {
  description?: string;
  category?: string;
  capex?: number | string;
  annual_opex?: number | string | null;
  replacement_cost?: number | string | null;
  service_life_years?: number | null;
  eol_cost?: number | string | null;
}

/**
 * Combined whole-life rollup for an inventory. Pass `carbonPricePerTonne` to
 * also get the monetised whole-life carbon back.
 * Wires GET /carbon/inventories/{id}/whole-life.
 */
export function getWholeLife(
  inventoryId: string,
  carbonPricePerTonne?: number | string | null,
): Promise<WholeLifeSummary> {
  const qs = new URLSearchParams();
  if (
    carbonPricePerTonne !== undefined &&
    carbonPricePerTonne !== null &&
    carbonPricePerTonne !== ''
  ) {
    qs.set('carbon_price_per_tonne', String(carbonPricePerTonne));
  }
  const q = qs.toString();
  return apiGet<WholeLifeSummary>(
    `/v1/carbon/inventories/${inventoryId}/whole-life${q ? `?${q}` : ''}`,
  );
}

/**
 * Compute B6 operational carbon from the project BIM. Always preview with
 * `dryRun: true` first, then persist with `dryRun: false` - AI proposes, the
 * user confirms. Marked long-running: it scans every element.
 * Wires POST /carbon/inventories/{id}/operational-carbon/compute?dry_run=.
 */
export function computeOperationalCarbon(
  inventoryId: string,
  body: {
    model_id?: string | null;
    grid_country?: string;
    grid_year?: number;
    grid_factor_kg_co2e_per_kwh?: number | string | null;
    study_period_years?: number;
    end_use?: string;
    gross_floor_area_m2?: number | string | null;
    modelled_intensity_kwh_per_m2_year?: number | string | null;
  },
  dryRun: boolean,
): Promise<OperationalCarbonComputeResult> {
  const qs = new URLSearchParams();
  qs.set('dry_run', String(dryRun));
  return apiPost<OperationalCarbonComputeResult>(
    `/v1/carbon/inventories/${inventoryId}/operational-carbon/compute?${qs.toString()}`,
    body,
    { longRunning: true },
  );
}

export function listOperationalCarbon(inventoryId: string): Promise<OperationalCarbonEntry[]> {
  return apiGet<OperationalCarbonEntry[]>(
    `/v1/carbon/inventories/${inventoryId}/operational-carbon`,
  );
}

/** Human accept: flip a draft B6 line to `confirmed`. */
export function confirmOperationalCarbon(entryId: string): Promise<OperationalCarbonEntry> {
  return apiPost<OperationalCarbonEntry>(`/v1/carbon/operational-carbon/${entryId}/confirm`, {});
}

/** Human reject: delete a draft (or any) B6 line. */
export function deleteOperationalCarbon(entryId: string): Promise<void> {
  return apiDelete(`/v1/carbon/operational-carbon/${entryId}`);
}

/**
 * Compute ISO 15686-5 whole-life cost from the project BIM (plus any explicit
 * `lines`). Preview with `dryRun: true`, then persist with `dryRun: false`.
 * Wires POST /carbon/inventories/{id}/life-cycle-cost/compute?dry_run=.
 */
export function computeLifeCycleCost(
  inventoryId: string,
  body: {
    model_id?: string | null;
    discount_rate?: number | string;
    study_period_years?: number;
    currency?: string;
    default_capex?: number | string | null;
    opex_rate_pct?: number | string;
    eol_rate_pct?: number | string;
    default_service_life_years?: number;
    lines?: LccLineInput[];
  },
  dryRun: boolean,
): Promise<LifeCycleCostComputeResult> {
  const qs = new URLSearchParams();
  qs.set('dry_run', String(dryRun));
  return apiPost<LifeCycleCostComputeResult>(
    `/v1/carbon/inventories/${inventoryId}/life-cycle-cost/compute?${qs.toString()}`,
    body,
    { longRunning: true },
  );
}

export function listLifeCycleCost(inventoryId: string): Promise<LifeCycleCostEntry[]> {
  return apiGet<LifeCycleCostEntry[]>(`/v1/carbon/inventories/${inventoryId}/life-cycle-cost`);
}

/** Human accept: flip a draft whole-life cost line to `confirmed`. */
export function confirmLifeCycleCost(entryId: string): Promise<LifeCycleCostEntry> {
  return apiPost<LifeCycleCostEntry>(`/v1/carbon/life-cycle-cost/${entryId}/confirm`, {});
}

/** Human reject: delete a draft (or any) whole-life cost line. */
export function deleteLifeCycleCost(entryId: string): Promise<void> {
  return apiDelete(`/v1/carbon/life-cycle-cost/${entryId}`);
}
