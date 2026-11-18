// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * China tax API: the project tax profile (neutral `project_tax` module) and
 * the China pack's tender summary, cn_vat check, 预缴 schedule and 数电票 data.
 */

import { apiGet, apiPost, apiPut } from '@/shared/lib/api';

const PROFILE = '/v1/project-tax';
const PACK = '/v1/china-pack';

export type TaxMethod = 'general' | 'simplified' | 'exempt';
export type TaxpayerSize = 'general' | 'small';
export type SimplifiedBasis = 'labour_only' | 'old_project' | 'employer_supplied';

export interface EditionOption {
  key: string;
  label: string;
  in_force_from: string | null;
}

export interface ProfileFields {
  tax_method: TaxMethod;
  election_date: string | null;
  lock_months: number | null;
  grandfathered: boolean;
  simplified_basis: string | null;
  employer_supplied: boolean;
  taxpayer_size: TaxpayerSize;
  permit_start_date: string | null;
  contract_date: string | null;
  tender_date: string | null;
  standard_edition: string | null;
  site_subdivision: string | null;
  site_city: string | null;
  home_subdivision: string | null;
  home_city: string | null;
  notes: string;
}

export interface TaxProfile extends ProfileFields {
  project_id: string;
  stored: boolean;
  edition_source: 'stored' | 'derived' | 'none';
  cross_region: boolean | null;
  lock_ends_on: string | null;
  method_history: Array<{ method: string; election_date: string | null; changed_on: string }>;
  editions: EditionOption[];
}

export interface Finding {
  rule_id: string;
  severity: string;
  message: string;
  element_ref?: string | null;
  details: Record<string, unknown>;
}

export interface SummaryHead {
  key: string;
  label_zh: string;
  amount: string;
}

export interface TenderSummary {
  edition: string;
  tax_method: string;
  heads: SummaryHead[];
  vat_base: string;
  vat: string;
  tax_inclusive_total: string;
  tender_total: string;
  employer_supplied_net: string;
  employer_supplied_tax: string;
  invoiceable_total: string;
}

export interface ProjectCheck {
  profile: Partial<TaxProfile>;
  summary: TenderSummary;
  lines: number;
  invoices: number;
  findings: Finding[];
}

export interface PrepaymentPeriodInput {
  period: string;
  receipts: string;
  subcontract_paid: string;
}

export interface PrepaymentRow {
  period: string;
  receipts: string;
  subcontract_paid: string;
  carried_in: string;
  base_net: string;
  prepaid: string;
  carried_out: string;
}

export interface PrepaymentResult {
  tax_rate_pct: string;
  prepay_rate_pct: string;
  verified: boolean;
  periods: PrepaymentRow[];
}

export function fetchProfile(projectId: string): Promise<TaxProfile> {
  return apiGet<TaxProfile>(`${PROFILE}/projects/${projectId}/profile/`);
}

export function saveProfile(
  projectId: string,
  body: ProfileFields,
): Promise<{ profile: TaxProfile; findings: Finding[] }> {
  return apiPut<{ profile: TaxProfile; findings: Finding[] }, ProfileFields>(
    `${PROFILE}/projects/${projectId}/profile/`,
    body,
  );
}

export function fetchProjectCheck(projectId: string): Promise<ProjectCheck> {
  return apiGet<ProjectCheck>(`${PACK}/projects/${projectId}/check/`);
}

export function computePrepayment(
  taxMethod: TaxMethod,
  periods: PrepaymentPeriodInput[],
): Promise<PrepaymentResult> {
  return apiPost<PrepaymentResult>(`${PACK}/prepayment/`, {
    tax_method: taxMethod === 'simplified' ? 'simplified' : 'general',
    periods,
  });
}

export interface FeeOption {
  key: string;
  values: string[];
  default?: string;
  labels_zh?: Record<string, string>;
}

export interface FeeLineMeta {
  name_zh: string | null;
  name_en: string | null;
  kind: string | null;
  band: { min?: string; mid?: string; max?: string } | null;
  non_competitive: boolean;
  user_input: boolean;
  needs_confirmation: boolean;
  reference_rates: Array<{ chapter_zh: string; chapter_en: string; rate: string }>;
  doc: string | null;
  url: string | null;
  secondary: boolean;
}

export interface FeeScheduleSummary {
  key: string;
  name_zh: string;
  name_en: string;
  effective_from: string | null;
  effective_to: string | null;
  superseded_by: string | null;
  labour_factor: string | null;
  bases_verified: boolean;
  doc: string | null;
  url: string | null;
  options: FeeOption[];
  lines: Record<string, FeeLineMeta>;
}

export interface FeeLineResult {
  code: string;
  group: string;
  base: string;
  rate: string | null;
  coefficient: string;
  amount: string;
  status: 'published' | 'user' | 'missing';
  published: string | null;
  floor: string | null;
}

export interface FeeSettings {
  schedule_key: string | null;
  rates: Record<string, string>;
  options: Record<string, string>;
  bases: Record<string, Record<string, string>>;
  labour_includes_social_insurance: boolean;
  apply_labour_factor: boolean | null;
}

export interface FeeBlock {
  jurisdiction: string;
  jurisdiction_name_zh: string;
  jurisdiction_name_en: string;
  date: string | null;
  guifei_abolished_from: string | null;
  price_station_url: string | null;
  price_publication: string | null;
  schedules: FeeScheduleSummary[];
  resolved_key: string | null;
  schedule: FeeScheduleSummary | null;
  in_force: boolean | null;
  successor: string | null;
  settings: Partial<FeeSettings>;
  result: {
    schedule_key: string;
    labour: string;
    labour_factor_applied: boolean;
    direct: string;
    lines: FeeLineResult[];
    pre_tax: string;
    vat_rate: string;
    vat: string;
    total: string;
    options: Record<string, string>;
  } | null;
}

export interface ProjectFees {
  fee: FeeBlock | null;
  findings: Finding[];
}

export interface EditionMovePreview {
  from: string | null;
  to: string;
  needed: boolean;
  guifei_lines: string[];
  guifei_markups: string[];
  codes_to_review: Array<{ ref: string; code: string }>;
  codes_to_review_count: number;
  fee_schedule_from: string | null;
  fee_schedule_to: string | null;
  applied?: { standard_edition: string; markups_switched_off: string[] };
}

export function fetchProjectFees(projectId: string): Promise<ProjectFees> {
  return apiGet<ProjectFees>(`${PACK}/projects/${projectId}/fees/`);
}

export function saveProjectFees(projectId: string, body: FeeSettings): Promise<ProjectFees> {
  return apiPut<ProjectFees, FeeSettings>(`${PACK}/projects/${projectId}/fees/`, body);
}

export function fetchEditionMove(projectId: string): Promise<EditionMovePreview> {
  return apiGet<EditionMovePreview>(`${PACK}/projects/${projectId}/edition-move/`);
}

export function applyEditionMove(projectId: string): Promise<EditionMovePreview> {
  return apiPost<EditionMovePreview>(`${PACK}/projects/${projectId}/edition-move/`, {});
}

/** Settings a PUT sends: blank rates dropped, everything else as stated. */
export function toFeeSettings(s: Partial<FeeSettings>): FeeSettings {
  const rates = Object.fromEntries(
    Object.entries(s.rates ?? {})
      .map(([k, v]) => [k, String(v ?? '').trim()] as const)
      .filter(([, v]) => v !== ''),
  );
  return {
    schedule_key: s.schedule_key || null,
    rates,
    options: { ...(s.options ?? {}) },
    bases: { ...(s.bases ?? {}) },
    labour_includes_social_insurance: !!s.labour_includes_social_insurance,
    apply_labour_factor: s.apply_labour_factor ?? null,
  };
}

/** The fields a PUT sends, read off a profile; blank strings become null. */
export function toProfileFields(p: ProfileFields): ProfileFields {
  const blank = (v: string | null | undefined) => (v == null || v.trim() === '' ? null : v.trim());
  return {
    tax_method: p.tax_method,
    election_date: blank(p.election_date),
    lock_months: p.lock_months == null || Number.isNaN(p.lock_months) ? null : p.lock_months,
    grandfathered: p.grandfathered,
    simplified_basis: p.tax_method === 'simplified' ? blank(p.simplified_basis) : null,
    employer_supplied: p.employer_supplied,
    taxpayer_size: p.taxpayer_size,
    permit_start_date: blank(p.permit_start_date),
    contract_date: blank(p.contract_date),
    tender_date: blank(p.tender_date),
    standard_edition: blank(p.standard_edition),
    site_subdivision: blank(p.site_subdivision)?.toUpperCase() ?? null,
    site_city: blank(p.site_city),
    home_subdivision: blank(p.home_subdivision)?.toUpperCase() ?? null,
    home_city: blank(p.home_city),
    notes: p.notes ?? '',
  };
}

/** Message key of a finding: the rule id with dots made safe for i18next. */
export function findingKey(ruleId: string): string {
  return `china_tax.rule.${ruleId.replace(/\./g, '_')}`;
}
