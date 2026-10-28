// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed API client for the estimating-methodology engine.
// Base path: /api/v1/methodology (the `/api` prefix is added by the helper).
//
// Every endpoint that touches project data is IDOR-guarded server-side; this
// client just sends the project_id the backend requires.

import {
  apiGet,
  apiPost,
  apiPatch,
  apiPut,
  apiDelete,
  API_BASE,
  getAuthToken,
  triggerDownload,
  extractErrorMessageFromBody,
} from '@/shared/lib/api';
import type {
  ActiveMethodology,
  ComputeEstimateRequest,
  ComputeEstimateResponse,
  Dimension,
  DimensionCreate,
  FundingSource,
  FundingSourceCreate,
  FundingSourceUpdate,
  InstallTemplateRequest,
  Methodology,
  MethodologyCreate,
  MethodologyListItem,
  MethodologyUpdate,
  TemplateListItem,
} from './types';

const BASE = '/v1/methodology';

/**
 * Coerce a money / rate value to a finite number.
 *
 * The backend serialises Decimal money and rates as JSON STRINGS (e.g. "12",
 * "0.32", "900.00"). The types declare those fields as `string` on purpose to
 * preserve precision on the wire. Use this at every arithmetic / formatting
 * boundary - a raw string `+` would silently concatenate. Non-finite or
 * unparseable input collapses to 0 so one bad value never breaks a render.
 */
export function toNum(v: unknown): number {
  if (typeof v === 'number') return Number.isFinite(v) ? v : 0;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

/** Build a query string from a flat record, skipping null/undefined values. */
function qs(params: Record<string, string | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.set(k, v);
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export const methodologyApi = {
  // ── Built-in templates (project-agnostic catalogue) ──────────────────
  listTemplates: () => apiGet<TemplateListItem[]>(`${BASE}/templates`),

  installTemplate: (body: InstallTemplateRequest) =>
    apiPost<Methodology, InstallTemplateRequest>(`${BASE}/templates/install`, body),

  // ── Methodology CRUD ─────────────────────────────────────────────────
  list: (projectId: string) =>
    apiGet<MethodologyListItem[]>(`${BASE}/${qs({ project_id: projectId })}`),

  get: (methodologyId: string, projectId: string) =>
    apiGet<Methodology>(`${BASE}/${methodologyId}${qs({ project_id: projectId })}`),

  create: (body: MethodologyCreate) =>
    apiPost<Methodology, MethodologyCreate>(`${BASE}/`, body),

  update: (methodologyId: string, projectId: string, body: MethodologyUpdate) =>
    apiPatch<Methodology, MethodologyUpdate>(
      `${BASE}/${methodologyId}${qs({ project_id: projectId })}`,
      body,
    ),

  remove: (methodologyId: string, projectId: string) =>
    apiDelete(`${BASE}/${methodologyId}${qs({ project_id: projectId })}`),

  // ── Active methodology pointer ───────────────────────────────────────
  getActive: (projectId: string) =>
    apiGet<ActiveMethodology>(`${BASE}/active${qs({ project_id: projectId })}`),

  setActive: (projectId: string, slug: string) =>
    apiPut<ActiveMethodology>(
      `${BASE}/active${qs({ project_id: projectId, slug })}`,
    ),

  // ── Analytical dimensions ────────────────────────────────────────────
  listDimensions: (projectId: string, methodologySlug?: string) =>
    apiGet<Dimension[]>(
      `${BASE}/dimensions${qs({ project_id: projectId, methodology_slug: methodologySlug })}`,
    ),

  createDimension: (body: DimensionCreate) =>
    apiPost<Dimension, DimensionCreate>(`${BASE}/dimensions`, body),

  removeDimension: (dimensionId: string, projectId: string) =>
    apiDelete(`${BASE}/dimensions/${dimensionId}${qs({ project_id: projectId })}`),

  // ── Funding sources ──────────────────────────────────────────────────
  listFundingSources: (projectId: string) =>
    apiGet<FundingSource[]>(`${BASE}/funding-sources${qs({ project_id: projectId })}`),

  createFundingSource: (body: FundingSourceCreate) =>
    apiPost<FundingSource, FundingSourceCreate>(`${BASE}/funding-sources`, body),

  updateFundingSource: (
    fundingSourceId: string,
    projectId: string,
    body: FundingSourceUpdate,
  ) =>
    apiPatch<FundingSource, FundingSourceUpdate>(
      `${BASE}/funding-sources/${fundingSourceId}${qs({ project_id: projectId })}`,
      body,
    ),

  removeFundingSource: (fundingSourceId: string, projectId: string) =>
    apiDelete(`${BASE}/funding-sources/${fundingSourceId}${qs({ project_id: projectId })}`),

  // ── Compute estimate ─────────────────────────────────────────────────
  compute: (body: ComputeEstimateRequest) =>
    apiPost<ComputeEstimateResponse, ComputeEstimateRequest>(`${BASE}/compute`, body),
};

/** The export formats the methodology estimate endpoints can stream. */
export type MethodologyExportFormat = 'excel' | 'pdf';

/**
 * Download a methodology's computed estimate as an Excel or PDF file.
 *
 * Streams from `GET /methodology/{id}/export/{format}` (IDOR-guarded server
 * side: the methodology is resolved scoped to the project). The endpoint
 * returns a binary attachment, so we bypass the JSON helpers and fetch the
 * blob directly with the same Bearer auth, then hand it to `triggerDownload`.
 * The optional `boqId` sources the cascade resource totals from that BOQ;
 * when omitted the server computes an all-zero cascade.
 *
 * Throws an `Error` with a readable message on a non-OK response so the
 * caller can surface it as a toast.
 */
export async function downloadEstimate(
  methodologyId: string,
  projectId: string,
  format: MethodologyExportFormat,
  boqId?: string,
): Promise<void> {
  const sp = new URLSearchParams({ project_id: projectId });
  if (boqId) sp.set('boq_id', boqId);
  // Match the backend route: the canonical path carries a trailing slash
  // (the app runs with redirect_slashes=False).
  const url = `${API_BASE}${BASE}/${methodologyId}/export/${format}/?${sp.toString()}`;

  const token = getAuthToken();
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!res.ok) {
    // Try to lift a FastAPI {"detail": ...} message off the error body.
    let message: string | null = null;
    try {
      message = extractErrorMessageFromBody(await res.json());
    } catch {
      // Non-JSON body (e.g. an HTML error page) - fall back to the status.
    }
    throw new Error(message ?? `Export failed (${res.status})`);
  }

  const blob = await res.blob();
  const ext = format === 'excel' ? 'xlsx' : 'pdf';
  triggerDownload(blob, `estimate.${ext}`);
}
