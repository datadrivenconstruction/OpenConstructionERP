// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Submittals.
 *
 * All endpoints are prefixed with /v1/submittals/.
 */

import { apiGet, apiPost, apiPatch, downloadWithAuth } from '@/shared/lib/api';
import { documentExportUrl, downloadRecordPdf, type DocumentFormat } from '@/shared/lib/documentExport';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type SubmittalStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'approved'
  | 'approved_as_noted'
  | 'revise_and_resubmit'
  | 'rejected'
  | 'closed';

// The one list. It mirrors SUBMITTAL_TYPES in the backend schema and is held
// against it by test_module_vocabularies_close_across_layers.py. The union is
// derived rather than written out again, so a Record keyed by SubmittalType
// stops compiling until every picker has learned a newly added type.
export const SUBMITTAL_TYPES = [
  'shop_drawing',
  'product_data',
  'sample',
  'mock_up',
  'test_report',
  'calculation',
  'method_statement',
  'certificate',
  'warranty',
] as const;

export type SubmittalType = (typeof SUBMITTAL_TYPES)[number];

/** The four decisions a reviewer records (the `status` of a review request). */
export type ReviewOutcome = 'approved' | 'approved_as_noted' | 'revise_and_resubmit' | 'rejected';

/**
 * One finished review cycle, as the server keeps it in `review_history`.
 *
 * A revision is revised in place: resubmitting raises the revision number and
 * overwrites the dates, so this entry is what is left of the revision that was
 * replaced and is the link from a resubmission back to it.
 */
export interface ReviewHistoryEntry {
  revision: number;
  outcome: string;
  /** The mark as the reviewer stamped it; the default letter when none was typed. */
  code: string | null;
  date_submitted: string | null;
  date_returned: string | null;
  reviewer_id: string | null;
  notes: string | null;
  resubmit_for_record: boolean;
}

/**
 * The register columns of a submittal. Every one is absent on a row written
 * before they existed, which is what {@link LEGACY_REGISTER_FIELDS} spells out.
 *
 * The figures in the second half are derived by the server as of today. `null`
 * there means "cannot be said from what is recorded" (no review period, no
 * lead time), never zero, and the screen never works them out from the dates.
 */
export interface SubmittalRegisterFields {
  /** Lower-case code; the default list comes from the vocabulary route. */
  discipline: string | null;
  manufacturer: string | null;
  model_reference: string | null;
  /** ISO 3166-1 alpha-2, upper case. */
  country_of_origin: string | null;
  /** A contact id or a typed name; show `supplier_name`, send `supplier`. */
  supplier: string | null;
  supplier_name: string | null;
  /** Calendar days the contract gives the reviewer; unset means unknown. */
  review_period_days: number | null;
  required_on_site_date: string | null;
  long_lead: boolean;
  lead_time_weeks: number | null;
  linked_drawing_ids: string[];
  date_returned: string | null;
  review_history: ReviewHistoryEntry[];
  /** The decision on the current revision; survives `closed`. */
  review_outcome: string | null;
  /** The mark for that decision, as stamped ("B", "2"). */
  review_code: string | null;
  /** True for approved and approved as noted: ordering may go ahead. */
  may_proceed: boolean;
  /** Approved as noted with a corrected copy still owed for the record. */
  resubmit_for_record: boolean;
  days_in_review: number | null;
  review_due_date: string | null;
  /** 0 = inside the review period; null = no period recorded or already returned. */
  review_overdue_days: number | null;
  approval_needed_by: string | null;
  /** 0 = not late; null = no needed-by date or already approved. */
  approval_late_days: number | null;
  submit_by_date: string | null;
}

/** What a row from before the register columns carries: nothing. */
export const LEGACY_REGISTER_FIELDS: SubmittalRegisterFields = {
  discipline: null,
  manufacturer: null,
  model_reference: null,
  country_of_origin: null,
  supplier: null,
  supplier_name: null,
  review_period_days: null,
  required_on_site_date: null,
  long_lead: false,
  lead_time_weeks: null,
  linked_drawing_ids: [],
  date_returned: null,
  review_history: [],
  review_outcome: null,
  review_code: null,
  may_proceed: false,
  resubmit_for_record: false,
  days_in_review: null,
  review_due_date: null,
  review_overdue_days: null,
  approval_needed_by: null,
  approval_late_days: null,
  submit_by_date: null,
};

export interface Submittal extends SubmittalRegisterFields {
  id: string;
  project_id: string;
  submittal_number: string;
  title: string;
  spec_section: string | null;
  type: SubmittalType;
  status: SubmittalStatus;
  ball_in_court: string | null;
  ball_in_court_name: string | null;
  revision: number;
  date_submitted: string | null;
  date_required: string | null;
  description: string | null;
  review_notes: string | null;
  /** BOQ position ids this submittal covers (deep-linked from the detail row). */
  linked_boq_item_ids: string[];
  /** Flexible blob; carries the source CDE container id when created from CDE. */
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * What the list can be narrowed and ordered by. Every member is a query
 * parameter of `GET /v1/submittals/` and is named as the route names it.
 * The toggles are only ever sent as `true`: "not long lead" is not a question
 * the register is asked.
 */
export interface SubmittalFilters {
  project_id?: string;
  status?: SubmittalStatus | '';
  type?: string;
  discipline?: string;
  outcome?: string;
  long_lead?: boolean;
  review_overdue?: boolean;
  approval_late?: boolean;
  /** One of the vocabulary's `sort_fields`; an unknown one is a 422. */
  sort?: string;
  order?: 'asc' | 'desc';
}

/** The filters the register export takes: the list's, minus the ordering. */
export type SubmittalExportFilters = Omit<SubmittalFilters, 'project_id' | 'sort' | 'order'>;

/** The register columns as a create or an edit sends them. */
interface RegisterFieldsPayload {
  discipline?: string | null;
  manufacturer?: string | null;
  model_reference?: string | null;
  country_of_origin?: string | null;
  supplier?: string | null;
  review_period_days?: number | null;
  required_on_site_date?: string | null;
  long_lead?: boolean;
  lead_time_weeks?: number | null;
}

export interface CreateSubmittalPayload extends RegisterFieldsPayload {
  project_id: string;
  title: string;
  description?: string;
  spec_section?: string;
  submittal_type: SubmittalType;
  date_required?: string;
  /** Optional blob persisted as-is; used to record the source CDE container. */
  metadata?: Record<string, unknown>;
}

/**
 * A partial edit. On the register columns `null` clears the value; an empty
 * string would be refused by the patterns on the dates and the numbers.
 */
export interface UpdateSubmittalPayload extends RegisterFieldsPayload {
  title?: string;
  description?: string;
  spec_section?: string;
  submittal_type?: SubmittalType;
  /**
   * `null` clears the date. It cannot be cleared with an empty string: the
   * backend field is `str | None` behind a `^\d{4}-\d{2}-\d{2}$` pattern, so
   * `''` is rejected with a 422 rather than treated as "no date".
   */
  date_required?: string | null;
}

export interface ReviewSubmittalPayload {
  status: ReviewOutcome;
  notes?: string;
  /** The mark as stamped; left out, the server records the default letter. */
  code?: string;
  /** Only meaningful with `approved_as_noted`. */
  resubmit_for_record?: boolean;
}

/**
 * The review-modal decision shape. ``approved`` is routed to the
 * ``/approve/`` endpoint (final approval, MANAGER-gated, rate-limited);
 * every other decision is routed to ``/review/`` with the notes persisted.
 */
export interface ApproveSubmittalPayload {
  status: ReviewOutcome;
  comments?: string;
  code?: string;
  resubmit_for_record?: boolean;
}

/* ── Register header and vocabularies ──────────────────────────────────── */

export interface SubmittalCodeCount {
  code: string;
  count: number;
}

export interface SubmittalOutcomeCount extends SubmittalCodeCount {
  /** The default stamp letter for the outcome. */
  review_code: string | null;
}

/** The counts above a project's register, as of `as_of` (GET /summary/). */
export interface SubmittalRegisterSummary {
  project_id: string;
  as_of: string;
  total: number;
  by_status: SubmittalCodeCount[];
  by_type: SubmittalCodeCount[];
  /** Rows with no discipline are counted under the empty code "". */
  by_discipline: SubmittalCodeCount[];
  by_outcome: SubmittalOutcomeCount[];
  awaiting_review: number;
  /** Past the review period. Never overlaps `review_period_unknown`. */
  review_overdue: number;
  review_period_unknown: number;
  long_lead: number;
  long_lead_awaiting_approval: number;
  approval_late: number;
  long_lead_without_lead_time: number;
}

export interface SubmittalVocabularyEntry {
  code: string;
  label: string;
  short_code: string | null;
}

/** The codes the pickers offer, labelled in one language (GET /vocabulary/). */
export interface SubmittalVocabulary {
  locale: string;
  types: SubmittalVocabularyEntry[];
  disciplines: SubmittalVocabularyEntry[];
  outcomes: SubmittalVocabularyEntry[];
  sort_fields: string[];
}

export type ValidationSeverity = 'error' | 'warning' | 'info';

/** One rule's verdict on a submittal. The message arrives translated. */
export interface SubmittalValidationResult {
  rule_id: string;
  severity: ValidationSeverity;
  passed: boolean;
  message: string;
  suggestion: string | null;
}

/* ── Wire <-> UI normaliser ────────────────────────────────────────────── */

type SubmittalWire = Omit<
  Submittal,
  'type' | 'revision' | 'linked_boq_item_ids' | 'metadata' | keyof SubmittalRegisterFields
> & {
  type?: SubmittalType;
  submittal_type?: SubmittalType;
  revision?: number;
  current_revision?: number;
  description?: string | null;
  review_notes?: string | null;
  ball_in_court_name?: string | null;
  linked_boq_item_ids?: string[] | null;
  metadata?: Record<string, unknown> | null;
} & {
  // An older server, and every row from before these columns, leaves them out.
  [K in Exclude<keyof SubmittalRegisterFields, 'review_history'>]?: SubmittalRegisterFields[K] | null;
} & {
  review_history?: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function textOrNull(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null;
}

function countOf(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/** `review_history` is a JSON column, so each entry is read field by field. */
function normaliseHistory(raw: unknown): ReviewHistoryEntry[] {
  if (!Array.isArray(raw)) return [];
  const entries: unknown[] = raw;
  return entries.filter(isRecord).map((entry) => ({
    revision: countOf(entry.revision),
    outcome: textOrNull(entry.outcome) ?? '',
    code: textOrNull(entry.code),
    date_submitted: textOrNull(entry.date_submitted),
    date_returned: textOrNull(entry.date_returned),
    reviewer_id: textOrNull(entry.reviewer_id),
    notes: textOrNull(entry.notes),
    resubmit_for_record: entry.resubmit_for_record === true,
  }));
}

function normaliseSubmittal(s: SubmittalWire): Submittal {
  const type = (s.type ?? s.submittal_type ?? 'shop_drawing') as SubmittalType;
  const revision = (s.revision ?? s.current_revision ?? 1) as number;
  return {
    ...s,
    type,
    revision,
    spec_section: s.spec_section ?? null,
    description: s.description ?? null,
    review_notes: s.review_notes ?? null,
    ball_in_court_name: s.ball_in_court_name ?? null,
    linked_boq_item_ids: s.linked_boq_item_ids ?? [],
    metadata: s.metadata ?? {},
    discipline: s.discipline ?? null,
    manufacturer: s.manufacturer ?? null,
    model_reference: s.model_reference ?? null,
    country_of_origin: s.country_of_origin ?? null,
    supplier: s.supplier ?? null,
    supplier_name: s.supplier_name ?? null,
    review_period_days: s.review_period_days ?? null,
    required_on_site_date: s.required_on_site_date ?? null,
    long_lead: s.long_lead === true,
    lead_time_weeks: s.lead_time_weeks ?? null,
    linked_drawing_ids: s.linked_drawing_ids ?? [],
    date_returned: s.date_returned ?? null,
    review_history: normaliseHistory(s.review_history),
    review_outcome: s.review_outcome ?? null,
    review_code: s.review_code ?? null,
    may_proceed: s.may_proceed === true,
    resubmit_for_record: s.resubmit_for_record === true,
    days_in_review: s.days_in_review ?? null,
    review_due_date: s.review_due_date ?? null,
    review_overdue_days: s.review_overdue_days ?? null,
    approval_needed_by: s.approval_needed_by ?? null,
    approval_late_days: s.approval_late_days ?? null,
    submit_by_date: s.submit_by_date ?? null,
  };
}

function normaliseCounts(raw: unknown): SubmittalCodeCount[] {
  if (!Array.isArray(raw)) return [];
  const rows: unknown[] = raw;
  return rows
    .filter(isRecord)
    .filter((row) => typeof row.code === 'string')
    .map((row) => ({ code: String(row.code), count: countOf(row.count) }));
}

function normaliseEntries(raw: unknown): SubmittalVocabularyEntry[] {
  if (!Array.isArray(raw)) return [];
  const rows: unknown[] = raw;
  return rows
    .filter(isRecord)
    .filter((row) => typeof row.code === 'string' && row.code !== '')
    .map((row) => ({
      code: String(row.code),
      label: textOrNull(row.label) ?? String(row.code),
      short_code: textOrNull(row.short_code),
    }));
}

/* ── API Functions ─────────────────────────────────────────────────────── */

// The route caps a page at 100 rows (`le=100`). The register is read whole, a
// page at a time, so the counts above it and the rows under it describe the
// same set and the search covers every record. The page cap only keeps a
// runaway project from loading without bound.
const LIST_PAGE_SIZE = 100;
const LIST_MAX_PAGES = 50;

function listQuery(filters: SubmittalFilters | undefined, offset: number): string {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.type) params.set('type', filters.type);
  if (filters?.discipline) params.set('discipline', filters.discipline);
  if (filters?.outcome) params.set('outcome', filters.outcome);
  if (filters?.long_lead) params.set('long_lead', 'true');
  if (filters?.review_overdue) params.set('review_overdue', 'true');
  if (filters?.approval_late) params.set('approval_late', 'true');
  if (filters?.sort) {
    params.set('sort', filters.sort);
    params.set('order', filters.order ?? 'desc');
  }
  params.set('limit', String(LIST_PAGE_SIZE));
  if (offset > 0) params.set('offset', String(offset));
  return params.toString();
}

export async function fetchSubmittals(filters?: SubmittalFilters): Promise<Submittal[]> {
  const rows: Submittal[] = [];
  for (let page = 0; page < LIST_MAX_PAGES; page += 1) {
    const batch = await apiGet<SubmittalWire[]>(`/v1/submittals/?${listQuery(filters, page * LIST_PAGE_SIZE)}`);
    if (!Array.isArray(batch)) break;
    rows.push(...batch.map(normaliseSubmittal));
    if (batch.length < LIST_PAGE_SIZE) break;
  }
  return rows;
}

/**
 * The counts above a project's register (GET /summary/).
 *
 * @returns `null` when the answer is not a summary, so the caller can fall
 *   back to counting the rows it holds instead of printing zeros as fact.
 */
export async function fetchSubmittalSummary(projectId: string): Promise<SubmittalRegisterSummary | null> {
  const raw = await apiGet<unknown>(`/v1/submittals/summary/?project_id=${encodeURIComponent(projectId)}`);
  if (!isRecord(raw)) return null;
  const { total, by_outcome: outcomes } = raw;
  if (typeof total !== 'number' || !Array.isArray(outcomes)) return null;
  const outcomeRows: unknown[] = outcomes;
  return {
    project_id: String(raw.project_id ?? projectId),
    as_of: textOrNull(raw.as_of) ?? '',
    total,
    by_status: normaliseCounts(raw.by_status),
    by_type: normaliseCounts(raw.by_type),
    by_discipline: normaliseCounts(raw.by_discipline),
    by_outcome: outcomeRows
      .filter(isRecord)
      .filter((row) => typeof row.code === 'string')
      .map((row) => ({
        code: String(row.code),
        count: countOf(row.count),
        review_code: textOrNull(row.review_code),
      })),
    awaiting_review: countOf(raw.awaiting_review),
    review_overdue: countOf(raw.review_overdue),
    review_period_unknown: countOf(raw.review_period_unknown),
    long_lead: countOf(raw.long_lead),
    long_lead_awaiting_approval: countOf(raw.long_lead_awaiting_approval),
    approval_late: countOf(raw.approval_late),
    long_lead_without_lead_time: countOf(raw.long_lead_without_lead_time),
  };
}

/**
 * The codes the pickers offer, labelled in `locale` (GET /vocabulary/).
 * English and Turkish labels exist; any other language reads the English.
 *
 * @returns `null` when the answer is not a vocabulary.
 */
export async function fetchSubmittalVocabulary(locale: string): Promise<SubmittalVocabulary | null> {
  const raw = await apiGet<unknown>(`/v1/submittals/vocabulary/?locale=${encodeURIComponent(locale)}`);
  if (!isRecord(raw) || !Array.isArray(raw.disciplines) || !Array.isArray(raw.outcomes)) return null;
  const sortFields: unknown[] = Array.isArray(raw.sort_fields) ? raw.sort_fields : [];
  return {
    locale: textOrNull(raw.locale) ?? locale,
    types: normaliseEntries(raw.types),
    disciplines: normaliseEntries(raw.disciplines),
    outcomes: normaliseEntries(raw.outcomes),
    sort_fields: sortFields.filter((field): field is string => typeof field === 'string'),
  };
}

/**
 * What the `submittal` rule set finds on one submittal (GET /{id}/validate/).
 * Read-only: it changes nothing and refuses nothing.
 *
 * @returns Only the rules that did not pass, errors first as the server lists them.
 */
export async function fetchSubmittalFindings(id: string): Promise<SubmittalValidationResult[]> {
  const raw = await apiGet<unknown>(`/v1/submittals/${encodeURIComponent(id)}/validate/`);
  if (!isRecord(raw) || !Array.isArray(raw.results)) return [];
  const results: unknown[] = raw.results;
  return results
    .filter(isRecord)
    .filter((row) => row.passed === false && typeof row.message === 'string')
    .map((row) => {
      const severity: ValidationSeverity =
        row.severity === 'error' ? 'error' : row.severity === 'info' ? 'info' : 'warning';
      return {
        rule_id: String(row.rule_id ?? ''),
        severity,
        passed: false,
        message: String(row.message),
        suggestion: textOrNull(row.suggestion),
      };
    });
}

export async function createSubmittal(data: CreateSubmittalPayload): Promise<Submittal> {
  const row = await apiPost<SubmittalWire>('/v1/submittals/', data);
  return normaliseSubmittal(row);
}

export async function updateSubmittal(id: string, data: UpdateSubmittalPayload): Promise<Submittal> {
  const row = await apiPatch<SubmittalWire, UpdateSubmittalPayload>(`/v1/submittals/${id}`, data);
  return normaliseSubmittal(row);
}

export async function submitSubmittal(id: string): Promise<Submittal> {
  const row = await apiPost<SubmittalWire>(`/v1/submittals/${id}/submit/`);
  return normaliseSubmittal(row);
}

export async function reviewSubmittal(id: string, data: ReviewSubmittalPayload): Promise<Submittal> {
  const row = await apiPost<SubmittalWire>(`/v1/submittals/${id}/review/`, data);
  return normaliseSubmittal(row);
}

/**
 * Final approval. The backend ``/approve/`` endpoint is MANAGER-gated and
 * rate-limited and unconditionally forces ``status='approved'``. It accepts
 * an optional body carrying the approver's ``notes`` so comments entered in
 * the approve modal are persisted (into metadata.review_notes) instead of
 * being silently dropped, and the ``code`` the approver stamped. Non-approve
 * decisions (reject / revise / approve-as-noted) must go through
 * {@link reviewSubmittal}.
 */
export async function approveSubmittal(id: string, notes?: string, code?: string): Promise<Submittal> {
  const body: { notes?: string; code?: string } = {};
  if (notes) body.notes = notes;
  if (code) body.code = code;
  const row = await apiPost<SubmittalWire, { notes?: string; code?: string }>(`/v1/submittals/${id}/approve/`, body);
  return normaliseSubmittal(row);
}

/**
 * Submit a review decision from the review modal. Routes ``approved`` to
 * the final-approval endpoint and every other decision to ``/review/`` so
 * Reject / Revise / Approve-as-Noted are persisted faithfully (and never
 * silently become ``approved``). Comments are forwarded as ``notes``.
 */
export async function submitReviewDecision(
  id: string,
  data: ApproveSubmittalPayload,
): Promise<Submittal> {
  if (data.status === 'approved') {
    return approveSubmittal(id, data.comments, data.code);
  }
  const body: ReviewSubmittalPayload = { status: data.status, notes: data.comments };
  if (data.code) body.code = data.code;
  if (data.status === 'approved_as_noted' && data.resubmit_for_record) body.resubmit_for_record = true;
  return reviewSubmittal(id, body);
}

/* ── Printed documents ─────────────────────────────────────────────────── */

/**
 * Download the submittal register of a project (GET /export/, trailing slash
 * as the route declares it).
 *
 * The route takes the filters the list takes. Without any the register is
 * exported whole; with `type` the document is titled and named as that type's
 * register (shop drawings, material approvals, method statements), and every
 * filter used is printed in its header.
 */
export function downloadSubmittalRegister(
  projectId: string,
  format: DocumentFormat,
  locale: string,
  filters: SubmittalExportFilters = {},
): Promise<void> {
  const url = documentExportUrl('/v1/submittals/export/', {
    project_id: projectId,
    format,
    locale,
    status: filters.status || undefined,
    type: filters.type || undefined,
    discipline: filters.discipline || undefined,
    outcome: filters.outcome || undefined,
    long_lead: filters.long_lead ? 'true' : undefined,
    review_overdue: filters.review_overdue ? 'true' : undefined,
    approval_late: filters.approval_late ? 'true' : undefined,
  });
  return downloadWithAuth(url, `submittal-register.${format}`);
}

/** Download the printable form of one submittal (GET /{id}/export/pdf/). */
export function downloadSubmittalPdf(id: string, locale: string, submittalNumber?: string): Promise<void> {
  return downloadRecordPdf(
    `/v1/submittals/${encodeURIComponent(id)}/export/pdf/`,
    locale,
    submittalNumber || 'submittal',
  );
}
