// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Spreadsheet (Excel / CSV) schedule import: types and calls.
 *
 * Three endpoints under the schedule module:
 *   - POST …/import/spreadsheet/preview/  reads the file, writes nothing;
 *   - POST …/import/spreadsheet/commit/   re-reads the same bytes (the preview's
 *     SHA-256 must match) and writes a new schedule or replaces a draft;
 *   - GET  …/import/spreadsheet/template/ an empty template in one language.
 *
 * Uploads are multipart, so these go through `fetchWithAuth` rather than the
 * JSON helpers; a refusal is thrown as an `ApiError` whose body keeps the
 * backend's `detail.code`, which the dialog branches on.
 */
import { API_BASE, ApiError, downloadWithAuth, fetchWithAuth } from '@/shared/lib/api';

const BASE = `${API_BASE}/v1/schedule/schedule/import/spreadsheet`;

/** Fields a column can be read as, in the order the mapping table lists them. */
export const IMPORT_FIELDS = [
  'id',
  'name',
  'wbs',
  'outline_level',
  'start',
  'finish',
  'duration',
  'predecessors',
  'percent_complete',
  'milestone',
  'resource',
  'notes',
  'client_visible',
] as const;
export type ImportField = (typeof IMPORT_FIELDS)[number];

/** Languages the backend writes a template in (and reads headers in). */
export const TEMPLATE_LANGUAGES = ['en', 'de', 'es', 'fr', 'ru', 'pt', 'it', 'nl', 'pl', 'tr'] as const;
export type TemplateLanguage = (typeof TEMPLATE_LANGUAGES)[number];
export type TemplateFormat = 'xlsx' | 'csv';

export type DateOrder = 'dmy' | 'mdy';
export type IssueSeverity = 'error' | 'warning' | 'info';

/** One problem the importer found, keyed to the sheet row (1-based) and column (0-based). */
export interface ImportIssue {
  code: string;
  severity: IssueSeverity;
  row: number | null;
  column: number | null;
  message: string;
  params: Record<string, unknown>;
}

export interface ImportColumn {
  index: number;
  header: string;
  field: string | null;
  confidence: number;
  tier: 'exact' | 'synonym' | 'fuzzy' | 'override' | 'none';
}

/** An activity of the parsed interchange document, reduced to what the dialog shows. */
export interface ImportActivity {
  ref: string;
  activity_code: string | null;
  name: string;
  start_date: string;
  end_date: string;
  duration_days: number;
  activity_type: string;
  client_visible: boolean;
  metadata?: { import_row?: number };
}

export interface ImportDocument {
  schedule: { name: string; start_date: string | null; end_date: string | null };
  activities: ImportActivity[];
  relationships: unknown[];
}

export interface TabularPreview {
  sha256: string;
  filename: string;
  file_format: 'xlsx' | 'xls' | 'csv' | null;
  encoding: string | null;
  delimiter: string | null;
  sheet: string | null;
  header_row: number | null;
  columns: ImportColumn[];
  mapping: Record<string, number>;
  date_order: DateOrder | null;
  date_order_source: 'explicit' | 'values' | 'suggested' | null;
  outline_source: string | null;
  row_count: number;
  activity_count: number;
  relationship_count: number;
  has_errors: boolean;
  sample_rows: { row: number; values: string[]; cells: Record<string, string> }[];
  issues: ImportIssue[];
  /** Refs the sheet marks for the client. A suggestion: only a confirmed list is applied. */
  client_visible_suggested: string[];
  document: ImportDocument | null;
  /** Schedules of the project already imported from these exact bytes. */
  duplicate_of: string[];
}

export interface ValidationFinding {
  rule_id: string;
  severity: string;
  message: string;
  element_ref: string | null;
  row: number | null;
  suggestion: string | null;
}

export interface TabularCommitResult {
  schedule_id: string;
  schedule_name: string;
  replaced: boolean;
  activity_count: number;
  relationship_count: number;
  critical_count: number;
  project_duration_days: number;
  validation: {
    rule_sets: string[];
    errors: number;
    warnings: number;
    infos: number;
    findings: ValidationFinding[];
  };
  warnings: ImportIssue[];
}

export interface PreviewRequest {
  projectId: string;
  file: File;
  /** Only the columns changed from the importer's own reading, JSON encoded. */
  columnMapping?: string | null;
  dateOrder?: DateOrder | null;
}

export interface CommitRequest extends PreviewRequest {
  expectedSha256: string;
  target: 'new' | 'replace';
  scheduleId?: string | null;
  name?: string | null;
  allowDuplicate?: boolean;
  /** Refs the person confirmed as visible to the client. Nothing else becomes visible. */
  clientVisibleRefs: string[];
}

/** The `detail` object of a refusal: a stable code plus whatever the code carries. */
export interface ImportErrorDetail {
  code: string;
  message: string;
  issues?: ImportIssue[];
  schedule_ids?: string[];
  refs?: string[];
  [extra: string]: unknown;
}

function previewForm(req: PreviewRequest): FormData {
  const form = new FormData();
  form.append('project_id', req.projectId);
  form.append('file', req.file, req.file.name);
  if (req.columnMapping) form.append('column_mapping', req.columnMapping);
  if (req.dateOrder) form.append('date_order', req.dateOrder);
  return form;
}

async function postForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetchWithAuth(`${BASE}/${path}/`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body: form,
  });
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = undefined;
    }
    throw new ApiError(response.status, response.statusText, body);
  }
  return (await response.json()) as T;
}

export function previewSpreadsheet(req: PreviewRequest): Promise<TabularPreview> {
  return postForm<TabularPreview>('preview', previewForm(req));
}

export function commitSpreadsheet(req: CommitRequest): Promise<TabularCommitResult> {
  const form = previewForm(req);
  form.append('expected_sha256', req.expectedSha256);
  form.append('target', req.target);
  if (req.target === 'replace' && req.scheduleId) form.append('schedule_id', req.scheduleId);
  if (req.name && req.name.trim()) form.append('name', req.name.trim());
  if (req.allowDuplicate) form.append('allow_duplicate', 'true');
  form.append('client_visible_refs', JSON.stringify(req.clientVisibleRefs));
  return postForm<TabularCommitResult>('commit', form);
}

export function downloadTemplate(lang: TemplateLanguage, format: TemplateFormat): Promise<void> {
  const qs = new URLSearchParams({ lang, format });
  return downloadWithAuth(`${BASE}/template/?${qs.toString()}`, `schedule_template_${lang}.${format}`);
}

/** The backend's `detail` object of a refused call, or `null` when it carries none. */
export function importErrorDetail(err: unknown): ImportErrorDetail | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | undefined;
  const detail = body?.detail;
  if (detail && typeof detail === 'object' && typeof (detail as { code?: unknown }).code === 'string') {
    return detail as ImportErrorDetail;
  }
  return null;
}

/** The template language closest to the interface language, English when none fits. */
export function templateLanguageFor(uiLanguage: string | undefined): TemplateLanguage {
  const base = (uiLanguage ?? 'en').toLowerCase().split(/[-_]/)[0] ?? 'en';
  return (TEMPLATE_LANGUAGES as readonly string[]).includes(base) ? (base as TemplateLanguage) : 'en';
}

/**
 * Issue params as interpolation values: lists joined, numbers kept (so `count`
 * picks the plural form), everything else as text. `field` names are passed
 * through `fieldLabel` so the sentence reads the translated column name
 * rather than the internal one.
 */
export function issueParams(
  params: Record<string, unknown>,
  fieldLabel: (field: string) => string,
): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    if (typeof value === 'number') out[key] = value;
    else if (key === 'field' && typeof value === 'string') out[key] = fieldLabel(value);
    else if (key === 'cycle' && Array.isArray(value)) out[key] = value.map(String).join(' → ');
    else if (Array.isArray(value)) out[key] = value.map(String).join(', ');
    else if (typeof value === 'object') out[key] = Object.entries(value as Record<string, unknown>).map(([k, v]) => `${k}: ${String(v)}`).join(', ');
    else out[key] = String(value);
  }
  return out;
}

/** The importer's own reading of each column, keyed by column index, `''` for none. */
export function readMapping(columns: ImportColumn[]): Record<string, string> {
  const read: Record<string, string> = {};
  for (const column of columns) read[String(column.index)] = column.field ?? '';
  return read;
}
