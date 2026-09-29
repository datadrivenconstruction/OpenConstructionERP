// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { apiGet, apiDelete, apiPost } from '@/shared/lib/api';
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
  diameter_mm: string;
  bars: number;
  weight_kg: number;
}

export interface RebarImport {
  id: string;
  project_id: string;
  filename: string;
  encoding: string;
  record_count: number;
  total_weight_kg: number | null;
  validation_status: string;
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
  status: string;
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

interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
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

/**
 * A project's imports, newest first.
 *
 * The backend pages this list (at most 200 per call); one page is plenty for
 * the schedules a project realistically holds, and the envelope is unwrapped
 * here so the page keeps working with a plain array.
 */
export async function fetchImports(projectId: string): Promise<RebarImport[]> {
  const page = await apiGet<Page<WireImport>>(
    `${BASE}/imports/?project_id=${encodeURIComponent(projectId)}&limit=200`,
  );
  return page.items.map(toImport);
}

export async function fetchImport(importId: string): Promise<RebarImport> {
  return toImport(await apiGet<WireImport>(`${BASE}/imports/${importId}`));
}

export async function fetchShapes(importId: string): Promise<RebarShape[]> {
  const page = await apiGet<Page<WireShape>>(`${BASE}/imports/${importId}/shapes?limit=1000`);
  return page.items.map((s) => ({ ...s, ...shapeDecimals(s) }));
}

export async function fetchCutting(importId: string): Promise<RebarCuttingEntry[]> {
  const rows = await apiGet<Wire<RebarCuttingEntry, 'weight_kg'>[]>(`${BASE}/imports/${importId}/cutting`);
  return rows.map((r) => ({ ...r, weight_kg: num(r.weight_kg) ?? 0 }));
}

export async function deleteImport(importId: string): Promise<void> {
  return apiDelete(`${BASE}/imports/${importId}`);
}

/**
 * Parse and validate an ABS file without storing it.
 *
 * The dry run takes the file's text as JSON rather than an upload; the format
 * is ASCII only, so reading it as text loses nothing a valid file can hold.
 */
export async function previewAbsFile(file: File, locale?: string): Promise<RebarPreviewResponse> {
  const content = await file.text();
  const raw = await apiPost<
    Omit<RebarPreviewResponse, 'total_weight_kg' | 'shapes'> & {
      total_weight_kg: string | number | null;
      shapes: WirePreviewShape[];
    }
  >(
    `${BASE}/preview/`,
    { content, locale },
    { timeoutMs: 90_000 },
  );
  return {
    ...raw,
    total_weight_kg: num(raw.total_weight_kg),
    shapes: raw.shapes.map((s) => ({ ...s, ...shapeDecimals(s) })),
  };
}

/**
 * Import an ABS file into a project.
 *
 * Uses raw fetch + FormData because apiPost sets Content-Type to
 * application/json, which breaks multipart uploads. The backend reads the
 * part named ``upload`` and answers with the stored record nested under
 * ``import_record``, next to the validation findings.
 */
export async function importAbsFile(
  file: File,
  projectId: string,
  locale?: string,
): Promise<RebarImportResult> {
  const token = useAuthStore.getState().accessToken;
  const form = new FormData();
  form.append('upload', file);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 90_000);

  try {
    const qs = new URLSearchParams({ project_id: projectId });
    if (locale) qs.set('locale', locale);
    const res = await fetch(`/api${BASE}/imports/?${qs.toString()}`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = typeof body?.detail === 'string' ? body.detail : 'Import failed';
      throw new Error(detail);
    }

    const result = (await res.json()) as Omit<RebarImportResult, 'import_record'> & { import_record: WireImport };
    return { ...result, import_record: toImport(result.import_record) };
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('Server did not respond within 90 seconds. The file may be too large.');
    }
    throw err;
  }
}
