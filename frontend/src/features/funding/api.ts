// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for Public Funding.
//
// Backend module: backend/app/modules/funding/router.py, mounted at
// /api/v1/funding/.
//
//   GET    /v1/funding/programmes/?country=&status=&search=
//   POST   /v1/funding/programmes/
//   GET    /v1/funding/applications/?project_id=
//   POST   /v1/funding/applications/
//   GET    /v1/funding/applications/{id}?today=&locale=
//   PATCH  /v1/funding/applications/{id}
//   POST   /v1/funding/applications/{id}/award
//   GET    /v1/funding/obligations/?project_id=&today=
//   GET    /v1/funding/projects/{id}/summary?today=
//
// Money arrives as plain-decimal STRINGS, not numbers. The backend
// serialises Decimal that way on purpose, because a grant of 1 234 567.89
// loses its last cent the moment JavaScript parses it as a float and an
// auditor reads that cent. Everything here keeps the string and only
// converts at the point of display or arithmetic, where `toMoney` below is
// the single place it happens.

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import { fmtPercent } from '@/shared/lib/formatters';

const BASE = '/v1/funding';

/** How a funding body is positioned relative to the applicant. */
export type AuthorityLevel = 'supranational' | 'national' | 'regional' | 'municipal';

/** What the programme actually hands over. */
export type Instrument = 'grant' | 'loan' | 'repayment_grant' | 'guarantee' | 'tax_relief' | 'equity';

export type ProgrammeStatus = 'draft' | 'open' | 'closed' | 'suspended';

export type ApplicationStatus =
  | 'draft'
  | 'submitted'
  | 'in_review'
  | 'approved'
  | 'rejected'
  | 'withdrawn'
  | 'closed';

export type DisbursementStatus = 'draft' | 'submitted' | 'approved' | 'paid' | 'rejected';

export type ProofKind = 'interim' | 'final';

export type ProofStatus = 'pending' | 'drafting' | 'submitted' | 'accepted' | 'rejected';

export type ObligationKind =
  | 'application_deadline'
  | 'measure_start'
  | 'disbursement'
  | 'spend_window'
  | 'interim_report'
  | 'final_report'
  | 'retention_end'
  | 'condition';

export type ObligationSource = 'programme_rule' | 'award_notice' | 'manual';

export type ObligationStatus = 'open' | 'done' | 'waived';

export type Eligibility = 'eligible' | 'partially_eligible' | 'not_eligible' | 'undecided';

export interface FundingProgramme {
  id: string;
  code: string;
  name: string;
  summary: string;
  authority_name: string;
  authority_level: AuthorityLevel;
  country: string;
  region_code: string;
  instrument: Instrument;
  funding_rate_percent: string;
  min_amount: string;
  max_amount: string;
  currency: string;
  own_share_percent: string;
  aid_intensity_cap_percent: string;
  de_minimis: boolean;
  cumulative: boolean;
  requires_application_before_start: boolean;
  application_window_start: string;
  application_window_end: string;
  rolling: boolean;
  proof_of_use_due_days: number;
  disbursement_spend_days: number;
  retention_years: number;
  eligible_applicant_types: string[];
  eligible_cost_categories: string[];
  excluded_cost_categories: string[];
  status: ProgrammeStatus;
  source_url: string;
  last_verified_on: string;
  pack_id: string;
  notes: string;
}

export interface FundingApplication {
  id: string;
  project_id: string;
  programme_id: string;
  code: string;
  title: string;
  applicant_name: string;
  applicant_type: string;
  status: ApplicationStatus;
  eligible_cost_base: string;
  requested_amount: string;
  own_share_amount: string;
  currency: string;
  submitted_on: string;
  decision_expected_on: string;
  decided_on: string;
  award_reference: string;
  approved_amount: string;
  award_period_start: string;
  award_period_end: string;
  conditions: string;
  rejection_reason: string;
  measure_start_on: string;
  early_start_approved: boolean;
  early_start_reference: string;
}

export interface FundingDisbursement {
  id: string;
  application_id: string;
  sequence: number;
  code: string;
  period_from: string;
  period_to: string;
  requested_on: string;
  approved_on: string;
  received_on: string;
  spend_deadline_on: string;
  amount_requested: string;
  amount_approved: string;
  amount_received: string;
  status: DisbursementStatus;
  invoice_ids: string[];
  notes: string;
}

export interface FundingProofOfUse {
  id: string;
  application_id: string;
  kind: ProofKind;
  due_on: string;
  submitted_on: string;
  accepted_on: string;
  status: ProofStatus;
  narrative_report: string;
  total_eligible_spent: string;
  total_funding_used: string;
  total_own_share: string;
  voucher_count: number;
  findings: string;
  retention_until: string;
}

export interface FundingObligation {
  id: string;
  application_id: string;
  kind: ObligationKind;
  /**
   * The server's own English. Read `title_key` instead, except when it is
   * empty, which is the server saying these are somebody's own words.
   */
  title: string;
  /** The server's own English again. Read `detail_key` and `detail_params`. */
  detail: string;
  /**
   * The message key for `title`, or empty when the title is not translatable
   * because a person typed it.
   */
  title_key: string;
  /**
   * The message key for `detail`, or empty on an obligation somebody typed.
   *
   * Stored on the row rather than derived from `kind`, because one kind
   * tells two different sentences: a retention deadline counted from the end
   * of the award period reads differently from the same deadline recounted
   * from the day the proof of use was accepted.
   */
  detail_key: string;
  /** The values `detail_key` interpolates, ready to hand to `t`. */
  detail_params: Record<string, string | number>;
  due_on: string;
  source: ObligationSource;
  source_reference: string;
  responsible_user_id: string | null;
  status: ObligationStatus;
  completed_on: string;
  /** Worked out by the server against the date the client sent. */
  overdue: boolean;
}

export interface FundingCostAllocation {
  id: string;
  application_id: string;
  cost_group: string;
  description: string;
  amount: string;
  eligible_amount: string;
  eligibility: Eligibility;
  reason: string;
  source_kind: string;
  source_ref_id: string | null;
}

export interface ApplicationSummary {
  application_id: string;
  currency: string;
  approved_amount: string;
  requested_amount: string;
  drawn_amount: string;
  received_amount: string;
  outstanding_amount: string;
  eligible_cost_base: string;
  allocated_amount: string;
  allocated_eligible_amount: string;
  own_share_required: string;
  own_share_recorded: string;
  effective_funding_rate_percent: string;
  obligations_open: number;
  obligations_overdue: number;
  next_due_on: string;
  /** The server's English title of the next deadline. */
  next_due_title: string;
  /** The kind behind it, which is what a screen should name it from. */
  next_due_kind: ObligationKind | '';
  /**
   * The message key for `next_due_title`, or empty when the next deadline is
   * somebody's own note - and then `next_due_title` is their words and is the
   * right thing to show. Decided by who wrote the title, which `next_due_kind`
   * cannot tell you: a typed condition and a derived report deadline can both
   * carry any kind.
   */
  next_due_title_key: string;
  /**
   * What the title names that the key does not interpolate: the sequence
   * number of the draw a spend window belongs to. Render the key, then attach
   * these the way the screen attaches a reference.
   */
  next_due_title_params: Record<string, string | number>;
}

export interface ProjectFundingSummary {
  project_id: string;
  currency: string;
  application_count: number;
  approved_count: number;
  approved_amount: string;
  received_amount: string;
  outstanding_amount: string;
  eligible_cost_base: string;
  aid_intensity_percent: string;
  aid_intensity_cap_percent: string;
  obligations_open: number;
  obligations_overdue: number;
}

export interface ValidationFinding {
  rule_id: string;
  rule_name: string;
  severity: 'error' | 'warning' | 'info';
  category: string;
  passed: boolean;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface ApplicationDetail {
  application: FundingApplication;
  programme: FundingProgramme | null;
  disbursements: FundingDisbursement[];
  proofs_of_use: FundingProofOfUse[];
  obligations: FundingObligation[];
  cost_allocations: FundingCostAllocation[];
  summary: ApplicationSummary;
  findings: ValidationFinding[];
}

export interface ProgrammeListResponse {
  items: FundingProgramme[];
  total: number;
  offset: number;
  limit: number;
}

export interface ApplicationListResponse {
  items: FundingApplication[];
  total: number;
}

export interface ObligationCalendarResponse {
  items: FundingObligation[];
  total: number;
  overdue: number;
}

/**
 * A money string as a number, for arithmetic and charts only.
 *
 * Never use the result to render an amount back to the user: it has already
 * lost whatever the string held beyond a double's precision. Render the
 * string, compute with this.
 */
export function toMoney(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === '') return 0;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

/**
 * A percentage as it should be read, from the decimal string the API sends.
 *
 * The column holds three decimal places, so a rate of twenty arrives as
 * "20.000". Printed as it stands that is a number a German or Spanish reader
 * parses as twenty thousand, because their thousands separator is the dot,
 * and "up to 20.000% of eligible cost" is then a promise no programme makes.
 * The trailing zeros are removed as digits rather than through a float, so
 * 66.667 stays 66.667 and nothing is rounded on its way to the screen.
 */
export function percentLabel(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '';
  const text = String(value).trim();
  if (!/^-?\d+(\.\d+)?$/.test(text)) return '';
  if (!text.includes('.')) return text;
  return text.replace(/0+$/, '').replace(/\.$/, '');
}

/**
 * How many decimal places a percentage actually carries.
 *
 * The column holds three, and almost none of them mean anything: a rate of
 * twenty arrives as "20.000" and wants no decimals at all, while 66.667
 * wants all three. `percentLabel` already works this out by trimming digits,
 * and this reads the answer off it rather than deciding it a second time.
 */
export function percentDecimals(value: string | number | null | undefined): number {
  const label = percentLabel(value);
  const dot = label.indexOf('.');
  return dot < 0 ? 0 : label.length - dot - 1;
}

/**
 * A percentage written the way the reader's own language writes one.
 *
 * `percentLabel` says which digits are significant; `fmtPercent` writes them
 * in the reader's numbering system and puts the percent sign where their
 * language puts it, which is after the figure in English, before it in
 * Turkish and as U+066A in Arabic. Assembling the string here instead left a
 * funding page showing Western digits in the percentages next to the
 * Arabic-Indic ones `formatCurrency` produces for the amounts.
 *
 * Empty for a value that is not a number, exactly as `percentLabel` is, so a
 * caller can still tell a rate of nothing from no rate at all.
 */
export function percentText(value: string | number | null | undefined): string {
  const label = percentLabel(value);
  if (label === '') return '';
  return fmtPercent(Number(label), percentDecimals(value));
}

/**
 * Whether a percentage was set at all.
 *
 * Zero is the column default, so a programme that never declared a rate is
 * indistinguishable from one that declared none, and both should stay silent
 * rather than claim a ceiling of nothing.
 */
export function declaresPercent(value: string | number | null | undefined): boolean {
  const label = percentLabel(value);
  return label !== '' && Number(label) > 0;
}

/**
 * Whether an amount was set at all.
 *
 * The same trap as the percentages, one column over. Money arrives as a
 * decimal string, so an unset amount is "0.00", which is a non-empty string
 * and therefore truthy. `approved || requested` then chooses the zero and
 * offers the reader a receipt for nothing against a draw they asked six
 * figures for.
 */
export function declaresAmount(value: string | number | null | undefined): boolean {
  return toMoney(value) > 0;
}

/** Today as the calendar day the reader is living in, not UTC. */
export function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export const fundingKeys = {
  all: ['funding'] as const,
  programmes: (filters: Record<string, string | undefined>) => ['funding', 'programmes', filters] as const,
  applications: (projectId: string) => ['funding', 'applications', projectId] as const,
  application: (id: string) => ['funding', 'application', id] as const,
  // The application detail carries validation findings the server writes in
  // the requested language, so the cached copy is per language. It extends
  // application(id) rather than replacing it, which keeps every invalidation
  // written against application(id) reaching all of its languages.
  applicationIn: (id: string, locale: string) => ['funding', 'application', id, locale] as const,
  obligations: (projectId: string) => ['funding', 'obligations', projectId] as const,
  projectSummary: (projectId: string) => ['funding', 'project-summary', projectId] as const,
};

/* ── Programmes ──────────────────────────────────────────────────────── */

export async function listProgrammes(params: {
  country?: string;
  status?: string;
  authority_level?: string;
  instrument?: string;
  search?: string;
  offset?: number;
  limit?: number;
}): Promise<ProgrammeListResponse> {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '' && value !== null) query.set(key, String(value));
  });
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return apiGet<ProgrammeListResponse>(`${BASE}/programmes/${suffix}`);
}

export async function createProgramme(payload: Partial<FundingProgramme>): Promise<FundingProgramme> {
  return apiPost<FundingProgramme>(`${BASE}/programmes/`, payload);
}

export async function updateProgramme(
  id: string,
  payload: Partial<FundingProgramme>,
): Promise<FundingProgramme> {
  return apiPatch<FundingProgramme>(`${BASE}/programmes/${id}`, payload);
}

export async function deleteProgramme(id: string): Promise<void> {
  await apiDelete(`${BASE}/programmes/${id}`);
}

/* ── Applications ────────────────────────────────────────────────────── */

export async function listApplications(
  projectId: string,
  status?: string,
): Promise<ApplicationListResponse> {
  const query = new URLSearchParams({ project_id: projectId });
  if (status) query.set('status', status);
  return apiGet<ApplicationListResponse>(`${BASE}/applications/?${query.toString()}`);
}

export async function getApplication(
  id: string,
  opts: { today?: string; locale?: string } = {},
): Promise<ApplicationDetail> {
  const query = new URLSearchParams();
  query.set('today', opts.today ?? localToday());
  if (opts.locale) query.set('locale', opts.locale);
  return apiGet<ApplicationDetail>(`${BASE}/applications/${id}?${query.toString()}`);
}

export async function createApplication(payload: {
  project_id: string;
  programme_id: string;
  code: string;
  title?: string;
  applicant_name?: string;
  eligible_cost_base?: string;
  requested_amount?: string;
  own_share_amount?: string;
  submitted_on?: string;
  measure_start_on?: string;
}): Promise<FundingApplication> {
  return apiPost<FundingApplication>(`${BASE}/applications/`, payload);
}

export async function updateApplication(
  id: string,
  payload: Partial<FundingApplication>,
): Promise<FundingApplication> {
  return apiPatch<FundingApplication>(`${BASE}/applications/${id}`, payload);
}

export async function deleteApplication(id: string): Promise<void> {
  await apiDelete(`${BASE}/applications/${id}`);
}

export async function recordAward(
  id: string,
  payload: {
    approved: boolean;
    decided_on?: string;
    award_reference?: string;
    approved_amount?: string;
    award_period_start?: string;
    award_period_end?: string;
    conditions?: string;
    rejection_reason?: string;
  },
): Promise<FundingApplication> {
  return apiPost<FundingApplication>(`${BASE}/applications/${id}/award`, payload);
}

/* ── Draws, reports, deadlines, eligible cost ────────────────────────── */

export async function createDisbursement(
  applicationId: string,
  payload: {
    code?: string;
    period_from?: string;
    period_to?: string;
    requested_on?: string;
    amount_requested?: string;
    notes?: string;
  },
): Promise<FundingDisbursement> {
  return apiPost<FundingDisbursement>(`${BASE}/applications/${applicationId}/disbursements/`, payload);
}

export async function confirmReceipt(
  disbursementId: string,
  payload: { received_on: string; amount_received?: string },
): Promise<FundingDisbursement> {
  return apiPost<FundingDisbursement>(`${BASE}/disbursements/${disbursementId}/receipt`, payload);
}

export async function createProofOfUse(
  applicationId: string,
  payload: { kind: ProofKind; due_on?: string; narrative_report?: string },
): Promise<FundingProofOfUse> {
  return apiPost<FundingProofOfUse>(`${BASE}/applications/${applicationId}/proofs/`, payload);
}

export async function acceptProofOfUse(proofId: string, acceptedOn: string): Promise<FundingProofOfUse> {
  const query = new URLSearchParams({ accepted_on: acceptedOn });
  return apiPost<FundingProofOfUse>(`${BASE}/proofs/${proofId}/accept?${query.toString()}`, {});
}

export async function createObligation(
  applicationId: string,
  payload: { kind: ObligationKind; title: string; detail?: string; due_on?: string },
): Promise<FundingObligation> {
  return apiPost<FundingObligation>(`${BASE}/applications/${applicationId}/obligations/`, payload);
}

export async function updateObligation(
  id: string,
  payload: { status?: ObligationStatus; completed_on?: string; due_on?: string; title?: string },
): Promise<FundingObligation> {
  return apiPatch<FundingObligation>(`${BASE}/obligations/${id}`, payload);
}

export async function listProjectObligations(
  projectId: string,
  opts: { today?: string; openOnly?: boolean } = {},
): Promise<ObligationCalendarResponse> {
  const query = new URLSearchParams({ project_id: projectId });
  query.set('today', opts.today ?? localToday());
  query.set('open_only', String(opts.openOnly ?? true));
  return apiGet<ObligationCalendarResponse>(`${BASE}/obligations/?${query.toString()}`);
}

export async function createCostAllocation(
  applicationId: string,
  payload: {
    cost_group: string;
    description?: string;
    amount: string;
    eligible_amount: string;
    eligibility: Eligibility;
    reason?: string;
  },
): Promise<FundingCostAllocation> {
  return apiPost<FundingCostAllocation>(`${BASE}/applications/${applicationId}/allocations/`, payload);
}

export async function getProjectSummary(
  projectId: string,
  today?: string,
): Promise<ProjectFundingSummary> {
  const query = new URLSearchParams({ today: today ?? localToday() });
  return apiGet<ProjectFundingSummary>(`${BASE}/projects/${projectId}/summary?${query.toString()}`);
}
