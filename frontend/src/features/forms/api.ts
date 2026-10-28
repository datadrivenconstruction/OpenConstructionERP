// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed client for the Forms & Checklists module (/api/v1/forms).
//
// Two halves: a reusable template library (build once, reuse everywhere) and
// project-scoped submissions (a template filled in on site). Templates are
// versioned by snapshot - a submission freezes the template's fields at fill
// time - so the answers a submission holds always match the fields it was filled
// against, even after the template is edited or deleted.

import { apiGet, apiPost, apiPatch, apiDelete, API_BASE, getAuthToken, triggerDownload } from '@/shared/lib/api';


/* -- Field vocabulary (keep in lock-step with backend validation.FIELD_TYPES) - */

export type FieldType =
  | 'section'
  | 'short_text'
  | 'long_text'
  | 'number'
  | 'single_choice'
  | 'multi_choice'
  | 'checkbox'
  | 'pass_fail_na'
  | 'rating'
  | 'photo'
  | 'signature'
  | 'date'
  | 'formula';

/** A comparison operator usable in a conditional (branching) rule. */
export type ConditionOp =
  | 'eq'
  | 'neq'
  | 'in'
  | 'not_in'
  | 'gt'
  | 'lt'
  | 'gte'
  | 'lte'
  | 'empty'
  | 'not_empty';

/**
 * A branching rule attached to a field via visible_if / required_if. It is
 * either a single comparison (field + op [+ value]) or a boolean group of
 * nested expressions - all (every one holds) or any (at least one holds). Kept
 * in lock-step with backend conditional.CONDITION_OPERATORS.
 */
export interface ConditionExpr {
  field?: string;
  op?: ConditionOp;
  value?: string | number | boolean | string[] | null;
  all?: ConditionExpr[];
  any?: ConditionExpr[];
}

export type TemplateCategory =
  | 'safety'
  | 'quality'
  | 'handover'
  | 'inspection'
  | 'commissioning'
  | 'custom';

export type TemplateStatus = 'draft' | 'published' | 'archived';
export type SubmissionStatus = 'draft' | 'completed';
export type FormResult = 'pass' | 'fail' | 'na' | null;

/** A single field definition inside a template / snapshot. */
export interface FormFieldDef {
  key: string;
  type: FieldType;
  label: string;
  required: boolean;
  help_text?: string | null;
  options?: string[];
  unit?: string | null;
  max_rating?: number | null;
  /* -- Per-field capture config (all optional, type-dependent) -- */
  placeholder?: string | null;
  default?: string | number | boolean | string[] | null;
  min?: number | null;
  max?: number | null;
  min_length?: number | null;
  pattern?: string | null;
  /** Expression for a computed (formula) field, read against other field keys. */
  formula?: string | null;
  /* -- Conditional (branching) logic -- */
  visible_if?: ConditionExpr | null;
  required_if?: ConditionExpr | null;
}

/** A captured signature answer. */
export interface SignatureValue {
  name?: string;
  data?: string;
  signed_at?: string;
}

/** Answer values are heterogenous by field type; the filler narrows per field. */
export type AnswerValue = string | number | boolean | string[] | SignatureValue | null;
export type AnswerMap = Record<string, AnswerValue>;

/* -- Templates ------------------------------------------------------------- */

export interface TemplateSummary {
  id: string;
  project_id: string | null;
  name: string;
  description: string | null;
  category: TemplateCategory;
  status: TemplateStatus;
  version: number;
  field_count: number;
  tags: string[];
  is_seed: boolean;
  updated_at: string;
}

export interface TemplateDetail extends Omit<TemplateSummary, 'field_count'> {
  fields: FormFieldDef[];
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface TemplateCreatePayload {
  project_id?: string | null;
  name: string;
  description?: string | null;
  category: TemplateCategory;
  status?: TemplateStatus;
  fields: FormFieldDef[];
  tags?: string[];
}

export interface TemplateUpdatePayload {
  name?: string;
  description?: string | null;
  category?: TemplateCategory;
  status?: TemplateStatus;
  fields?: FormFieldDef[];
  tags?: string[];
}

export interface CategoryInfo {
  key: TemplateCategory;
  label: string;
  template_count: number;
}

/* -- Submissions ----------------------------------------------------------- */

export interface SubmissionSummary {
  id: string;
  project_id: string;
  submission_number: string;
  template_name: string;
  template_category: TemplateCategory;
  title: string | null;
  location: string | null;
  status: SubmissionStatus;
  result: FormResult;
  completed_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubmissionDetail extends SubmissionSummary {
  template_id: string | null;
  template_version: number;
  template_snapshot: FormFieldDef[];
  answers: AnswerMap;
  completed_by: string | null;
  linked_inspection_id: string | null;
  metadata: Record<string, unknown>;
}

export interface SubmissionCreatePayload {
  project_id: string;
  template_id: string;
  title?: string | null;
  location?: string | null;
  answers?: AnswerMap;
  /**
   * Free-form metadata frozen onto the submission at create time. Used to
   * record what the submission is attached to (e.g. a site issue), so the
   * link is discoverable from the submission later. The backend accepts and
   * stores this verbatim (forms.SubmissionCreate.metadata).
   */
  metadata?: Record<string, unknown>;
}

export interface SubmissionUpdatePayload {
  title?: string | null;
  location?: string | null;
  answers?: AnswerMap;
  /**
   * Metadata patch. The backend deep-merges this into the existing metadata
   * (forms.service.merge_metadata) rather than replacing it, so partial
   * updates are safe.
   */
  metadata?: Record<string, unknown>;
}

/** One validation issue returned in a 422 detail payload. */
export interface FieldIssue {
  field_index: number;
  field_key: string | null;
  code: string;
  message: string;
}

/* -- Template calls -------------------------------------------------------- */

export interface TemplateListParams {
  projectId?: string | null;
  category?: TemplateCategory | '';
  status?: TemplateStatus | '';
  q?: string;
}

export function fetchTemplates(params?: TemplateListParams): Promise<TemplateSummary[]> {
  const qs = new URLSearchParams();
  if (params?.projectId) qs.set('project_id', params.projectId);
  if (params?.category) qs.set('category', params.category);
  if (params?.status) qs.set('status', params.status);
  if (params?.q?.trim()) qs.set('q', params.q.trim());
  const suffix = qs.toString();
  return apiGet<TemplateSummary[]>(`/v1/forms/templates${suffix ? `?${suffix}` : ''}`);
}

export function fetchCategories(projectId?: string | null): Promise<CategoryInfo[]> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiGet<CategoryInfo[]>(`/v1/forms/categories${qs}`);
}

export function fetchTemplate(id: string): Promise<TemplateDetail> {
  return apiGet<TemplateDetail>(`/v1/forms/templates/${id}`);
}

export function createTemplate(payload: TemplateCreatePayload): Promise<TemplateDetail> {
  return apiPost<TemplateDetail, TemplateCreatePayload>(`/v1/forms/templates`, payload);
}

export function updateTemplate(id: string, payload: TemplateUpdatePayload): Promise<TemplateDetail> {
  return apiPatch<TemplateDetail, TemplateUpdatePayload>(`/v1/forms/templates/${id}`, payload);
}

export function duplicateTemplate(id: string): Promise<TemplateDetail> {
  return apiPost<TemplateDetail>(`/v1/forms/templates/${id}/duplicate`, {});
}

export function deleteTemplate(id: string): Promise<void> {
  return apiDelete(`/v1/forms/templates/${id}`);
}

/* -- Submission calls ------------------------------------------------------ */

export interface SubmissionListParams {
  projectId: string;
  status?: SubmissionStatus | '';
  category?: TemplateCategory | '';
  templateId?: string;
}

export function fetchSubmissions(params: SubmissionListParams): Promise<SubmissionSummary[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.projectId);
  if (params.status) qs.set('status', params.status);
  if (params.category) qs.set('category', params.category);
  if (params.templateId) qs.set('template_id', params.templateId);
  return apiGet<SubmissionSummary[]>(`/v1/forms/submissions?${qs.toString()}`);
}

export function fetchSubmission(id: string): Promise<SubmissionDetail> {
  return apiGet<SubmissionDetail>(`/v1/forms/submissions/${id}`);
}

export function createSubmission(payload: SubmissionCreatePayload): Promise<SubmissionDetail> {
  return apiPost<SubmissionDetail, SubmissionCreatePayload>(`/v1/forms/submissions`, payload);
}

export function updateSubmission(id: string, payload: SubmissionUpdatePayload): Promise<SubmissionDetail> {
  return apiPatch<SubmissionDetail, SubmissionUpdatePayload>(`/v1/forms/submissions/${id}`, payload);
}

export function completeSubmission(id: string, answers?: AnswerMap): Promise<SubmissionDetail> {
  return apiPost<SubmissionDetail>(`/v1/forms/submissions/${id}/complete`, { answers: answers ?? null });
}

export function deleteSubmission(id: string): Promise<void> {
  return apiDelete(`/v1/forms/submissions/${id}`);
}

export interface CreateInspectionResult {
  inspection_id: string;
  inspection_number?: string;
  submission_id: string;
  created: boolean;
}

export function createInspectionFromSubmission(id: string): Promise<CreateInspectionResult> {
  return apiPost<CreateInspectionResult>(`/v1/forms/submissions/${id}/create-inspection`, {});
}

/**
 * Download a completed form as a PDF. The endpoint streams a PDF (not JSON), so
 * this bypasses the JSON helpers with a raw authenticated fetch and hands the
 * blob to the shared download trigger.
 */
export async function downloadSubmissionPdf(id: string, filename: string): Promise<void> {
  const token = getAuthToken();
  const res = await fetch(`${API_BASE}/v1/forms/submissions/${id}/export/pdf`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) {
    throw new Error(`Export failed (${res.status})`);
  }
  const blob = await res.blob();
  triggerDownload(blob, filename);
}
