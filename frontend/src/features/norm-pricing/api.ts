// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Norm pricing: what the project's country pack offers (norm base, grade table,
// funding classes, labour location factors) and what the project chose.
// Money and coefficients arrive as decimal strings and stay strings.

import { apiGet, apiPut } from '@/shared/lib/api';

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

const BASE = '/v1/norm_pricing';

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
