// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client for the regional price-list import (prezzario regionale).
 *
 * A regional list runs to tens of thousands of items, longer to read than a
 * request may last, so the upload is stored once and the preview and the import
 * each run as a server job this client polls:
 * POST /costs/import/pricelist/uploads/ stores the file and starts its preview,
 * POST /costs/import/pricelist/uploads/{id}/preview/ reads it again with the user's corrections,
 * POST /costs/import/pricelist/uploads/{id}/import/ creates the catalogue once the user confirms,
 * GET /costs/import/pricelist/jobs/{job_id} reports progress, then the result or the refusal.
 */
import { useAuthStore } from '@/stores/useAuthStore';

export interface PriceListSource {
  format: string;
  profile: string | null;
  title: string | null;
  region_code: string | null;
  region_name: string | null;
  /** file_header | code_prefix | layout | filename | user | null */
  region_detected_from: string | null;
  edition: string | null;
  area: string | null;
  publisher: string | null;
  licence: string | null;
  /** file | catalogue | null */
  licence_stated_in: string | null;
  attribution: string;
  suggested_catalog_name: string;
}

export interface PriceListPreview {
  source: PriceListSource;
  files: { name: string; size: number }[];
  skipped_files: { name: string; reason: string; format?: string }[];
  counts: {
    rows: number;
    importable: number;
    duplicates: number;
    broken_rows: number;
    with_analysis: number;
    with_labour_share: number;
    safety_rows: number;
    skipped: Record<string, number>;
  };
  chapters: { code: string; title: string; count: number }[];
  chapter_count: number;
  sample_rows: {
    code: string;
    description: string;
    unit: string;
    source_unit: string;
    rate: string | null;
    labour_share_pct: string | null;
    chapter: string;
  }[];
  broken_examples: { code: string; fields: string[] }[];
  warnings: string[];
  currency: string;
}

export interface PriceListImportResult {
  imported: number;
  rows: number;
  duplicates: number;
  skipped: Record<string, number>;
  catalog: string;
  catalog_id: string;
  catalog_currency: string;
  source: PriceListSource;
}

/** An error the server names by a stable code; the UI translates the code. */
export class PriceListError extends Error {
  code: string;
  params: Record<string, unknown>;

  constructor(code: string, message: string, params: Record<string, unknown> = {}) {
    super(message);
    this.code = code;
    this.params = params;
  }
}

/** The region prefixes the ministry assigns, with the region each names. */
export const PRICE_LIST_REGIONS: readonly { code: string; name: string }[] = [
  { code: 'ABR', name: 'Abruzzo' },
  { code: 'BAS', name: 'Basilicata' },
  { code: 'CAL', name: 'Calabria' },
  { code: 'CAM', name: 'Campania' },
  { code: 'EMR', name: 'Emilia-Romagna' },
  { code: 'FVG', name: 'Friuli Venezia Giulia' },
  { code: 'LAZ', name: 'Lazio' },
  { code: 'LIG', name: 'Liguria' },
  { code: 'LOM', name: 'Lombardia' },
  { code: 'MAR', name: 'Marche' },
  { code: 'MOL', name: 'Molise' },
  { code: 'PIE', name: 'Piemonte' },
  { code: 'PUG', name: 'Puglia' },
  { code: 'SAR', name: 'Sardegna' },
  { code: 'SIC', name: 'Sicilia' },
  { code: 'TOS', name: 'Toscana' },
  { code: 'UMB', name: 'Umbria' },
  { code: 'VDA', name: "Valle d'Aosta" },
  { code: 'VEN', name: 'Veneto' },
  { code: 'TRE', name: 'Provincia autonoma di Trento' },
  { code: 'BOL', name: 'Provincia autonoma di Bolzano' },
];

function authHeaders(): Record<string, string> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

async function send<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, headers: authHeaders() });
  if (response.ok) return response.json() as Promise<T>;
  let detail: unknown = null;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    // not JSON: fall through to the status-only error
  }
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const { code, message, ...params } = detail as { code: string; message?: string };
    throw new PriceListError(code, message ?? code, params);
  }
  throw new PriceListError('http_error', typeof detail === 'string' ? detail : String(response.status), {
    status: response.status,
  });
}

export interface PriceListOverrides {
  regionCode?: string;
  edition?: string;
}

/** How far a running preview or import has got. */
export interface PriceListProgress {
  /** reading | writing | null */
  stage: string | null;
  rowsRead: number;
  imported: number;
  /** 0-100 when the total is known, else 0 */
  percent: number;
}

interface PriceListJob<T> {
  job_id: string;
  kind: 'preview' | 'import';
  upload_id: string | null;
  status: 'pending' | 'started' | 'success' | 'failed' | 'cancelled';
  progress_percent: number;
  stage: string | null;
  rows_read: number;
  imported: number;
  result?: T;
  error?: { code: string; message?: string; params?: Record<string, unknown> };
}

interface JobStarted {
  upload_id: string;
  job_id: string;
}

const BASE = '/api/v1/costs/import/pricelist';
/** How often a running job is asked how far it got. */
export const PRICE_LIST_POLL_MS = 1000;

function overridesForm(overrides: PriceListOverrides): FormData {
  const data = new FormData();
  if (overrides.regionCode) data.append('region_code', overrides.regionCode);
  if (overrides.edition) data.append('edition', overrides.edition);
  return data;
}

async function waitForJob<T>(jobId: string, onProgress?: (progress: PriceListProgress) => void): Promise<T> {
  for (;;) {
    const job = await send<PriceListJob<T>>(`${BASE}/jobs/${jobId}`);
    if (job.status === 'success' && job.result !== undefined) return job.result;
    if (job.status === 'failed' || job.status === 'cancelled') {
      const error = job.error ?? { code: 'import_failed' };
      throw new PriceListError(error.code, error.message || error.code, error.params ?? {});
    }
    onProgress?.({
      stage: job.stage,
      rowsRead: job.rows_read,
      imported: job.imported,
      percent: job.progress_percent,
    });
    await new Promise((resolve) => setTimeout(resolve, PRICE_LIST_POLL_MS));
  }
}

/** Store the file and read it; resolves with the upload's id and the preview. */
export async function uploadPriceList(
  file: File,
  overrides: PriceListOverrides = {},
  onProgress?: (progress: PriceListProgress) => void,
): Promise<{ uploadId: string; preview: PriceListPreview }> {
  const data = overridesForm(overrides);
  data.append('file', file);
  const started = await send<JobStarted>(`${BASE}/uploads/`, { method: 'POST', body: data });
  try {
    const preview = await waitForJob<PriceListPreview>(started.job_id, onProgress);
    return { uploadId: started.upload_id, preview };
  } catch (error) {
    // A file that cannot be read is of no use on the server either.
    await discardPriceListUpload(started.upload_id);
    throw error;
  }
}

/** Read the stored upload again with the region or edition the user corrected. */
export async function repreviewPriceList(
  uploadId: string,
  overrides: PriceListOverrides,
  onProgress?: (progress: PriceListProgress) => void,
): Promise<PriceListPreview> {
  const started = await send<JobStarted>(`${BASE}/uploads/${uploadId}/preview/`, {
    method: 'POST',
    body: overridesForm(overrides),
  });
  return waitForJob<PriceListPreview>(started.job_id, onProgress);
}

/** Import the stored upload into a new catalogue; ``expectedRows`` (from the preview) lets progress show a percent. */
export async function importUploadedPriceList(
  uploadId: string,
  catalogName: string,
  overrides: PriceListOverrides = {},
  expectedRows?: number,
  onProgress?: (progress: PriceListProgress) => void,
): Promise<PriceListImportResult> {
  const data = overridesForm(overrides);
  data.append('catalog_name', catalogName.trim());
  if (expectedRows) data.append('expected_rows', String(expectedRows));
  const started = await send<JobStarted>(`${BASE}/uploads/${uploadId}/import/`, { method: 'POST', body: data });
  return waitForJob<PriceListImportResult>(started.job_id, onProgress);
}

/** Forget an upload the user cancelled; best effort, the server sweeps it after a day anyway. */
export async function discardPriceListUpload(uploadId: string): Promise<void> {
  try {
    await fetch(`${BASE}/uploads/${uploadId}/`, { method: 'DELETE', headers: authHeaders() });
  } catch {
    // nothing to do: an upload left behind is swept by the server
  }
}
