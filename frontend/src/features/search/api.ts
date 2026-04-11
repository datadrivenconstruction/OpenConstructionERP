/**
 * API client for the unified semantic search backend (`/api/v1/search/`)
 * and the per-module similar-items endpoints.
 *
 * The unified search endpoint fans out to every registered vector
 * collection (BOQ, documents, tasks, risks, BIM elements, validation,
 * chat history) and merges the results via Reciprocal Rank Fusion.  See
 * `backend/app/modules/search/router.py` for the contract.
 */

import { apiGet } from '@/shared/lib/api';

/** One unified-search hit returned by the backend.  Mirrors the
 *  ``UnifiedSearchHit`` Pydantic schema. */
export interface UnifiedSearchHit {
  id: string;
  score: number;
  title: string;
  snippet: string;
  text: string;
  module: string;
  project_id: string;
  tenant_id: string;
  payload: Record<string, unknown>;
  collection: string;
}

export interface UnifiedSearchResponse {
  query: string;
  types: string[];
  project_id: string | null;
  total: number;
  hits: UnifiedSearchHit[];
  facets: Record<string, number>;
}

export interface SearchTypeMeta {
  name: string;
  label: string;
  short: string;
}

export interface SearchStatusCollection {
  collection: string;
  label: string;
  vectors_count: number;
  ready: boolean;
}

export interface SearchStatusResponse {
  backend: string;
  engine: string;
  model_name: string;
  embedding_dim: number;
  connected: boolean;
  collections: SearchStatusCollection[];
  cost_collection: Record<string, unknown> | null;
}

/** Per-module similar-items response — every backend module that exposes
 *  `GET /{id}/similar/` returns the same envelope shape. */
export interface SimilarItemsResponse {
  source_id: string;
  limit: number;
  cross_project: boolean;
  hits: UnifiedSearchHit[];
}

export interface UnifiedSearchParams {
  q: string;
  types?: string[];
  projectId?: string | null;
  limitPerCollection?: number;
  finalLimit?: number;
}

const SEARCH_BASE = '/api/v1/search';

function buildQuery(params: Record<string, string | number | null | undefined>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === '') continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  }
  return parts.length > 0 ? `?${parts.join('&')}` : '';
}

/** Run a unified semantic search across the requested collections. */
export async function unifiedSearch(
  params: UnifiedSearchParams,
): Promise<UnifiedSearchResponse> {
  const qs = buildQuery({
    q: params.q,
    project_id: params.projectId ?? null,
    limit_per_collection: params.limitPerCollection ?? null,
    final_limit: params.finalLimit ?? null,
  });
  // ``types`` is a repeated query param — FastAPI accepts ?types=boq&types=documents
  let typesQs = '';
  if (params.types && params.types.length > 0) {
    typesQs = params.types.map((t) => `&types=${encodeURIComponent(t)}`).join('');
  }
  return apiGet<UnifiedSearchResponse>(`${SEARCH_BASE}/${qs}${typesQs}`);
}

/** Fetch per-collection vector store status. */
export async function fetchSearchStatus(): Promise<SearchStatusResponse> {
  return apiGet<SearchStatusResponse>(`${SEARCH_BASE}/status/`);
}

/** Fetch the list of supported collection types for the multi-select. */
export async function fetchSearchTypes(): Promise<{ types: SearchTypeMeta[] }> {
  return apiGet<{ types: SearchTypeMeta[] }>(`${SEARCH_BASE}/types/`);
}

// ── Per-module similar-items endpoints ──────────────────────────────────
//
// Each module exposes a uniform `GET /{id}/similar/` route that returns
// `SimilarItemsResponse`.  The thin wrappers below let the shared
// `<SimilarItemsPanel>` component talk to any module by name.

export type SimilarModuleKind =
  | 'boq'
  | 'documents'
  | 'tasks'
  | 'risks'
  | 'bim_elements';

const MODULE_PATH: Record<SimilarModuleKind, (id: string) => string> = {
  boq: (id) => `/api/v1/boq/positions/${encodeURIComponent(id)}/similar/`,
  documents: (id) => `/api/v1/documents/${encodeURIComponent(id)}/similar/`,
  tasks: (id) => `/api/v1/tasks/${encodeURIComponent(id)}/similar/`,
  risks: (id) => `/api/v1/risk/${encodeURIComponent(id)}/similar/`,
  bim_elements: (id) =>
    `/api/v1/bim_hub/elements/${encodeURIComponent(id)}/similar/`,
};

export async function fetchSimilarItems(
  module: SimilarModuleKind,
  id: string,
  options?: { limit?: number; crossProject?: boolean },
): Promise<SimilarItemsResponse> {
  const base = MODULE_PATH[module](id);
  const qs = buildQuery({
    limit: options?.limit ?? null,
    cross_project:
      options?.crossProject === undefined
        ? null
        : options.crossProject
          ? 'true'
          : 'false',
  });
  return apiGet<SimilarItemsResponse>(`${base}${qs}`);
}

/** Build a deep-link URL for a unified-search hit so the modal can
 *  navigate the user to the matching native page on click. */
export function hitToHref(hit: UnifiedSearchHit): string {
  switch (hit.collection) {
    case 'oe_boq_positions': {
      const boqId =
        typeof hit.payload?.boq_id === 'string' ? hit.payload.boq_id : '';
      return boqId
        ? `/boq?boq=${encodeURIComponent(boqId)}&position=${encodeURIComponent(hit.id)}`
        : `/boq?position=${encodeURIComponent(hit.id)}`;
    }
    case 'oe_documents':
      return `/documents?id=${encodeURIComponent(hit.id)}`;
    case 'oe_tasks':
      return `/tasks?id=${encodeURIComponent(hit.id)}`;
    case 'oe_risks':
      return `/risks?id=${encodeURIComponent(hit.id)}`;
    case 'oe_bim_elements':
      return `/bim?element=${encodeURIComponent(hit.id)}`;
    case 'oe_validation':
      return `/validation?id=${encodeURIComponent(hit.id)}`;
    case 'oe_chat':
      return `/chat?message=${encodeURIComponent(hit.id)}`;
    default:
      return '#';
  }
}

/** Human-readable label for a collection key — used for facet pills. */
export function collectionLabel(collection: string): string {
  switch (collection) {
    case 'oe_boq_positions':
      return 'BOQ';
    case 'oe_documents':
      return 'Documents';
    case 'oe_tasks':
      return 'Tasks';
    case 'oe_risks':
      return 'Risks';
    case 'oe_bim_elements':
      return 'BIM';
    case 'oe_validation':
      return 'Validation';
    case 'oe_chat':
      return 'Chat';
    default:
      return collection.replace(/^oe_/, '');
  }
}
