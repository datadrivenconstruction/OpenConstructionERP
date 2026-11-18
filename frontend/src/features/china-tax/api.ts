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
