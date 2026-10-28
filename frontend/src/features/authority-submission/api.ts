// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Authority Submission Factory.
 *
 * All endpoints are prefixed with /v1/authority-submission/. Profiles are
 * global, jurisdiction-neutral schema definitions (generic XML, a
 * GAEB-X83-shaped tender exchange, a COBie-shaped handover register);
 * submissions are project-scoped documents built against a profile and
 * driven through the draft -> validated -> signed_pending -> submitted ->
 * accepted | rejected lifecycle.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type FormatKey =
  | 'minstroy_xml'
  | 'gaeb_x83'
  | 'cobie'
  | 'eplan'
  | 'generic_xml'
  | 'custom';

export type SubmissionStatus =
  | 'draft'
  | 'validated'
  | 'signed_pending'
  | 'submitted'
  | 'accepted'
  | 'rejected';

/** A field descriptor inside a profile's field_spec (order fixes XML element order). */
export interface FieldSpec {
  name: string;
  type: 'string' | 'integer' | 'number' | 'boolean' | 'date' | 'array' | 'object';
  required?: boolean;
  xml_tag?: string;
  label?: string;
  item_tag?: string;
  /** Nested field_spec for array-of-objects / object fields. */
  fields?: FieldSpec[];
}

export interface SubmissionProfile {
  id: string;
  name: string;
  jurisdiction: string | null;
  format_key: string;
  schema_version: string;
  root_element: string;
  field_spec: FieldSpec[];
  description: string;
  is_builtin: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface Submission {
  id: string;
  project_id: string;
  profile_id: string;
  title: string;
  payload: Record<string, unknown>;
  status: SubmissionStatus;
  generated_xml: string | null;
  validation_report: ValidationReport | null;
  submitted_at: string | null;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ValidationResultRow {
  field: string;
  ok: boolean;
  severity: string;
  message: string;
}

export interface ValidationReport {
  status: string;
  score: number;
  checked: number;
  errors: number;
  missing_required: string[];
  type_mismatches: { field: string; expected: string; got: string }[];
  results: ValidationResultRow[];
}

export interface GeneratedXml {
  submission_id: string;
  xml: string;
}

export interface RenderedSubmission {
  title: string;
  root_element: string;
  fields: { field: string; label: string; type: string; value: unknown }[];
  text: string;
}

export interface MetaOption {
  code: string;
  label: string;
}

export interface SubmissionMeta {
  format_keys: MetaOption[];
  statuses: MetaOption[];
}

export interface SubmissionFilters {
  project_id: string;
  status?: SubmissionStatus | '';
  profile_id?: string | '';
}

export interface CreateSubmissionPayload {
  project_id: string;
  profile_id: string;
  title: string;
  payload?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface UpdateSubmissionPayload {
  title?: string;
  payload?: Record<string, unknown>;
  /** Only the settable statuses accepted by the backend (see schemas.py). */
  status?: 'draft' | 'signed_pending' | 'accepted' | 'rejected';
  metadata?: Record<string, unknown>;
}

/**
 * The API may omit newer fields on older rows / partial serialisers.
 * Normalise so the UI never has to guard `undefined`.
 */
type SubmissionWire = Omit<Submission, 'payload' | 'metadata' | 'validation_report'> & {
  payload?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  validation_report?: ValidationReport | null;
};

function normaliseSubmission(s: SubmissionWire): Submission {
  return {
    ...s,
    payload: s.payload ?? {},
    metadata: s.metadata ?? {},
    validation_report: s.validation_report ?? null,
  } as Submission;
}

/* ── Meta ──────────────────────────────────────────────────────────────── */

export async function fetchSubmissionMeta(): Promise<SubmissionMeta> {
  return apiGet<SubmissionMeta>('/v1/authority-submission/meta');
}

/* ── Profiles (global, read-only from the UI) ─────────────────────────── */

export async function fetchProfiles(formatKey?: string): Promise<SubmissionProfile[]> {
  const qs = formatKey ? `?format_key=${encodeURIComponent(formatKey)}` : '';
  return apiGet<SubmissionProfile[]>(`/v1/authority-submission/profiles${qs}`);
}

export async function fetchProfile(profileId: string): Promise<SubmissionProfile> {
  return apiGet<SubmissionProfile>(`/v1/authority-submission/profiles/${profileId}/`);
}

/* ── Submissions ───────────────────────────────────────────────────────── */

export async function fetchSubmissions(filters: SubmissionFilters): Promise<Submission[]> {
  const params = new URLSearchParams();
  params.set('project_id', filters.project_id);
  if (filters.status) params.set('status', filters.status);
  if (filters.profile_id) params.set('profile_id', filters.profile_id);
  const rows = await apiGet<SubmissionWire[]>(
    `/v1/authority-submission/submissions/?${params.toString()}`,
  );
  return rows.map(normaliseSubmission);
}

export async function getSubmission(id: string): Promise<Submission> {
  const row = await apiGet<SubmissionWire>(`/v1/authority-submission/submissions/${id}/`);
  return normaliseSubmission(row);
}

export async function createSubmission(data: CreateSubmissionPayload): Promise<Submission> {
  const row = await apiPost<SubmissionWire>('/v1/authority-submission/submissions/', data);
  return normaliseSubmission(row);
}

export async function updateSubmission(
  id: string,
  data: UpdateSubmissionPayload,
): Promise<Submission> {
  const row = await apiPatch<SubmissionWire>(`/v1/authority-submission/submissions/${id}/`, data);
  return normaliseSubmission(row);
}

export async function deleteSubmission(id: string): Promise<void> {
  await apiDelete(`/v1/authority-submission/submissions/${id}/`);
}

/* ── Engine actions (validate -> generate XML -> submit) ─────────────────── */

export async function validateSubmission(id: string): Promise<ValidationReport> {
  return apiPost<ValidationReport>(`/v1/authority-submission/submissions/${id}/validate`);
}

export async function generateSubmissionXml(id: string): Promise<GeneratedXml> {
  return apiPost<GeneratedXml>(`/v1/authority-submission/submissions/${id}/generate-xml`);
}

export async function renderSubmission(id: string): Promise<RenderedSubmission> {
  return apiGet<RenderedSubmission>(`/v1/authority-submission/submissions/${id}/render`);
}

export async function submitSubmission(id: string): Promise<Submission> {
  const row = await apiPost<SubmissionWire>(`/v1/authority-submission/submissions/${id}/submit`);
  return normaliseSubmission(row);
}
