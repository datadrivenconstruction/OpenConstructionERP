/**
 * API helpers + types for the HSE Advanced module.
 *
 * Endpoints are prefixed with /v1/hse-advanced/.
 *
 * api-HIGH contract realignment: every interface, create-payload and helper
 * below is aligned to the REAL backend schemas in
 * backend/app/modules/hse_advanced/schemas.py (+ router.py). The previous
 * version was written against field names the backend never serves
 * (investigation_number/title/incident_date/severity, jsa_number,
 * permit.title/scope/expires_at, talk_number/presenter/talk_date,
 * ppe_number/item_type/issued_to_name/quantity, audit_number/auditor/audit_date,
 * capa_number/assigned_to/due_date), which made every table render blank cells
 * and every Create button 422. Backend is the single source of truth.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* -- Shared types --------------------------------------------------------- */

// Backend investigation status enum (schemas.py InvestigationCreate.status):
// in_progress | completed | abandoned. There is no "pending"/"cancelled".
export type InvestigationStatus = 'in_progress' | 'completed' | 'abandoned';
// Investigation method (schemas.py InvestigationCreate.method).
export type InvestigationMethod = '5_whys' | 'fishbone' | 'timeline' | 'swot';
export type PermitStatus =
  | 'requested'
  | 'approved'
  | 'active'
  | 'suspended'
  | 'closed'
  | 'cancelled'
  | 'expired';
// Backend CAPA status enum (schemas.py CAPACreate.status). No "verified"/"closed".
export type CAPAStatus = 'open' | 'in_progress' | 'completed' | 'overdue' | 'cancelled';
export type AuditStatus = 'scheduled' | 'in_progress' | 'completed' | 'cancelled';
export type CertificationStatus = 'valid' | 'expired' | 'revoked';

/* -- Incident Investigation ----------------------------------------------- */

// Matches schemas.py InvestigationResponse exactly. The investigation is keyed
// off an incident (incident_ref) — it has no project_id, title, severity or
// incident_date of its own; those live on the linked safety incident.
export interface IncidentInvestigation {
  id: string;
  incident_ref: string;
  investigation_lead?: string | null;
  started_at: string;
  completed_at?: string | null;
  method: InvestigationMethod;
  findings: string;
  recommendations: string;
  status: InvestigationStatus;
  report_url?: string | null;
  created_at: string;
  updated_at: string;
}

// InvestigationCreate requires incident_ref + started_at (schemas.py:44-50).
export interface CreateInvestigationPayload {
  incident_ref: string;
  started_at: string;
  investigation_lead?: string | null;
  method?: InvestigationMethod;
  findings?: string;
  recommendations?: string;
  status?: InvestigationStatus;
  report_url?: string | null;
}

/* -- Job Safety Analysis -------------------------------------------------- */

// JSA hazard rows are returned as opaque dicts (schemas.py JSAResponse.hazards:
// list[dict[str, Any]]).
export interface JSAHazard {
  step?: string;
  hazard?: string;
  severity?: number;
  likelihood?: number;
  controls?: string;
}

// Matches schemas.py JSAResponse. No jsa_number/title — task_description + risk_score.
export interface JobSafetyAnalysis {
  id: string;
  project_id: string;
  task_description: string;
  location?: string | null;
  work_date: string;
  prepared_by?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  status: string;
  hazards: JSAHazard[];
  required_ppe: string[];
  risk_score: number;
  created_at: string;
  updated_at: string;
}

// JSACreate requires project_id + task_description + work_date (schemas.py:110-113).
export interface CreateJSAPayload {
  project_id: string;
  task_description: string;
  work_date: string;
  location?: string | null;
  status?: string;
}

/* -- Permit to Work ------------------------------------------------------- */

// Matches schemas.py PermitResponse. No title/scope/expires_at — the permit
// has permit_number + description and a work_start/work_end window. The
// prereq_* flags gate the requested → active transition.
export interface PermitToWork {
  id: string;
  project_id: string;
  permit_number: string;
  permit_type: string;
  description: string;
  location?: string | null;
  work_start: string;
  work_end: string;
  applicant_id?: string | null;
  supervisor_id?: string | null;
  jsa_id?: string | null;
  status: PermitStatus;
  approved_at?: string | null;
  approved_by?: string | null;
  conditions: string;
  closure_checklist_passed: boolean;
  closure_notes: string;
  prereq_jsa_approved?: boolean;
  prereq_supervisor_present?: boolean;
  prereq_fire_watch_assigned?: boolean;
  prereq_extinguisher_present?: boolean;
  prereq_atmospheric_test_passed?: boolean;
  created_at: string;
  updated_at: string;
}

// PermitCreate requires project_id + permit_number + permit_type + work_start +
// work_end (schemas.py:168-180). The form's free-text scope maps to description.
export interface CreatePermitPayload {
  project_id: string;
  permit_number: string;
  permit_type: string;
  work_start: string;
  work_end: string;
  description?: string;
  location?: string | null;
  conditions?: string;
}

/* -- Toolbox Talk --------------------------------------------------------- */

// Matches schemas.py ToolboxTalkResponse. No talk_number/title/presenter/talk_date
// — topic_code/topic_title/conducted_at/conducted_by + an attendance_count int.
export interface ToolboxTalk {
  id: string;
  project_id: string;
  topic_code: string;
  topic_title: string;
  conducted_at: string;
  conducted_by?: string | null;
  language: string;
  attendance_count: number;
  notes: string;
  library_topic_ref?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ToolboxTopic {
  id: string;
  code: string;
  title: string;
  content?: string;
  category?: string | null;
  language?: string;
}

// ToolboxTalkCreate requires project_id + topic_code + topic_title + conducted_at
// (schemas.py:346-349).
export interface CreateToolboxTalkPayload {
  project_id: string;
  topic_code: string;
  topic_title: string;
  conducted_at: string;
  conducted_by?: string | null;
  language?: string;
  notes?: string;
}

/* -- PPE Issue ------------------------------------------------------------ */

export type PPEStatus = 'issued' | 'in_use' | 'returned' | 'lost' | 'damaged';

// Matches schemas.py PPEIssueResponse. There is NO project_id, ppe_number,
// item_type, quantity or return_by — it uses ppe_type + recipient_name and a
// date-typed valid_until. The list endpoint is org-wide (no project scoping).
export interface PPEIssue {
  id: string;
  recipient_user_id?: string | null;
  recipient_name?: string | null;
  recipient_company?: string | null;
  issued_at: string;
  issued_by?: string | null;
  ppe_type: string;
  size?: string | null;
  brand?: string | null;
  serial?: string | null;
  valid_until?: string | null;
  returned_at?: string | null;
  status: PPEStatus;
  created_at: string;
  updated_at: string;
}

// PPEIssueCreate requires ppe_type + issued_at (schemas.py:470-478); recipient_name
// is optional. No project_id/quantity/return_by exist on the backend.
export interface CreatePPEIssuePayload {
  ppe_type: string;
  issued_at: string;
  recipient_name?: string | null;
  recipient_company?: string | null;
  size?: string | null;
  valid_until?: string | null;
  status?: PPEStatus;
}

/* -- Safety Audit --------------------------------------------------------- */

// Matches schemas.py AuditResponse. No audit_number/title/auditor/audit_date —
// audit_type/conducted_at/conducted_by/summary. score_total + max_score are
// Decimal, serialized as STRING (or null); never do arithmetic without Number().
export interface SafetyAudit {
  id: string;
  project_id: string;
  audit_type: string;
  conducted_at: string;
  conducted_by?: string | null;
  score_total?: string | number | null;
  max_score?: string | number | null;
  status: AuditStatus;
  summary: string;
  checklist_template_ref?: string | null;
  created_at: string;
  updated_at: string;
}

// AuditCreate requires project_id + audit_type + conducted_at (schemas.py:535-540).
export interface CreateAuditPayload {
  project_id: string;
  audit_type: string;
  conducted_at: string;
  summary?: string;
  status?: AuditStatus;
}

/* -- Corrective Action (CAPA) -------------------------------------------- */

// Matches schemas.py CAPAResponse. No capa_number/assigned_to/due_date —
// source_type/owner_user_id/target_date. Note owner_user_id is a UUID, not a name.
export interface CorrectiveAction {
  id: string;
  project_id: string;
  source_type: string;
  source_ref?: string | null;
  title: string;
  description: string;
  owner_user_id?: string | null;
  target_date: string;
  status: CAPAStatus;
  completed_at?: string | null;
  verification_notes: string;
  root_cause_category?: string | null;
  five_whys?: Array<Record<string, unknown>> | null;
  effectiveness_verified_at?: string | null;
  effectiveness_verified_by?: string | null;
  created_at: string;
  updated_at: string;
}

// CAPACreate requires project_id + source_type + title + target_date
// (schemas.py:648-657). source_type is an enum; the UI defaults to "observation".
// source_ref is the optional UUID of the originating record (incident, jsa,
// permit or audit) — populated by the dependent source picker / audit-finding
// shortcut so the CAPA links back to what raised it.
export interface CreateCAPAPayload {
  project_id: string;
  source_type: string;
  source_ref?: string | null;
  title: string;
  target_date: string;
  description?: string;
  owner_user_id?: string | null;
  status?: CAPAStatus;
}

/* -- Safety Certification ------------------------------------------------- */

export interface SafetyCertification {
  id: string;
  owner_user_id?: string | null;
  owner_name?: string | null;
  owner_company?: string | null;
  cert_type: string;
  issued_by?: string | null;
  issue_date: string;
  valid_until: string;
  document_url?: string | null;
  status: CertificationStatus;
  created_at: string;
  updated_at: string;
}

/* -- HSE KPI -------------------------------------------------------------- */

// Matches schemas.py KPIResponse. The Decimal fields (hours_worked/trir/ltifr)
// serialize as STRING; Number()-wrap before any arithmetic or .toFixed().
export interface HSEKpi {
  project_id: string;
  period_start: string | null;
  period_end: string | null;
  hours_worked: string | number;
  recordable_count: number;
  lti_count: number;
  trir: string | number;
  ltifr: string | number;
  days_without_lti: number | null;
}

/* -- Endpoints ------------------------------------------------------------ */

const BASE = '/v1/hse-advanced';

export const fetchInvestigations = (projectId: string) =>
  apiGet<IncidentInvestigation[] | { items: IncidentInvestigation[] }>(
    `${BASE}/investigations/?project_id=${projectId}`,
  );

export const fetchInvestigation = (id: string) =>
  apiGet<IncidentInvestigation>(`${BASE}/investigations/${id}`);

export const createInvestigation = (payload: CreateInvestigationPayload) =>
  apiPost<IncidentInvestigation>(`${BASE}/investigations/`, payload);

export const updateInvestigation = (
  id: string,
  payload: Partial<CreateInvestigationPayload>,
) => apiPatch<IncidentInvestigation>(`${BASE}/investigations/${id}`, payload);

export const deleteInvestigation = (id: string) => apiDelete(`${BASE}/investigations/${id}`);

export const fetchJSAs = (projectId: string) =>
  apiGet<JobSafetyAnalysis[] | { items: JobSafetyAnalysis[] }>(
    `${BASE}/jsa/?project_id=${projectId}`,
  );

export const createJSA = (payload: CreateJSAPayload) =>
  apiPost<JobSafetyAnalysis>(`${BASE}/jsa/`, payload);

/* JSA lifecycle FSM — draft → under_review (submit) → approved → active →
 * archived (router.py:279-340). The endpoints take no body. */
export const submitJSA = (id: string) =>
  apiPost<JobSafetyAnalysis>(`${BASE}/jsa/${id}/submit`, {});
export const approveJSA = (id: string) =>
  apiPost<JobSafetyAnalysis>(`${BASE}/jsa/${id}/approve`, {});
export const activateJSA = (id: string) =>
  apiPost<JobSafetyAnalysis>(`${BASE}/jsa/${id}/activate`, {});
export const archiveJSA = (id: string) =>
  apiPost<JobSafetyAnalysis>(`${BASE}/jsa/${id}/archive`, {});

export const fetchPermits = (projectId: string) =>
  apiGet<PermitToWork[] | { items: PermitToWork[] }>(`${BASE}/permits/?project_id=${projectId}`);

export const createPermit = (payload: CreatePermitPayload) =>
  apiPost<PermitToWork>(`${BASE}/permits/`, payload);

/* Permit lifecycle FSM — requested → approved → active →
 * suspended/closed/cancelled (router.py:419-478). */
export interface PermitPrerequisites {
  prereq_jsa_approved?: boolean | null;
  prereq_supervisor_present?: boolean | null;
  prereq_fire_watch_assigned?: boolean | null;
  prereq_extinguisher_present?: boolean | null;
  prereq_atmospheric_test_passed?: boolean | null;
}

export const approvePermit = (id: string, conditions = '') =>
  apiPost<PermitToWork>(`${BASE}/permits/${id}/approve`, { conditions });
export const activatePermit = (id: string) =>
  apiPost<PermitToWork>(`${BASE}/permits/${id}/activate`, {});
export const suspendPermit = (id: string) =>
  apiPost<PermitToWork>(`${BASE}/permits/${id}/suspend`, {});
export const closePermit = (
  id: string,
  body: { closure_checklist_passed?: boolean; closure_notes?: string } = {},
) => apiPost<PermitToWork>(`${BASE}/permits/${id}/close`, body);
export const cancelPermit = (id: string) =>
  apiPost<PermitToWork>(`${BASE}/permits/${id}/cancel`, {});
export const updatePermitPrerequisites = (id: string, body: PermitPrerequisites) =>
  apiPatch<PermitToWork>(`${BASE}/permits/${id}/prerequisites`, body);

export const fetchToolboxTalks = (projectId: string) =>
  apiGet<ToolboxTalk[] | { items: ToolboxTalk[] }>(
    `${BASE}/toolbox-talks/?project_id=${projectId}`,
  );

export const createToolboxTalk = (payload: CreateToolboxTalkPayload) =>
  apiPost<ToolboxTalk>(`${BASE}/toolbox-talks/`, payload);

export const fetchToolboxTopics = () =>
  apiGet<ToolboxTopic[] | { items: ToolboxTopic[] }>(`${BASE}/toolbox-topics/`);

// The PPE list endpoint is org-wide — the backend route takes no project_id
// query param (router.py:610-625), so we deliberately fetch without one.
export const fetchPPEIssues = () =>
  apiGet<PPEIssue[] | { items: PPEIssue[] }>(`${BASE}/ppe-issues/`);

export const createPPEIssue = (payload: CreatePPEIssuePayload) =>
  apiPost<PPEIssue>(`${BASE}/ppe-issues/`, payload);

export const fetchAudits = (projectId: string) =>
  apiGet<SafetyAudit[] | { items: SafetyAudit[] }>(`${BASE}/audits/?project_id=${projectId}`);

export const createAudit = (payload: CreateAuditPayload) =>
  apiPost<SafetyAudit>(`${BASE}/audits/`, payload);

/* -- Audit findings + completion (router.py:748-793) --------------------- */

export type AuditFindingCategory =
  | 'PPE'
  | 'permit'
  | 'housekeeping'
  | 'electrical'
  | 'fire'
  | 'environmental'
  | 'other';
export type AuditFindingSeverity = 'low' | 'med' | 'high' | 'critical';

// Matches schemas.py AuditFindingResponse.
export interface AuditFinding {
  id: string;
  audit_id: string;
  item_description: string;
  category: AuditFindingCategory;
  severity: AuditFindingSeverity;
  is_passed: boolean;
  evidence_url?: string | null;
  corrective_action_ref?: string | null;
  created_at: string;
  updated_at: string;
}

// AuditFindingCreate (schemas.py AuditFindingPayload). is_passed scores the
// audit; failed findings drag the score down.
export interface CreateAuditFindingPayload {
  item_description: string;
  category?: AuditFindingCategory;
  severity?: AuditFindingSeverity;
  is_passed?: boolean;
  evidence_url?: string | null;
}

export const fetchAuditFindings = (auditId: string) =>
  apiGet<AuditFinding[] | { items: AuditFinding[] }>(`${BASE}/audits/${auditId}/findings`);

export const createAuditFinding = (auditId: string, payload: CreateAuditFindingPayload) =>
  apiPost<AuditFinding>(`${BASE}/audits/${auditId}/findings`, payload);

export const deleteAuditFinding = (findingId: string) =>
  apiDelete(`${BASE}/audit-findings/${findingId}`);

export const completeAudit = (auditId: string) =>
  apiPost<SafetyAudit>(`${BASE}/audits/${auditId}/complete`, {});

export const fetchCAPAs = (projectId: string) =>
  apiGet<CorrectiveAction[] | { items: CorrectiveAction[] }>(
    `${BASE}/capas/?project_id=${projectId}`,
  );

export const createCAPA = (payload: CreateCAPAPayload) =>
  apiPost<CorrectiveAction>(`${BASE}/capas/`, payload);

/* -- CAPA lifecycle + 5-Whys + effectiveness (router.py:865-909,1163-1194) */

export type RootCauseCategory =
  | 'manpower'
  | 'method'
  | 'material'
  | 'machine'
  | 'environment'
  | 'management'
  | 'other';

export interface FiveWhyStep {
  why: string;
  answer: string;
}

export const completeCAPA = (id: string, verification_notes = '') =>
  apiPost<CorrectiveAction>(`${BASE}/capas/${id}/complete`, { verification_notes });

export const escalateCAPA = (id: string) =>
  apiPost<CorrectiveAction>(`${BASE}/capas/${id}/escalate`, {});

export const cancelCAPA = (id: string) =>
  apiPost<CorrectiveAction>(`${BASE}/capas/${id}/cancel`, {});

export const setCAPAFiveWhys = (
  id: string,
  body: { steps: FiveWhyStep[]; root_cause_category?: RootCauseCategory | null },
) => apiPost<CorrectiveAction>(`${BASE}/capas/${id}/five-whys`, body);

export const verifyCAPAEffectiveness = (
  id: string,
  body: { effective: boolean; notes?: string },
) => apiPost<CorrectiveAction>(`${BASE}/capas/${id}/effectiveness`, body);

export const fetchCertifications = () =>
  apiGet<SafetyCertification[] | { items: SafetyCertification[] }>(`${BASE}/certifications/`);

// KPI endpoint has NO trailing slash (router.py:987 GET /kpi/project/{id}).
export const getKpi = (projectId: string) =>
  apiGet<HSEKpi>(`${BASE}/kpi/project/${projectId}`);

/* -- OSHA 300 CSV + slim corrective-action FSM (T6 / v3086) --------------- */

/** Strict FSM target states for the slim incident-scoped CorrectiveAction. */
export type CATargetStatus = 'pending' | 'in_progress' | 'verified' | 'closed';

export interface CATransitionRequest {
  to_status: CATargetStatus;
  verification_notes?: string;
}

export interface CorrectiveActionRow {
  id: string;
  incident_id: string;
  description: string;
  assigned_to_user_id?: string | null;
  due_date?: string | null;
  status: CATargetStatus;
  verified_by_user_id?: string | null;
  verified_at?: string | null;
  verification_notes?: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Trigger an OSHA Form 300 CSV download for a project + calendar year.
 *
 * The endpoint streams ``text/csv; charset=utf-8`` with a
 * ``Content-Disposition: attachment`` header, so we hand the URL to the
 * browser via a synthetic ``<a download>`` click rather than going
 * through ``apiGet``: that lets the browser show its own save dialog and
 * respect the server-supplied filename.
 */
export function downloadOsha300Csv(projectId: string, year: number): void {
  const url = `/api${BASE}/osha-300-log.csv?project_id=${encodeURIComponent(
    projectId,
  )}&year=${encodeURIComponent(String(year))}`;
  const a = document.createElement('a');
  a.href = url;
  a.rel = 'noopener';
  // Suggested filename — the server's Content-Disposition wins when the
  // browser honours it, but this keeps in-page text readable.
  a.download = `osha-300-${year}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/* -- Safety incident options (cross-module picker) ----------------------- */

// Slim projection of a safety incident for the investigation / CAPA source
// pickers. The full record lives in the Safety module; we only read the few
// fields needed to label the dropdown and carry the id (which becomes the
// investigation's incident_ref or the CAPA's source_ref).
export interface SafetyIncidentOption {
  id: string;
  incident_number: string;
  incident_date: string;
  incident_type: string;
  description: string;
}

/**
 * Fetch the project's safety incidents so the HSE pages can offer a real
 * picker instead of a raw-UUID field. Hits the Safety module endpoint
 * directly (it is the system of record for incidents).
 */
export const fetchSafetyIncidents = (projectId: string) =>
  apiGet<SafetyIncidentOption[] | { items: SafetyIncidentOption[] }>(
    `/v1/safety/incidents/?project_id=${encodeURIComponent(projectId)}`,
  );

export const fetchCorrectiveActions = (params: {
  projectId?: string;
  incidentId?: string;
  status?: CATargetStatus;
}) => {
  const qs = new URLSearchParams();
  if (params.projectId) qs.set('project_id', params.projectId);
  if (params.incidentId) qs.set('incident_id', params.incidentId);
  if (params.status) qs.set('status', params.status);
  return apiGet<CorrectiveActionRow[] | { items: CorrectiveActionRow[] }>(
    `${BASE}/corrective-actions/?${qs.toString()}`,
  );
};

export const transitionCorrectiveAction = (
  caId: string,
  body: CATransitionRequest,
) =>
  apiPost<CorrectiveActionRow>(
    `${BASE}/corrective-actions/${caId}/transition`,
    body,
  );

/* -- Helpers -------------------------------------------------------------- */

/** Days between today and a target date string (YYYY-MM-DD or ISO). Negative if past. */
export function daysUntil(dateStr: string | null | undefined): number | null {
  if (!dateStr) return null;
  const target = new Date(dateStr);
  if (Number.isNaN(target.getTime())) return null;
  const now = new Date();
  const target0 = new Date(target.getFullYear(), target.getMonth(), target.getDate()).getTime();
  const today0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  return Math.round((target0 - today0) / 86_400_000);
}
