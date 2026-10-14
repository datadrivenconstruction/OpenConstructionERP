// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the project HSE frame: the facts that decide which duties
// apply, the register of requirements, reviews, clearances and targets, the
// appointed roles and the links to incidents, permits to work and audits.
//
// Backend module: backend/app/modules/hse_frame/router.py, mounted at
// /api/v1/hse-frame/. Every route lives under /projects/{project_id}/.
//
// Calendar days are ISO `YYYY-MM-DD` strings. Errors arrive as
// `detail = {code, message_key, message, violations?, info?}`.

import { API_BASE, ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export type FrameState = 'draft' | 'in_review' | 'approved' | 'binding' | 'revising';
export type ItemStatus = 'open' | 'in_progress' | 'met' | 'waived' | 'not_applicable';
export type Audience = 'owner' | 'designer' | 'contractor' | 'coordinator' | 'operator';
export type PlanStatus = 'not_started' | 'draft' | 'issued' | 'in_force';
export type LaterWorksStatus = 'not_started' | 'draft' | 'complete';
export type RoleStatus = 'proposed' | 'appointed' | 'ended';
export type ReadinessState = 'met' | 'not_met' | 'unknown' | 'warning';

export interface Frame {
  id: string;
  project_id: string;
  catalogue_source: string;
  catalogue_id: string;
  catalogue_version: number;
  state: FrameState;
  planned_start: string | null;
  duration_working_days: number | null;
  peak_workers: number | null;
  person_days: number | null;
  employers_count: number | null;
  hazardous_work_codes: string[];
  hazardous_works_assessed: boolean;
  advance_notice_sent_on: string | null;
  advance_notice_reference: string;
  plan_status: PlanStatus;
  plan_issued_on: string | null;
  later_works_status: LaterWorksStatus;
  notes: string;
  submitted_by: string | null;
  approved_by: string | null;
  version: number;
}

/** A duty the facts trigger: true, false, or null when the facts or the catalogue do not say. */
export type Duty = boolean | null;

export interface Duties {
  advance_notice: Duty;
  coordinator: Duty;
  plan: Duty;
  later_works_file: Duty;
  hazardous_work: Duty;
}

export interface FrameView {
  frame: Frame | null;
  catalogue: { id: string; labels: Record<string, string> | null; jurisdiction: string };
  duties: Duties | null;
}

export interface Labelled {
  code: string;
  labels: Record<string, string> | null;
}

export interface CatTopic extends Labelled {
  criterion: string | null;
  basis: 'items' | 'roles' | 'permits';
}

export interface CatRole extends Labelled {
  party: Audience;
  phase: string;
  required_when: string | null;
  national_name: string;
  qualification_required: boolean;
  legal_basis: string;
}

export interface CatTemplate extends Labelled {
  topic: string;
  obligation: 'mandatory' | 'recommended';
  legal_basis: string;
  applies_when: string | null;
}

export interface Catalogue {
  id: string;
  labels: Record<string, string> | null;
  jurisdiction: string;
  topics: CatTopic[];
  role_kinds: CatRole[];
  templates: CatTemplate[];
  hazardous_works: Labelled[];
  plan_elements: Labelled[];
  thresholds: Record<string, unknown>;
  link_kinds: string[];
  item_statuses: ItemStatus[];
}

export interface LinkFact {
  kind: string;
  number: string | null;
  title: string | null;
  status: string | null;
  date: string | null;
  severity: string | null;
}

export interface ItemLink {
  id: string;
  item_id: string;
  link_kind: string;
  link_id: string;
  note: string;
  fact: LinkFact | null;
}

export interface Item {
  id: string;
  topic: string;
  template_code: string | null;
  title: string;
  description: string;
  audience: Audience[];
  obligation: 'mandatory' | 'recommended';
  legal_basis: string;
  status: ItemStatus;
  responsible_user_id: string | null;
  responsible_party: string;
  due_date: string | null;
  met_on: string | null;
  evidence_note: string;
  waive_reason: string;
  in_tender_documents: boolean;
  source: string;
  overdue: boolean;
  links: ItemLink[];
}

export interface Role {
  id: string;
  role_code: string;
  person_user_id: string | null;
  person_name: string;
  organisation: string;
  status: RoleStatus;
  appointed_on: string | null;
  ends_on: string | null;
  qualification: string;
  qualification_valid_until: string | null;
  in_force: boolean;
}

export interface ReadinessItem {
  code: string;
  topic: string;
  criterion: string | null;
  state: ReadinessState;
  detail: string;
  label: string;
}

export interface Readiness {
  frame_state: FrameState;
  items: ReadinessItem[];
  duties: Duties;
}

export interface Summary {
  incidents_open: number | null;
  incidents_serious_open_unlinked: number | null;
  observations_open: number | null;
  permits_to_work_active: number | null;
  corrective_actions_open: number | null;
  audits: number | null;
  inspections: number | null;
  permit_conditions_hse: number | null;
  permit_conditions_hse_open: number;
  permit_conditions_hse_overdue: number;
}

export interface Check {
  rule_id: string;
  passed: boolean;
  severity: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface Candidate extends LinkFact {
  id: string;
}

export type FramePatch = Partial<
  Pick<
    Frame,
    | 'planned_start'
    | 'duration_working_days'
    | 'peak_workers'
    | 'person_days'
    | 'employers_count'
    | 'hazardous_work_codes'
    | 'hazardous_works_assessed'
    | 'advance_notice_sent_on'
    | 'advance_notice_reference'
    | 'plan_status'
    | 'plan_issued_on'
    | 'later_works_status'
    | 'notes'
  >
>;

export interface ItemCreate {
  topic: string;
  title: string;
  description?: string;
  audience?: Audience[];
  obligation?: 'mandatory' | 'recommended';
  responsible_party?: string;
  due_date?: string | null;
  in_tender_documents?: boolean;
}

export interface RoleCreate {
  role_code: string;
  person_name?: string;
  organisation?: string;
  status?: RoleStatus;
  appointed_on?: string | null;
  qualification?: string;
  qualification_valid_until?: string | null;
}

export type ExportWhat = 'register' | 'roles';

export function downloadExport(projectId: string, what: ExportWhat, format: 'pdf' | 'xlsx'): Promise<void> {
  return downloadWithAuth(`${API_BASE}/v1/hse-frame/projects/${projectId}/export?what=${what}&format=${format}`, `hse_${what}.${format}`);
}

export const getFrame = (p: string) => apiGet<FrameView>(`/v1/hse-frame/projects/${p}/frame`);
export const createFrame = (p: string) => apiPost<Frame>(`/v1/hse-frame/projects/${p}/frame`);
export const patchFrame = (p: string, body: FramePatch) => apiPatch<Frame, FramePatch>(`/v1/hse-frame/projects/${p}/frame`, body);
export const getCatalogue = (p: string) => apiGet<Catalogue>(`/v1/hse-frame/projects/${p}/catalogue`);
export const applyTemplates = (p: string) =>
  apiPost<{ created: number; skipped: number }>(`/v1/hse-frame/projects/${p}/frame/apply-templates`);
export const consolidatePermitConditions = (p: string) =>
  apiPost<{ created: number; already_linked: number }>(`/v1/hse-frame/projects/${p}/frame/consolidate-permit-conditions`);
export const submitFrame = (p: string) => apiPost<Frame>(`/v1/hse-frame/projects/${p}/frame/submit`);
export const approveFrame = (p: string) => apiPost<Frame>(`/v1/hse-frame/projects/${p}/frame/approve`);
export const reviseFrame = (p: string, note = '') => apiPost<Frame>(`/v1/hse-frame/projects/${p}/frame/revise`, { note });
export const pinCatalogue = (p: string, body: { source: string; catalogue_id: string; version?: number }) =>
  apiPut<Frame, typeof body>(`/v1/hse-frame/projects/${p}/frame/catalogue`, body);

export const listItems = (p: string) => apiGet<Page<Item>>(`/v1/hse-frame/projects/${p}/items`);
export const createItem = (p: string, body: ItemCreate) => apiPost<Item, ItemCreate>(`/v1/hse-frame/projects/${p}/items`, body);
export const patchItem = (p: string, id: string, body: Partial<Item>) =>
  apiPatch<Item, Partial<Item>>(`/v1/hse-frame/projects/${p}/items/${id}`, body);
export const meetItem = (p: string, id: string, body: { met_on?: string; evidence_note?: string }) =>
  apiPost<Item, typeof body>(`/v1/hse-frame/projects/${p}/items/${id}/meet`, body);
export const waiveItem = (p: string, id: string, body: { reason: string; not_applicable: boolean }) =>
  apiPost<Item, typeof body>(`/v1/hse-frame/projects/${p}/items/${id}/waive`, body);
export const reopenItem = (p: string, id: string) => apiPost<Item>(`/v1/hse-frame/projects/${p}/items/${id}/reopen`);
export const deleteItem = (p: string, id: string) => apiDelete(`/v1/hse-frame/projects/${p}/items/${id}`);
export const addLink = (p: string, itemId: string, body: { link_kind: string; link_id: string }) =>
  apiPost<Item, typeof body>(`/v1/hse-frame/projects/${p}/items/${itemId}/links`, body);
export const removeLink = (p: string, itemId: string, linkId: string) =>
  apiDelete(`/v1/hse-frame/projects/${p}/items/${itemId}/links/${linkId}`);
export const listCandidates = (p: string, kind: string, q: string) =>
  apiGet<Page<Candidate>>(`/v1/hse-frame/projects/${p}/link-candidates?kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(q)}`);

export const listRoles = (p: string) => apiGet<Page<Role>>(`/v1/hse-frame/projects/${p}/roles`);
export const createRole = (p: string, body: RoleCreate) => apiPost<Role, RoleCreate>(`/v1/hse-frame/projects/${p}/roles`, body);
export const patchRole = (p: string, id: string, body: Partial<Role>) =>
  apiPatch<Role, Partial<Role>>(`/v1/hse-frame/projects/${p}/roles/${id}`, body);
export const deleteRole = (p: string, id: string) => apiDelete(`/v1/hse-frame/projects/${p}/roles/${id}`);

export const getReadiness = (p: string) => apiGet<Readiness>(`/v1/hse-frame/projects/${p}/readiness`);
export const getSummary = (p: string) => apiGet<Summary>(`/v1/hse-frame/projects/${p}/summary`);
export const getChecks = (p: string) => apiGet<Page<Check>>(`/v1/hse-frame/projects/${p}/validation`);

export const hseKeys = {
  all: (p: string) => ['hse-frame', p] as const,
  frame: (p: string) => ['hse-frame', p, 'frame'] as const,
  catalogue: (p: string) => ['hse-frame', p, 'catalogue'] as const,
  items: (p: string) => ['hse-frame', p, 'items'] as const,
  roles: (p: string) => ['hse-frame', p, 'roles'] as const,
  readiness: (p: string) => ['hse-frame', p, 'readiness'] as const,
  summary: (p: string) => ['hse-frame', p, 'summary'] as const,
  checks: (p: string) => ['hse-frame', p, 'checks'] as const,
  candidates: (p: string, kind: string, q: string) => ['hse-frame', p, 'candidates', kind, q] as const,
};

/** The refusal body the server answers with, or null for any other failure. */
export function refusalOf(err: unknown): { code: string | null; message: string | null } | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  const d = detail as Record<string, unknown>;
  return {
    code: typeof d.code === 'string' ? d.code : null,
    message: typeof d.message === 'string' ? d.message : null,
  };
}

/** Today as the calendar day the reader is living in, not UTC. */
export function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}
