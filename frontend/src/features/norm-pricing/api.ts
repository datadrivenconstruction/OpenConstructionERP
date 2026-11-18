// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Norm pricing: what the project's country pack offers (norm base, grade table,
// funding classes, labour location factors) and what the project chose.
// Money and coefficients arrive as decimal strings and stay strings.

import { API_BASE, apiGet, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export type EstimateRole = 'investor' | 'contractor';

export interface EstimatePricingSettings {
  estimate_wage?: string | null;
  monthly_hours?: string | null;
  funding_class?: string | null;
  estimate_role?: EstimateRole | null;
  labour_location?: string | null;
}

export interface FundingClassOption {
  key: string;
  label: string;
  source: string;
  markup_caps: { key: string; label: string; cap_percent: string }[];
  investor_estimate_at_cap: boolean;
  min_quotes: number | null;
}

export interface LocationOption {
  key: string;
  label: string;
  source: string;
  factor: string | null;
}

export interface NormBaseInfo {
  key: string;
  name: string;
  classification_key: string;
  code_example: string;
  types: { prefix: string; title: string | null; collections: number | null }[];
  legacy_prefixes: Record<string, string>;
  grade_field: string;
}

export interface PricingProfile {
  available: boolean;
  pack_slug: string | null;
  currency: string | null;
  norm_bases: NormBaseInfo[];
  funding_classes: FundingClassOption[];
  location_factors: LocationOption[];
  grades: string[];
  base_grade: string | null;
  grading_status: string | null;
  grading_source: string | null;
  has_export_layout: boolean;
  default_monthly_hours: string | null;
  settings: EstimatePricingSettings;
}

export interface LabourRate {
  grade: string;
  base_grade: string;
  base_rate: string;
  grade_one_rate: string;
  base_coefficient: string;
  coefficient: string;
  rate: string;
  location_factor: string;
  rate_with_location: string;
}

export interface LabourRates {
  estimate_wage: string;
  monthly_hours: string;
  rates: LabourRate[];
  missing_grades: string[];
}

export interface WritebackRow {
  position_id: string;
  ordinal: string;
  description: string;
  resource_index: number;
  resource_name: string;
  grade: string;
  current_rate: string | null;
  proposed_rate: string;
  derivation: LabourRate;
}

export interface WritebackSkip {
  position_id: string;
  ordinal: string;
  resource_index: number;
  resource_name: string;
  reason: 'no_grade' | 'grade_off_scale';
  grade: string | null;
}

export interface WritebackPreview {
  boq_id: string;
  estimate_wage: string;
  monthly_hours: string;
  location_factor: string;
  changes: WritebackRow[];
  unchanged: number;
  skipped: WritebackSkip[];
}

export interface WritebackItem {
  position_id: string;
  resource_index: number;
  rate: string;
}

const BASE = '/v1/norm_pricing';
const q = (projectId: string, boqId: string) =>
  `project_id=${encodeURIComponent(projectId)}&boq_id=${encodeURIComponent(boqId)}`;

export const normPricingApi = {
  profile: (projectId: string, locale?: string) =>
    apiGet<PricingProfile>(
      `${BASE}/profile?project_id=${encodeURIComponent(projectId)}${locale ? `&locale=${encodeURIComponent(locale)}` : ''}`,
    ),
  saveSettings: (projectId: string, body: EstimatePricingSettings, locale?: string) =>
    apiPut<PricingProfile, EstimatePricingSettings>(
      `${BASE}/settings?project_id=${encodeURIComponent(projectId)}${locale ? `&locale=${encodeURIComponent(locale)}` : ''}`,
      body,
    ),
  labourRates: (projectId: string, grades: string[]) =>
    apiGet<LabourRates>(
      `${BASE}/labour-rates?project_id=${encodeURIComponent(projectId)}&grades=${encodeURIComponent(grades.join(','))}`,
    ),
  writebackPreview: (projectId: string, boqId: string) =>
    apiGet<WritebackPreview>(`${BASE}/labour-writeback?${q(projectId, boqId)}`),
  writebackApply: (projectId: string, boqId: string, items: WritebackItem[]) =>
    apiPost<{ updated_positions: number; updated_resources: number }, { items: WritebackItem[] }>(
      `${BASE}/labour-writeback?${q(projectId, boqId)}`,
      { items },
    ),
  exportSheet: (projectId: string, boqId: string, locale?: string) =>
    downloadWithAuth(
      `${API_BASE}${BASE}/export/xlsx?${q(projectId, boqId)}${locale ? `&locale=${encodeURIComponent(locale)}` : ''}`,
      'estimate.xlsx',
    ),
};

/** Grades worth a row in the rate table: whole grades plus the base grade, as the pack ships them. */
export function displayGrades(profile: Pick<PricingProfile, 'grades' | 'base_grade'>): string[] {
  const picked = profile.grades.filter((g) => g.endsWith('.0') || g === profile.base_grade);
  return picked.length > 0 ? picked : profile.grades.slice(0, 8);
}

/** The derivation a cost engineer checks, e.g. "V3.8 = 30000 / 174 = 172.41". */
export function rateDerivation(r: LabourRate, rates: Pick<LabourRates, 'estimate_wage' | 'monthly_hours'>): string {
  const base = `V${r.base_grade} = ${rates.estimate_wage} / ${rates.monthly_hours} = ${r.base_rate}`;
  if (r.grade === r.base_grade) return base;
  const one = `V1 = ${r.base_rate} / ${r.base_coefficient} = ${r.grade_one_rate}`;
  return `${base}; ${one}; V${r.grade} = ${r.grade_one_rate} × ${r.coefficient} = ${r.rate}`;
}

export { averageLabourGrade } from './grade';
