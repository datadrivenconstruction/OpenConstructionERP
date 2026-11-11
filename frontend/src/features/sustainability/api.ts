// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet, apiPost, apiPut } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────── */

export interface CO2Breakdown {
  material: string;
  category: string;
  quantity: number;
  unit: string;
  co2_kg: number;
  percentage: number;
  positions_count: number;
}

export interface PositionCO2Detail {
  position_id: string;
  ordinal: string;
  description: string;
  quantity: number;
  unit: string;
  epd_id: string | null;
  epd_name: string | null;
  gwp_per_unit: number;
  gwp_total: number;
  category: string;
  source: string;
}

export interface SustainabilityData {
  total_co2_kg: number;
  total_co2_tons: number;
  breakdown: CO2Breakdown[];
  benchmark_per_m2: number | null;
  rating: string;
  rating_label: string;
  project_area_m2: number | null;
  positions_analyzed: number;
  positions_matched: number;
  lifecycle_stages: string;
  data_quality: string;
  positions_detail: PositionCO2Detail[];
  eu_cpr_compliance: string;
  eu_cpr_gwp_per_m2_year: number | null;
}

export interface EPDMaterial {
  id: string;
  name: string;
  category: string;
  gwp: number;
  unit: string;
  density?: number;
  source: string;
  stages: string;
  own?: boolean;
}

export interface EPDMaterialsResponse {
  materials: EPDMaterial[];
  categories: { id: string; label: string }[];
  total: number;
}

export interface CO2EnrichResponse {
  enriched: number;
  skipped: number;
  total: number;
}

/* ── API calls ─────────────────────────────────────────────────────── */

export function fetchSustainability(boqId: string, areaM2: number) {
  return apiGet<SustainabilityData>(
    `/v1/boq/boqs/${boqId}/sustainability/?area_m2=${areaM2}`,
  );
}

export function enrichCO2(boqId: string) {
  return apiPost<CO2EnrichResponse>(`/v1/boq/boqs/${boqId}/enrich-co2/`, {});
}

export function assignPositionCO2(positionId: string, epdId: string) {
  return apiPut<{ status: string; co2: Record<string, unknown> }>(
    `/v1/boq/positions/${positionId}/co2/`,
    { epd_id: epdId },
  );
}

export function fetchEPDMaterials(category?: string, search?: string) {
  const params = new URLSearchParams();
  if (category) params.set('category', category);
  if (search) params.set('search', search);
  const qs = params.toString();
  return apiGet<EPDMaterialsResponse>(`/v1/boq/epd-materials/${qs ? `?${qs}` : ''}`);
}

export interface OwnMaterialInput {
  name: string;
  category: string;
  unit: string;
  /** kg CO2e per declared unit (A1-A3), kept as a decimal string. */
  gwp: string;
}

/** Saves a user material as a custom EPD record in the carbon module's EPD library. */
export function createOwnMaterial(input: OwnMaterialInput) {
  const slug = input.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);
  const suffix = Math.random().toString(36).slice(2, 8);
  return apiPost<{ id: string; epd_id: string }>('/v1/carbon/epd', {
    epd_id: `own-${slug || 'material'}-${suffix}`,
    source: 'custom',
    material_class: input.category,
    product_name: input.name,
    declared_unit: input.unit,
    gwp_a1a3: input.gwp,
  });
}

/** Strict decimal check for the GWP field (negative allowed for biogenic credits). */
export function isDecimalString(v: string): boolean {
  return /^-?\d+(\.\d+)?$/.test(v.trim());
}
