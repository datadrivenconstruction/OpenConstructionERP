// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Certified Payroll.
 *
 * All endpoints are prefixed with /v1/certified_payroll/ and are manager-scoped.
 * Money and hours are Decimal-as-string; the UI parses with Number(...) only
 * for display, never for arithmetic that lands back on the server.
 *
 * Basic wage and fringe are separate fields in every shape here, on the
 * required side and the paid side alike. There is deliberately no combined
 * rate: the overtime multiplier applies to the basic wage alone, and a type
 * that can hold one blended number invites code that multiplies it.
 */

import { apiDelete, apiGet, apiPatch, apiPost, getAuthToken } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** Who issued a wage determination. Three values: an awarding body sets its
 *  own rate where no state schedule exists, which a federal/state pair cannot
 *  express. */
export type DeterminationAuthority = 'federal' | 'state' | 'awarding_body';

export type DeterminationMethod =
  | 'published_schedule'
  | 'local_wage_survey'
  | 'federal_locality_determination';

/** How the fringe was discharged: into a benefit plan, in cash, or split. */
export type FringeElection = 'plan' | 'cash' | 'mixed';

export type WeekStatus = 'draft' | 'certified';

export interface WageClassification {
  id: string;
  determination_id: string;
  code: string;
  title: string;
  /** The overtime base. Never add this to fringe_rate and store the result. */
  basic_hourly_rate: string;
  fringe_rate: string;
  note: string;
  ordinal: number;
  created_at: string;
  updated_at: string;
}

export interface WageDetermination {
  id: string;
  project_id: string;
  authority: DeterminationAuthority;
  authority_name: string;
  jurisdiction: string;
  locality: string;
  identifier: string;
  title: string;
  determination_method: DeterminationMethod | null;
  decision_date: string | null;
  effective_date: string | null;
  expires_on: string | null;
  statute_reference: string;
  source_note: string;
  currency: string;
  /** True once a certified payroll cites it. Locked determinations are read-only. */
  locked: boolean;
  metadata: Record<string, unknown>;
  classifications: WageClassification[];
  created_at: string;
  updated_at: string;
}

export interface ClassificationAssignment {
  id: string;
  project_id: string;
  resource_id: string | null;
  worker_name: string;
  worker_identifier: string;
  classification_id: string;
  valid_from: string | null;
  valid_to: string | null;
  /** Null means nobody stated the split, so the server derives one and says so. */
  paid_basic_rate: string | null;
  paid_fringe_rate: string | null;
  fringe_election: FringeElection | null;
  note: string;
  created_at: string;
  updated_at: string;
}

export interface CertifiedLine {
  id: string | null;
  week_id: string | null;
  resource_id: string | null;
  worker_name: string;
  worker_identifier: string;
  classification_id: string | null;
  classification_code: string;
  classification_title: string;
  determination_id: string | null;
  determination_identifier: string;
  determination_authority: string;
  /** ISO date -> { straight, overtime }, both Decimal-as-string. */
  hours_by_day: Record<string, { straight?: string; overtime?: string }>;
  straight_hours: string;
  overtime_hours: string;
  required_basic_rate: string;
  required_fringe_rate: string;
  paid_basic_rate: string;
  paid_fringe_rate: string;
  fringe_election: string;
  overtime_multiplier: string;
  /** What the multiplier was applied to. Should equal paid_basic_rate. */
  overtime_base_rate: string;
  gross_amount: string;
  total_deductions: string;
  net_amount: string;
  deductions_detail: Array<{ label?: string; type?: string; amount?: string }>;
  currency: string;
  ordinal: number;
  note: string;
}

export interface CertifiedWeek {
  id: string;
  project_id: string;
  batch_id: string | null;
  week_ending: string;
  payroll_number: string;
  is_final: boolean;
  contractor_name: string;
  contractor_address: string;
  is_subcontractor: boolean;
  project_name: string;
  project_location: string;
  contract_number: string;
  covered_authorities: string[];
  governing_determination_id: string | null;
  governing_reason: string;
  fringe_election: FringeElection;
  fringe_exception_note: string;
  status: WeekStatus;
  signatory_name: string | null;
  signatory_title: string | null;
  signed_at: string | null;
  signed_by: string | null;
  statement_text: string;
  currency: string;
  notes: string;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CertifiedWeekDetail extends CertifiedWeek {
  lines: CertifiedLine[];
  /** True while the lines are computed live from payroll; false once frozen. */
  lines_are_derived: boolean;
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
  details: Record<string, unknown>;
}

export interface WeekValidation {
  week_id: string;
  status: 'passed' | 'warnings' | 'errors';
  error_count: number;
  warning_count: number;
  can_certify: boolean;
  findings: ValidationFinding[];
}

/* ── Wage determinations ───────────────────────────────────────────────── */

export interface ClassificationPayload {
  code: string;
  title: string;
  basic_hourly_rate: string;
  fringe_rate: string;
  note?: string;
  ordinal?: number;
}

export interface DeterminationPayload {
  authority: DeterminationAuthority;
  authority_name?: string;
  jurisdiction?: string;
  locality?: string;
  identifier: string;
  title?: string;
  determination_method?: DeterminationMethod | null;
  decision_date?: string | null;
  effective_date?: string | null;
  expires_on?: string | null;
  statute_reference?: string;
  source_note?: string;
  currency?: string;
  classifications?: ClassificationPayload[];
}

export async function listDeterminations(projectId: string): Promise<WageDetermination[]> {
  return apiGet<WageDetermination[]>(
    `/v1/certified_payroll/projects/${encodeURIComponent(projectId)}/determinations/`,
  );
}

export async function createDetermination(
  projectId: string,
  payload: DeterminationPayload,
): Promise<WageDetermination> {
  return apiPost<WageDetermination, DeterminationPayload>(
    `/v1/certified_payroll/projects/${encodeURIComponent(projectId)}/determinations/`,
    payload,
  );
}

export async function deleteDetermination(determinationId: string): Promise<void> {
  return apiDelete<void>(
    `/v1/certified_payroll/determinations/${encodeURIComponent(determinationId)}`,
  );
}

export async function addClassification(
  determinationId: string,
  payload: ClassificationPayload,
): Promise<WageClassification> {
  return apiPost<WageClassification, ClassificationPayload>(
    `/v1/certified_payroll/determinations/${encodeURIComponent(determinationId)}/classifications/`,
    payload,
  );
}

/* ── Worker classification ─────────────────────────────────────────────── */

export interface AssignmentPayload {
  resource_id?: string | null;
  worker_name: string;
  worker_identifier?: string;
  classification_id: string;
  valid_from?: string | null;
  valid_to?: string | null;
  paid_basic_rate?: string | null;
  paid_fringe_rate?: string | null;
  fringe_election?: FringeElection | null;
  note?: string;
}

export async function listAssignments(projectId: string): Promise<ClassificationAssignment[]> {
  return apiGet<ClassificationAssignment[]>(
    `/v1/certified_payroll/projects/${encodeURIComponent(projectId)}/assignments/`,
  );
}

export async function createAssignment(
  projectId: string,
  payload: AssignmentPayload,
): Promise<ClassificationAssignment> {
  return apiPost<ClassificationAssignment, AssignmentPayload>(
    `/v1/certified_payroll/projects/${encodeURIComponent(projectId)}/assignments/`,
    payload,
  );
}

export async function updateAssignment(
  assignmentId: string,
  payload: Partial<AssignmentPayload>,
): Promise<ClassificationAssignment> {
  return apiPatch<ClassificationAssignment, Partial<AssignmentPayload>>(
    `/v1/certified_payroll/assignments/${encodeURIComponent(assignmentId)}`,
    payload,
  );
}

export async function deleteAssignment(assignmentId: string): Promise<void> {
  return apiDelete<void>(`/v1/certified_payroll/assignments/${encodeURIComponent(assignmentId)}`);
}

/* ── Weeks ─────────────────────────────────────────────────────────────── */

export interface WeekPayload {
  week_ending: string;
  batch_id?: string | null;
  payroll_number?: string;
  is_final?: boolean;
  contractor_name?: string;
  contractor_address?: string;
  is_subcontractor?: boolean;
  project_name?: string;
  project_location?: string;
  contract_number?: string;
  covered_authorities?: DeterminationAuthority[];
  fringe_election?: FringeElection;
  fringe_exception_note?: string;
  daily_overtime_threshold?: string | null;
  weekly_overtime_threshold?: string | null;
  overtime_multiplier?: string;
  notes?: string;
}

export async function listWeeks(projectId: string): Promise<CertifiedWeek[]> {
  return apiGet<CertifiedWeek[]>(
    `/v1/certified_payroll/projects/${encodeURIComponent(projectId)}/weeks/`,
  );
}

export async function createWeek(
  projectId: string,
  payload: WeekPayload,
): Promise<CertifiedWeekDetail> {
  return apiPost<CertifiedWeekDetail, WeekPayload>(
    `/v1/certified_payroll/projects/${encodeURIComponent(projectId)}/weeks/`,
    payload,
  );
}

export async function getWeek(weekId: string): Promise<CertifiedWeekDetail> {
  return apiGet<CertifiedWeekDetail>(`/v1/certified_payroll/weeks/${encodeURIComponent(weekId)}`);
}

export async function updateWeek(
  weekId: string,
  payload: Partial<WeekPayload>,
): Promise<CertifiedWeekDetail> {
  return apiPatch<CertifiedWeekDetail, Partial<WeekPayload>>(
    `/v1/certified_payroll/weeks/${encodeURIComponent(weekId)}`,
    payload,
  );
}

export async function deleteWeek(weekId: string): Promise<void> {
  return apiDelete<void>(`/v1/certified_payroll/weeks/${encodeURIComponent(weekId)}`);
}

/** Run the compliance rules over a week without changing anything. */
export async function validateWeek(weekId: string): Promise<WeekValidation> {
  return apiGet<WeekValidation>(
    `/v1/certified_payroll/weeks/${encodeURIComponent(weekId)}/validate/`,
  );
}

export interface CertifyPayload {
  signatory_name: string;
  signatory_title: string;
  /** Blank renders the standard four assertions from the week's own facts. */
  statement_text?: string;
  fringe_election?: FringeElection;
  fringe_exception_note?: string;
}

/**
 * Sign the statement of compliance and freeze the week. The server refuses on
 * any compliance error, so a rejected certify is a finding list rather than a
 * failure to save.
 */
export async function certifyWeek(
  weekId: string,
  payload: CertifyPayload,
): Promise<CertifiedWeekDetail> {
  return apiPost<CertifiedWeekDetail, CertifyPayload>(
    `/v1/certified_payroll/weeks/${encodeURIComponent(weekId)}/certify/`,
    payload,
  );
}

/**
 * Download the weekly form. The endpoints are auth-gated, so a bare anchor href
 * would 401 - fetch the blob with the Bearer token and save it client-side.
 */
export async function downloadWeekForm(
  weekId: string,
  weekEnding: string,
  format: 'csv' | 'json',
): Promise<void> {
  const token = getAuthToken();
  const res = await fetch(
    `/api/v1/certified_payroll/weeks/${encodeURIComponent(weekId)}/form.${format}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) {
    throw new Error(`Export failed (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `certified-payroll-${weekEnding || weekId}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
