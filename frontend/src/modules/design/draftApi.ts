// Design module (ERP side of the design editor link).
/**
 * Drafts of the browser editor (contract README §11): every edit autosaves the package as the person's draft, the ERP
 * shows its quantities and estimate at once, and one action makes a revision from it through the desktop editor's
 * intake (the server takes and frees the project lock). Also who may edit a project and the editor's own AI choice.
 */
import { API_BASE, ApiError, apiGet, apiPost, apiPut, apiDelete, fetchWithAuth } from '@/shared/lib/api';
import { LINK_VERSION } from './api';
import type { RevisionView } from './data/revisions';

const HEADERS = { 'X-DDC-Link': LINK_VERSION };
const P = (id: string) => `/v1/design/projects/${id}`;

export interface DraftLine {
  rule: string; unit: string | null; elements: number; element_keys: string[];
  quantity: string | null; current_quantity: string | null; unit_rate: string | null;
  total: string | null; current_total: string | null; position_id: string | null; description: string; flags: string[];
}

export interface DraftView {
  project_id: string; revision_id: string; parent_revision_id: string | null;
  package_sha256: string; package_bytes: number; element_count: number; updated_at: string;
  estimate: { estimate: boolean; lines: DraftLine[]; model_total: string };
}

export interface DesignRights { edit: 'members' | 'managers'; can_edit: boolean; can_accept: boolean }
export interface AiChoice { same_as_erp: boolean; preferred_model: string | null; model: string | null }

async function failure(r: Response): Promise<ApiError> {
  let body: unknown = null;
  try { body = await r.json(); } catch { /* not JSON */ }
  return new ApiError(r.status, r.statusText, body);
}

/** The person's draft, null when there is none. */
export async function fetchDraft(projectId: string): Promise<DraftView | null> {
  try {
    return (await apiGet<DraftView | null>(`${P(projectId)}/draft`, { headers: HEADERS })) ?? null;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export async function saveDraft(projectId: string, bytes: Uint8Array): Promise<DraftView> {
  const form = new FormData();
  form.append('package', new Blob([bytes as BlobPart], { type: 'application/zip' }), 'draft.ddcrev');
  const r = await fetchWithAuth(`${API_BASE}${P(projectId)}/draft`, { method: 'PUT', body: form, headers: HEADERS });
  if (!r.ok) throw await failure(r);
  return (await r.json()) as DraftView;
}

export async function readDraftPackage(projectId: string): Promise<Uint8Array> {
  const r = await fetchWithAuth(`${API_BASE}${P(projectId)}/draft/package`, { headers: HEADERS });
  if (!r.ok) throw await failure(r);
  return new Uint8Array(await r.arrayBuffer());
}

export const dropDraft = (projectId: string) => apiDelete(`${P(projectId)}/draft`, { headers: HEADERS });

/** The draft becomes a revision awaiting acceptance (409: someone else edits, or the chain moved on). */
export const makeRevision = (projectId: string) =>
  apiPost<RevisionView>(`${P(projectId)}/draft/revision`, {}, { headers: HEADERS });

export const fetchRights = (projectId: string) => apiGet<DesignRights>(`${P(projectId)}/design-rights`, { headers: HEADERS });
export const putRights = (projectId: string, edit: DesignRights['edit']) =>
  apiPut<{ edit: DesignRights['edit'] }>(`${P(projectId)}/design-rights`, { edit }, { headers: HEADERS });

export const fetchAiChoice = () => apiGet<AiChoice>('/v1/design/ai-choice', { headers: HEADERS });
export const putAiChoice = (c: { preferred_model: string | null; model: string | null }) =>
  apiPut<AiChoice>('/v1/design/ai-choice', c, { headers: HEADERS });

/** One file of a revision, read with the person's session (the editor never gets the token). */
export async function readRevisionFile(revisionId: string, path: string): Promise<Uint8Array> {
  const r = await fetchWithAuth(`${API_BASE}/v1/design/revisions/${revisionId}/files/${path.split('/').map(encodeURIComponent).join('/')}`);
  if (!r.ok) throw await failure(r);
  return new Uint8Array(await r.arrayBuffer());
}
