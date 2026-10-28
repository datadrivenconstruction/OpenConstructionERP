// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the engineering brief: the requirements of the client, the
// technical concept, the programme and the framework schedule of a project.
//
// Backend module: backend/app/modules/engineering_brief/router.py, mounted at
// /api/v1/engineering_brief/. Every project route lives under /projects/{project_id}/.
// Each call writes its full path as a literal, so the route check of the repo
// can compare it with the router, method included.
//
// Errors arrive as `detail = {code, message_key, message, violations?}`. The
// screens show the server's sentence for a refusal.

import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export type BriefStatus = 'draft' | 'in_review' | 'approved' | 'binding' | 'revising';
export type Priority = 'must' | 'should' | 'could' | 'wont';
export type ConceptStatus = 'open' | 'agreed';
export type ConstraintType =
  | 'equals'
  | 'not_equals'
  | 'min'
  | 'max'
  | 'range'
  | 'contains'
  | 'not_contains'
  | 'regex'
  | 'exists'
  | 'not_exists';
export type ExportFormat = 'pdf' | 'xlsx';
export type ExportWhat = 'requirements' | 'concept' | 'programme' | 'schedule';
export type Severity = 'error' | 'warning';

export interface BriefGate {
  id: string;
  code: string;
  label: string;
  order: number;
  status: string;
  target_date: string | null;
}

export function listGates(projectId: string) {
  return apiGet<Page<BriefGate>>(`/v1/engineering_brief/projects/${projectId}/gates`);
}

export const CONSTRAINT_TYPES: ConstraintType[] = [
  'equals',
  'not_equals',
  'min',
  'max',
  'range',
  'contains',
  'not_contains',
  'regex',
  'exists',
  'not_exists',
];
export const PRIORITIES: Priority[] = ['must', 'should', 'could', 'wont'];

/** One capability as the server decided it. `applies` is false when the action does not fit the state at all. */
export interface Can {
  allowed: boolean;
  reason: string | null;
  applies?: boolean;
}

export interface CatalogueSummary {
  kind: string;
  source: 'shipped' | 'tenant';
  id: string;
  code: string;
  name: { key: string | null; text: Record<string, string> | null };
  state: string;
  versions: number[];
  latest_version: number | null;
}

/** A catalogue item names itself by a locale key (shipped) or by texts per locale (tenant). */
export interface Labelled {
  code: string;
  name_key: string;
  labels: Record<string, string> | null;
}

export interface RequirementCategory extends Labelled {
  required: boolean;
  reference: string;
}
export interface ConceptTopic extends Labelled {
  required: boolean;
}
export interface ProgrammeKind extends Labelled {
  default_unit: string;
}
export interface MilestoneKind extends Labelled {
  anchor: boolean;
  gate: boolean;
}
export interface MilestoneTemplate extends Labelled {
  kind: string;
  successor: string | null;
  lead_days: number;
}

export interface BriefCatalogue {
  id: string;
  name_key: string;
  labels: Record<string, string> | null;
  version: number;
  requirement_categories: RequirementCategory[];
  concept_topics: ConceptTopic[];
  programme_kinds: ProgrammeKind[];
  milestone_kinds: MilestoneKind[];
  milestone_templates: MilestoneTemplate[];
  verification_methods: string[];
  originator_roles: string[];
  phases: string[];
  priorities: Priority[];
}

export interface Brief {
  id: string;
  project_id: string;
  catalogue_source: 'shipped' | 'tenant';
  catalogue_id: string;
  catalogue_version: number;
  status: BriefStatus;
  title: string;
  summary: string;
  operation_proof_date: string | null;
  submitted_at: string | null;
  approved_at: string | null;
  approval_source: string | null;
  requirements_changed: boolean;
  requirement_count: number;
  gates_in_use: boolean;
  can: {
    manage: Can;
    submit: Can;
    return: Can;
    approve: Can;
    edit: Can;
    publish: Can;
  };
}

export interface Finding {
  code: string;
  ref: string;
  severity: Severity;
  detail: string;
}

export interface Requirement {
  id: string;
  entity: string;
  attribute: string;
  constraint_type: ConstraintType;
  constraint_value: string;
  unit: string;
  category: string;
  priority: Priority;
  verification_method: string;
  originator: string;
  originator_role: string;
  source_ref: string;
  rationale: string;
  phase: string;
  status: string;
  /** Codes of the concept items that answer this requirement. */
  answered_by: string[];
}

export type RequirementInput = Omit<Requirement, 'id' | 'status' | 'answered_by'>;

export interface ConceptItem {
  id: string;
  code: string;
  topic_code: string;
  title: string;
  description: string;
  decision: string;
  status: ConceptStatus;
  requirement_ids: string[];
}
export interface ConceptInput {
  topic_code: string;
  title: string;
  description: string;
  decision: string;
  requirement_ids: string[];
}

export interface ProgrammeLine {
  id: string;
  code: string;
  kind_code: string;
  label: string;
  unit: string;
  /** A decimal string, never a float. */
  quantity: string;
  basis: string;
}
export interface ProgrammeInput {
  kind_code: string;
  label: string;
  unit: string;
  quantity: string;
  basis: string;
}

export interface MilestoneGate {
  code: string;
  label: string;
  status: string;
  target_date: string | null;
  bound_to_schedule: boolean;
}

export interface Milestone {
  id: string;
  code: string;
  kind_code: string;
  name: string;
  planned_date: string | null;
  lead_days: number;
  successor_id: string | null;
  gate_code: string | null;
  permit_requirement_id: string | null;
  activity_id: string | null;
  gate: MilestoneGate | null;
  permit_state: string | null;
  /** True when the milestone is published and its activity still exists. */
  published: boolean;
  findings: Finding[];
}
export interface MilestoneInput {
  kind_code: string;
  name: string;
  planned_date: string | null;
  lead_days: number;
  successor_id: string | null;
  gate_code: string | null;
  notes: string;
}

export interface BackplanChange {
  id: string;
  code: string;
  from: string | null;
  to: string;
  changed: boolean;
}
export interface BackplanResult {
  applied: boolean;
  changes: BackplanChange[];
  unreached: string[];
}
export interface PublishResult {
  schedule_id: string;
  created: number;
  moved: number;
  gates_bound: string[];
  gates_skipped: string[];
  gates_decided?: string[];
}

export type StudyKind = 'site_analysis' | 'suitability';
export type StudyConclusion = 'open' | 'suitable' | 'conditional' | 'unsuitable';
export const STUDY_KINDS: StudyKind[] = ['site_analysis', 'suitability'];
export const STUDY_CONCLUSIONS: StudyConclusion[] = ['open', 'suitable', 'conditional', 'unsuitable'];

export interface Study {
  id: string;
  code: string;
  kind: StudyKind;
  title: string;
  scope: string;
  author: string;
  study_date: string | null;
  result: string;
  conclusion: StudyConclusion;
  document_id: string | null;
  document_name?: string | null;
}
export interface StudyInput {
  kind: StudyKind;
  title: string;
  scope: string;
  author: string;
  study_date: string | null;
  result: string;
  conclusion: StudyConclusion;
  document_id: string | null;
}

export interface SpecificationIssue {
  id: string;
  version_no: number;
  title: string;
  issued_at: string;
  issued_by: string | null;
  document_id: string | null;
  requirements_hash: string;
  requirement_count: number;
  note: string;
}
export interface SpecificationState {
  items: SpecificationIssue[];
  current: boolean;
  stale: boolean;
  requirement_count: number;
  detail: string;
}

export interface BriefSetInput {
  catalogue_source: 'shipped' | 'tenant';
  catalogue_id: string;
  catalogue_version?: number;
  title: string;
  summary: string;
  operation_proof_date: string | null;
}
export interface BriefPatchInput {
  title?: string;
  summary?: string;
  operation_proof_date?: string | null;
}

/* ── Query keys ───────────────────────────────────────────────────────── */

export const briefKeys = {
  catalogues: ['engineering-brief', 'catalogues'] as const,
  /** Everything a write can change: the sweep key of every project query. */
  project: (projectId: string) => ['engineering-brief', projectId] as const,
  brief: (projectId: string) => ['engineering-brief', projectId, 'brief'] as const,
  catalogue: (projectId: string) => ['engineering-brief', projectId, 'catalogue'] as const,
  findings: (projectId: string) => ['engineering-brief', projectId, 'findings'] as const,
  requirements: (projectId: string) => ['engineering-brief', projectId, 'requirements'] as const,
  concept: (projectId: string) => ['engineering-brief', projectId, 'concept'] as const,
  programme: (projectId: string) => ['engineering-brief', projectId, 'programme'] as const,
  milestones: (projectId: string) => ['engineering-brief', projectId, 'milestones'] as const,
  studies: (projectId: string) => ['engineering-brief', projectId, 'studies'] as const,
  specification: (projectId: string) => ['engineering-brief', projectId, 'specification'] as const,
};

/* ── Errors ───────────────────────────────────────────────────────────── */

interface ErrorDetail {
  code?: unknown;
  message?: unknown;
}

function detailOf(err: unknown): ErrorDetail | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as ErrorDetail) : null;
}

/** The stable error code of a refusal, or null when the failure was not a brief refusal. */
export function briefErrorCode(err: unknown): string | null {
  const code = detailOf(err)?.code;
  return typeof code === 'string' ? code : null;
}

/** The sentence the server wrote for the refusal, already in the reader's language. */
export function briefErrorMessage(err: unknown): string | null {
  const message = detailOf(err)?.message;
  return typeof message === 'string' && message.trim() ? message : null;
}

/* ── Catalogues ───────────────────────────────────────────────────────── */

export function listCatalogues(): Promise<Page<CatalogueSummary>> {
  return apiGet<Page<CatalogueSummary>>('/v1/engineering_brief/catalogues');
}

export function getPinnedCatalogue(projectId: string): Promise<BriefCatalogue> {
  return apiGet<BriefCatalogue>(`/v1/engineering_brief/projects/${projectId}/catalogue`);
}

/* ── Brief ────────────────────────────────────────────────────────────── */

export function getBrief(projectId: string): Promise<Brief> {
  return apiGet<Brief>(`/v1/engineering_brief/projects/${projectId}/brief`);
}

export function setBrief(projectId: string, body: BriefSetInput): Promise<Brief> {
  return apiPut<Brief, BriefSetInput>(`/v1/engineering_brief/projects/${projectId}/brief`, body);
}

export function patchBrief(projectId: string, body: BriefPatchInput): Promise<Brief> {
  return apiPatch<Brief, BriefPatchInput>(`/v1/engineering_brief/projects/${projectId}/brief`, body);
}

export function submitBrief(projectId: string): Promise<Brief> {
  return apiPost<Brief>(`/v1/engineering_brief/projects/${projectId}/brief/submit`);
}

export function approveBrief(projectId: string): Promise<Brief> {
  return apiPost<Brief>(`/v1/engineering_brief/projects/${projectId}/brief/approve`);
}

export function returnBrief(projectId: string): Promise<Brief> {
  return apiPost<Brief>(`/v1/engineering_brief/projects/${projectId}/brief/return`);
}

export function listBriefFindings(projectId: string): Promise<Page<Finding>> {
  return apiGet<Page<Finding>>(`/v1/engineering_brief/projects/${projectId}/brief/findings`);
}

/* ── Requirements ─────────────────────────────────────────────────────── */

export function listRequirements(projectId: string): Promise<Page<Requirement>> {
  return apiGet<Page<Requirement>>(`/v1/engineering_brief/projects/${projectId}/requirements`);
}

export function createRequirement(projectId: string, body: RequirementInput): Promise<Requirement> {
  return apiPost<Requirement, RequirementInput>(`/v1/engineering_brief/projects/${projectId}/requirements`, body);
}

export function updateRequirement(
  projectId: string,
  id: string,
  body: Partial<RequirementInput>,
): Promise<Requirement> {
  return apiPatch<Requirement, Partial<RequirementInput>>(
    `/v1/engineering_brief/projects/${projectId}/requirements/${id}`,
    body,
  );
}

export function deleteRequirement(projectId: string, id: string): Promise<void> {
  return apiDelete(`/v1/engineering_brief/projects/${projectId}/requirements/${id}`);
}

/* ── Technical concept ────────────────────────────────────────────────── */

export function listConcepts(projectId: string): Promise<Page<ConceptItem>> {
  return apiGet<Page<ConceptItem>>(`/v1/engineering_brief/projects/${projectId}/concept`);
}

export function createConcept(projectId: string, body: ConceptInput): Promise<ConceptItem> {
  return apiPost<ConceptItem, ConceptInput>(`/v1/engineering_brief/projects/${projectId}/concept`, body);
}

export function conceptsFromCatalogue(projectId: string): Promise<Page<ConceptItem>> {
  return apiPost<Page<ConceptItem>>(`/v1/engineering_brief/projects/${projectId}/concept/from-catalogue`);
}

export function updateConcept(projectId: string, id: string, body: Partial<ConceptInput>): Promise<ConceptItem> {
  return apiPatch<ConceptItem, Partial<ConceptInput>>(`/v1/engineering_brief/projects/${projectId}/concept/${id}`, body);
}

export function setConceptStatus(projectId: string, id: string, status: ConceptStatus): Promise<ConceptItem> {
  return apiPost<ConceptItem, { status: ConceptStatus }>(
    `/v1/engineering_brief/projects/${projectId}/concept/${id}/status`,
    { status },
  );
}

export function deleteConcept(projectId: string, id: string): Promise<void> {
  return apiDelete(`/v1/engineering_brief/projects/${projectId}/concept/${id}`);
}

/* ── Programme ────────────────────────────────────────────────────────── */

export function listProgramme(projectId: string): Promise<Page<ProgrammeLine>> {
  return apiGet<Page<ProgrammeLine>>(`/v1/engineering_brief/projects/${projectId}/programme`);
}

export function createProgrammeLine(projectId: string, body: ProgrammeInput): Promise<ProgrammeLine> {
  return apiPost<ProgrammeLine, ProgrammeInput>(`/v1/engineering_brief/projects/${projectId}/programme`, body);
}

export function updateProgrammeLine(
  projectId: string,
  id: string,
  body: Partial<ProgrammeInput>,
): Promise<ProgrammeLine> {
  return apiPatch<ProgrammeLine, Partial<ProgrammeInput>>(
    `/v1/engineering_brief/projects/${projectId}/programme/${id}`,
    body,
  );
}

export function deleteProgrammeLine(projectId: string, id: string): Promise<void> {
  return apiDelete(`/v1/engineering_brief/projects/${projectId}/programme/${id}`);
}

/* ── Framework schedule ───────────────────────────────────────────────── */

export function listMilestones(projectId: string): Promise<Page<Milestone>> {
  return apiGet<Page<Milestone>>(`/v1/engineering_brief/projects/${projectId}/milestones`);
}

export function createMilestone(projectId: string, body: MilestoneInput): Promise<Milestone> {
  return apiPost<Milestone, MilestoneInput>(`/v1/engineering_brief/projects/${projectId}/milestones`, body);
}

export function milestonesFromCatalogue(projectId: string): Promise<Page<Milestone>> {
  return apiPost<Page<Milestone>, { codes: string[] | null }>(
    `/v1/engineering_brief/projects/${projectId}/milestones/from-catalogue`,
    { codes: null },
  );
}

export function milestonesFromGates(projectId: string): Promise<Page<Milestone>> {
  return apiPost<Page<Milestone>>(`/v1/engineering_brief/projects/${projectId}/milestones/from-gates`);
}

/** `apply: false` only reports the dates a backward plan would give; `true` writes them. */
export function backplan(projectId: string, apply: boolean): Promise<BackplanResult> {
  return apiPost<BackplanResult, { apply: boolean }>(
    `/v1/engineering_brief/projects/${projectId}/milestones/backplan`,
    { apply },
  );
}

export function publishSchedule(projectId: string): Promise<PublishResult> {
  return apiPost<PublishResult>(`/v1/engineering_brief/projects/${projectId}/milestones/publish`);
}

export function updateMilestone(projectId: string, id: string, body: Partial<MilestoneInput>): Promise<Milestone> {
  return apiPatch<Milestone, Partial<MilestoneInput>>(
    `/v1/engineering_brief/projects/${projectId}/milestones/${id}`,
    body,
  );
}

export function deleteMilestone(projectId: string, id: string): Promise<void> {
  return apiDelete(`/v1/engineering_brief/projects/${projectId}/milestones/${id}`);
}

/* ── Studies ──────────────────────────────────────────────────────────── */

export function listStudies(projectId: string): Promise<Page<Study>> {
  return apiGet<Page<Study>>(`/v1/engineering_brief/projects/${projectId}/studies`);
}

export function createStudy(projectId: string, body: StudyInput): Promise<Study> {
  return apiPost<Study, StudyInput>(`/v1/engineering_brief/projects/${projectId}/studies`, body);
}

export function updateStudy(projectId: string, id: string, body: Partial<StudyInput>): Promise<Study> {
  return apiPatch<Study, Partial<StudyInput>>(`/v1/engineering_brief/projects/${projectId}/studies/${id}`, body);
}

export function deleteStudy(projectId: string, id: string): Promise<void> {
  return apiDelete(`/v1/engineering_brief/projects/${projectId}/studies/${id}`);
}

/* ── Requirements specification ───────────────────────────────────────── */

export function getSpecification(projectId: string): Promise<SpecificationState> {
  return apiGet<SpecificationState>(`/v1/engineering_brief/projects/${projectId}/specification`);
}

export function issueSpecification(projectId: string, note: string): Promise<SpecificationIssue> {
  return apiPost<SpecificationIssue, { note: string }>(
    `/v1/engineering_brief/projects/${projectId}/specification/issue`,
    { note },
  );
}

/* ── Export ───────────────────────────────────────────────────────────── */

/** Download one register. The server names the file; the query parameter is `what`. */
export function downloadExport(projectId: string, what: ExportWhat, format: ExportFormat): Promise<void> {
  return downloadWithAuth(
    `/api/v1/engineering_brief/projects/${projectId}/export?what=${what}&format=${format}`,
    `engineering_brief_${what}.${format}`,
  );
}
