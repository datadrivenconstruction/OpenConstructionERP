// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { ApiError, apiGet, apiDelete, type Page } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

// ---------------------------------------------------------------------------
// Types
//
// These mirror backend/app/modules/rebar_schedule/schemas.py. The backend's
// Decimal columns arrive as JSON strings, so the fetchers below turn them into
// numbers once, here, and the page only ever sees numbers or null.
// ---------------------------------------------------------------------------

export interface RebarShape {
  id: string;
  line_no: number;
  super_group: string;
  drawing_ref: string | null;
  position: string | null;
  length_mm: number | null;
  quantity: number | null;
  weight_kg: number | null;
  diameter_mm: number | null;
  steel_grade: string | null;
  checksum_ok: boolean;
}

export interface RebarCuttingEntry {
  diameter_mm: number | null;
  bars: number;
  weight_kg: number;
}

/** passed, info, warnings or errors: what the bvbs_abs rule set made of a file. */
export type AbsValidationStatus = 'passed' | 'info' | 'warnings' | 'errors';

export interface RebarImport {
  id: string;
  project_id: string;
  filename: string;
  encoding: string;
  record_count: number;
  total_weight_kg: number | null;
  validation_status: AbsValidationStatus;
  error_count: number;
  warning_count: number;
  created_at: string | null;
}

export interface AbsFinding {
  rule_id: string;
  rule_name: string;
  severity: string;
  message: string;
  element_ref: string | null;
}

export interface AbsValidationSummary {
  status: AbsValidationStatus;
  error_count: number;
  warning_count: number;
  info_count: number;
  findings: AbsFinding[];
}

export interface RebarPreviewResponse {
  record_count: number;
  encoding: string;
  total_weight_kg: number | null;
  /** Preview shapes are not stored yet, so they have no id; line_no is unique. */
  shapes: Omit<RebarShape, 'id'>[];
  validation: AbsValidationSummary;
}

export interface RebarImportResult {
  import_record: RebarImport;
  validation: AbsValidationSummary;
  /** The same bytes were already imported into this project. */
  duplicate: boolean;
}

/** A model as it travels: the named Decimal columns are strings on the wire. */
type Wire<T, K extends keyof T> = Omit<T, K> & { [P in K]: string | number | null };

type ShapeDecimals = 'length_mm' | 'weight_kg' | 'diameter_mm';
type WireImport = Wire<RebarImport, 'total_weight_kg'>;
type WireShape = Wire<RebarShape, ShapeDecimals>;
type WirePreviewShape = Wire<Omit<RebarShape, 'id'>, ShapeDecimals>;

function num(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function toImport(raw: WireImport): RebarImport {
  return { ...raw, total_weight_kg: num(raw.total_weight_kg) };
}

function shapeDecimals(raw: WirePreviewShape): Pick<RebarShape, ShapeDecimals> {
  return {
    length_mm: num(raw.length_mm),
    weight_kg: num(raw.weight_kg),
    diameter_mm: num(raw.diameter_mm),
  };
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

const BASE = '/v1/rebar-schedule';

/** The most the list routes hand out in one page (``le=200`` / ``le=1000`` on the router). */
export const IMPORTS_PAGE_LIMIT = 200;
export const SHAPES_PAGE_LIMIT = 1000;

/**
 * A project's imports, newest first, as the page the backend returned.
 *
 * The page keeps ``total`` so the screen can say when it shows fewer imports
 * than the project holds (see ``isTruncated``).
 */
export async function fetchImports(projectId: string): Promise<Page<RebarImport>> {
  const page = await apiGet<Page<WireImport>>(
    `${BASE}/imports/?project_id=${encodeURIComponent(projectId)}&limit=${IMPORTS_PAGE_LIMIT}`,
  );
  return { ...page, items: page.items.map(toImport) };
}

export async function fetchImport(importId: string): Promise<RebarImport> {
  return toImport(await apiGet<WireImport>(`${BASE}/imports/${importId}`));
}

export async function fetchShapes(importId: string): Promise<Page<RebarShape>> {
  const page = await apiGet<Page<WireShape>>(`${BASE}/imports/${importId}/shapes?limit=${SHAPES_PAGE_LIMIT}`);
  return { ...page, items: page.items.map((s) => ({ ...s, ...shapeDecimals(s) })) };
}

export async function fetchCutting(importId: string): Promise<RebarCuttingEntry[]> {
  // diameter_mm is str(Decimal) off a Numeric(8,2) column, so '12.00'.
  const rows = await apiGet<Wire<RebarCuttingEntry, 'diameter_mm' | 'weight_kg'>[]>(
    `${BASE}/imports/${importId}/cutting`,
  );
  return rows.map((r) => ({ ...r, diameter_mm: num(r.diameter_mm), weight_kg: num(r.weight_kg) ?? 0 }));
}

export async function deleteImport(importId: string): Promise<void> {
  return apiDelete(`${BASE}/imports/${importId}`);
}

/**
 * POST an ABS file as the multipart part ``upload``.
 *
 * Raw fetch + FormData, because apiPost sets Content-Type to application/json,
 * which breaks multipart uploads. It still behaves like the shared client
 * where it matters: a 401 gets one silent token refresh, and a failure throws
 * ``ApiError`` so ``getErrorMessage`` words it the same way as everywhere else.
 * A timeout throws an ``AbortError``, which ``getErrorMessage`` also words.
 */
async function postAbsUpload<T>(path: string, file: File, params: URLSearchParams, retried = false): Promise<T> {
  const token = useAuthStore.getState().accessToken;
  const form = new FormData();
  form.append('upload', file);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 90_000);
  let res: Response;
  try {
    const qs = params.toString();
    res = await fetch(`/api${BASE}${path}${qs ? `?${qs}` : ''}`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }

  if (res.status === 401 && !retried) {
    const fresh = await useAuthStore.getState().refreshAccessToken();
    if (fresh) return postAbsUpload<T>(path, file, params, true);
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let body: unknown = text;
    try {
      body = JSON.parse(text);
    } catch {
      // A plain-text body is still something ApiError can word.
    }
    throw new ApiError(res.status, res.statusText, body);
  }
  return (await res.json()) as T;
}

type WirePreview = Omit<RebarPreviewResponse, 'total_weight_kg' | 'shapes'> & {
  total_weight_kg: string | number | null;
  shapes: WirePreviewShape[];
};

/**
 * Parse and validate an ABS file without storing it.
 *
 * The file goes up as bytes, to the same decoder the import uses. Decoding it
 * in the browser read it as UTF-8, which turned each cp1252 umlaut a German
 * CAD system writes into a replacement character and broke the checksum of
 * every record holding one, so the preview reported errors the import did not.
 */
export async function previewAbsFile(file: File, locale?: string): Promise<RebarPreviewResponse> {
  const params = new URLSearchParams();
  if (locale) params.set('locale', locale);
  const raw = await postAbsUpload<WirePreview>('/preview/file/', file, params);
  return {
    ...raw,
    total_weight_kg: num(raw.total_weight_kg),
    shapes: raw.shapes.map((s) => ({ ...s, ...shapeDecimals(s) })),
  };
}

/**
 * Import an ABS file into a project.
 *
 * The backend answers with the stored record nested under ``import_record``,
 * next to the validation findings, and sets ``duplicate`` when these bytes
 * were already imported into the project.
 */
export async function importAbsFile(file: File, projectId: string, locale?: string): Promise<RebarImportResult> {
  const params = new URLSearchParams({ project_id: projectId });
  if (locale) params.set('locale', locale);
  const result = await postAbsUpload<Omit<RebarImportResult, 'import_record'> & { import_record: WireImport }>(
    '/imports/',
    file,
    params,
  );
  return { ...result, import_record: toImport(result.import_record) };
}
