// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';

/**
 * Conceptual (ROM) estimate API client and types.
 *
 * Every monetary / ratio field arrives from the backend as a Decimal-encoded
 * STRING (never a JS number) to preserve precision. Keep these typed as
 * `string` and only coerce at the moment of formatting via the money helpers.
 */

/** A selectable building type with its indicative base rate and accuracy band. */
export interface RomBuildingTypeOption {
  key: string;
  label: string;
  base_rate_per_m2: string;
  accuracy_low_pct: string;
  accuracy_high_pct: string;
}

/** A selectable quality level or region with its multiplier. */
export interface RomFactorOption {
  key: string;
  label: string;
  factor: string;
}

/** One of the six elemental categories (stable key + default label). */
export interface RomElementOption {
  key: string;
  label: string;
}

/** Everything the form needs: building types, quality levels, regions, elements. */
export interface RomReference {
  building_types: RomBuildingTypeOption[];
  quality_levels: RomFactorOption[];
  regions: RomFactorOption[];
  elements: RomElementOption[];
  default_quality: string;
  default_region: string;
  reference_basis_note: string;
}

/** Input for an instant estimate. */
export interface RomEstimateRequest {
  building_type: string;
  gross_floor_area: string | number;
  quality: string;
  region: string;
  gfa_unit?: string;
  currency?: string;
  name?: string;
  /**
   * Optional base cost per m2 (in `currency`) that overrides the neutral
   * reference basis so the total is anchored to the estimator's real rate.
   * Sent as a Decimal string; omit or leave blank to keep the reference basis.
   */
  base_rate_per_m2_override?: string | number;
}

/** One elemental line of the breakdown. Money fields are Decimal strings. */
export interface RomElementBreakdown {
  key: string;
  label: string;
  cost_share_pct: string;
  rate_per_m2: string;
  amount: string;
}

/** Honest accuracy band around the point estimate. */
export interface RomAccuracyBand {
  estimate_class: string;
  estimate_class_label: string;
  low_pct: string;
  high_pct: string;
  low_amount: string;
  high_amount: string;
  localized: boolean;
  note: string;
}

/** A full conceptual estimate result. */
export interface RomEstimateResult {
  building_type: string;
  building_type_label: string;
  quality: string;
  quality_label: string;
  region: string;
  region_label: string;
  currency: string;
  gross_floor_area: string;
  gfa_unit: string;
  gfa_canonical_m2: string;
  quality_factor: string;
  regional_factor: string;
  cost_per_m2: string;
  subtotal_base: string;
  total: string;
  accuracy: RomAccuracyBand;
  elements: RomElementBreakdown[];
  notes: string;
}

/** Reconciliation status band. */
export type RomReconciliationStatus = 'no_baseline' | 'on_track' | 'over' | 'under';

/**
 * Read-side reconciliation of the project's conceptual baseline against its live
 * detailed BOQ total. Money and percentage fields are Decimal strings (or null
 * when there is no usable baseline); render them verbatim, never float-mathed.
 */
export interface RomReconciliation {
  project_id: string;
  status: RomReconciliationStatus;
  /** Most-recent saved conceptual total, or null when none is stored. */
  conceptual_total: string | null;
  /** Sum of the project's BOQ grand totals in the base currency ("0" with no BOQ). */
  detailed_total: string;
  /** detailed_total - conceptual_total, or null with no baseline. */
  variance_amount: string | null;
  /** Variance as a signed percent of the conceptual total, or null. */
  variance_pct: string | null;
  /** On-track tolerance band (absolute percent) used for the status. */
  tolerance_pct: string;
  /** Currency the reconciliation is expressed in (BOQ base currency). */
  currency: string;
  /** Currency label stored on the conceptual estimate. */
  conceptual_currency: string;
  /** True when the two currencies differ, so the comparison mixes currencies. */
  currency_mismatch: boolean;
  /** Number of BOQs summed into the detailed total. */
  boq_count: number;
  conceptual_estimate_id: string | null;
  conceptual_name: string;
  conceptual_created_at: string | null;
}

/**
 * A conceptual (ROM) estimate persisted against a project. Every monetary /
 * ratio field is a Decimal-encoded STRING - render via the money helpers, never
 * `parseFloat` for display.
 */
export interface RomEstimateRecord {
  id: string;
  project_id: string;
  name: string;
  building_type: string;
  building_type_label: string;
  quality: string;
  region: string;
  currency: string;
  gross_floor_area: string;
  gfa_unit: string;
  cost_per_m2: string;
  total: string;
  estimate_class: string;
  accuracy_low_pct: string;
  accuracy_high_pct: string;
  accuracy_low_amount: string;
  accuracy_high_amount: string;
  elements: RomElementBreakdown[];
  created_at: string | null;
  created_by: string | null;
}

/**
 * Input to save a ROM estimate as the project baseline and seed a BOQ from it.
 * Carries every estimate field (so the concept can be saved and priced) plus
 * the name for the created bill of quantities.
 */
export interface RomCreateBoqRequest extends RomEstimateRequest {
  boq_name?: string;
}

/** Result of seeding a provisional BOQ from a conceptual (ROM) estimate. */
export interface RomCreateBoqResponse {
  boq_id: string;
  estimate_id?: string;
  sections_created: number;
  positions_created: number;
}

export const romEstimateApi = {
  /** Reference table for the form (building types, quality levels, regions, elements). */
  reference: () => apiGet<RomReference>('/v1/rom-estimate/reference/'),
  /** Produce an instant order-of-magnitude estimate (stateless, no persistence). */
  generate: (body: RomEstimateRequest) =>
    apiPost<RomEstimateResult, RomEstimateRequest>('/v1/rom-estimate/generate/', body),
  /** Reconcile the project's saved conceptual baseline against its live detailed BOQ total. */
  reconciliation: (projectId: string) =>
    apiGet<RomReconciliation>(
      `/v1/rom-estimate/projects/${encodeURIComponent(projectId)}/reconciliation/`,
    ),
  /** Compute and SAVE a conceptual estimate as the project baseline. */
  create: (projectId: string, body: RomEstimateRequest) =>
    apiPost<RomEstimateRecord, RomEstimateRequest>(
      `/v1/rom-estimate/projects/${encodeURIComponent(projectId)}/estimates/`,
      body,
    ),
  /** List a project's saved conceptual estimates (newest first). */
  list: (projectId: string) =>
    apiGet<RomEstimateRecord[]>(
      `/v1/rom-estimate/projects/${encodeURIComponent(projectId)}/estimates/`,
    ),
  /** Delete a saved conceptual estimate. */
  delete: (projectId: string, estimateId: string) =>
    apiDelete<void>(
      `/v1/rom-estimate/projects/${encodeURIComponent(projectId)}/estimates/${encodeURIComponent(estimateId)}`,
    ),
  /** Save the estimate as the baseline and seed a provisional BOQ from it. */
  createBoq: (projectId: string, body: RomCreateBoqRequest) =>
    apiPost<RomCreateBoqResponse, RomCreateBoqRequest>(
      `/v1/rom-estimate/projects/${encodeURIComponent(projectId)}/estimates/create-boq/`,
      body,
    ),
};
