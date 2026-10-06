// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API client for the unified semantic search backend (`/api/v1/search/`)
 * and the per-module similar-items endpoints.
 *
 * The unified search endpoint fans out to every registered vector
 * collection (BOQ, documents, tasks, risks, BIM elements, validation,
 * chat history) and merges the results via Reciprocal Rank Fusion.  See
 * `backend/app/modules/search/router.py` for the contract.
 */

import type { TFunction } from 'i18next';

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
  /** Full collection key, e.g. `oe_boq_positions`. Label it with
   *  `collectionLabel`, which reads the reader's locale. */
  name: string;
  /** The server's own English name for the collection, from
   *  `COLLECTION_LABELS` in `backend/app/core/vector_index.py`. The server
   *  cannot know the reader's language, so nothing in this app renders it;
   *  it stays on the wire for other API consumers. */
  label: string;
  /** `name` without its `oe_` prefix; what `GET /search/?types=` accepts. */
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

const SEARCH_BASE = '/v1/search';

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
  // NOTE: `requirements` is intentionally absent from this table.
  // The similar-requirements route is nested under the parent set
  // (`/requirements/{set_id}/requirements/{req_id}/similar/`), so
  // the generic `SimilarItemsPanel` — which only knows the item id
  // — cannot build a URL for it.  Requirement similarity is surfaced
  // via the set-scoped detail page directly, not through this
  // generic cross-module panel.
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
 *  navigate the user to the matching native page on click.
 *
 *  Each route is matched against the actual `App.tsx` route table:
 *
 *    /boq/:boqId?highlight=<position_id>     → BOQEditorPage
 *    /files?file=<doc_id>                    → FileManagerPage
 *    /tasks?id=<task_id>                     → TasksPage
 *    /risks?id=<risk_id>                     → RiskRegisterPage
 *    /bim?element=<element_id>               → BIMPage
 *    /bim/rules?tab=requirements             → BIMQuantityRulesPage (Requirements tab)
 *    /validation?id=<report_id>              → ValidationPage
 *    /chat?session=<session_id>              → ERP Chat full page
 *    /changeorders?highlight=<order_id>      → ChangeOrdersPage
 *    /variations                             → VariationsPage
 *    /moc                                    → MoCPage
 *    /costs                                  → CostsPage
 *
 *  The last three land on the register rather than on the record. Neither
 *  page can select one from the URL - they read no search param at all - so
 *  a parameter here would be a link that looks precise and is not, which is
 *  the shape `linkedRecordDeepLink.test.tsx` already settled for the same
 *  question: the bare register is the honest destination until the page can
 *  read an id, and a test says which ones are still waiting.
 *
 *  Returns ``#`` for unknown collections so the click is a safe no-op. Every
 *  collection in ALL_COLLECTIONS (backend/app/core/vector_index.py:112) is
 *  answered above, so today that branch is only reachable by a collection
 *  the backend has grown and this build has not heard of yet - which is
 *  exactly how the four cases above came to be missing. The modal marks such
 *  a row non-navigable rather than letting the click do nothing in silence.
 */
export function hitToHref(hit: UnifiedSearchHit): string {
  switch (hit.collection) {
    case 'oe_boq_positions': {
      const boqId =
        typeof hit.payload?.boq_id === 'string' ? hit.payload.boq_id : '';
      // BOQ editor uses a path-segment for the BOQ id and a `highlight`
      // query for the position.  Without a boq_id we can only land on
      // the list page — fail soft.
      if (!boqId) return '/boq';
      return `/boq/${encodeURIComponent(boqId)}?highlight=${encodeURIComponent(hit.id)}`;
    }
    case 'oe_documents':
      // Documents merged into the unified File Manager (#71): the file
      // browser pre-selects a file via `?file=<id>`. The old `/documents?id`
      // form dropped its query through the redirect, so point straight at
      // the live route and param.
      return `/files?file=${encodeURIComponent(hit.id)}`;
    case 'oe_tasks':
      return `/tasks?id=${encodeURIComponent(hit.id)}`;
    case 'oe_risks':
      return `/risks?id=${encodeURIComponent(hit.id)}`;
    case 'oe_bim_elements':
      return `/bim?element=${encodeURIComponent(hit.id)}`;
    case 'oe_requirements':
      // Requirements are the Requirements tab of /bim/rules, which opens on
      // the quantity rules unless the URL names the tab. The page reads no
      // requirement id, so the tab is where the link honestly lands.
      return '/bim/rules?tab=requirements';
    case 'oe_rfi_rfis':
      // RFI has a dedicated detail route that self-resolves its project.
      return `/rfi/${encodeURIComponent(hit.id)}`;
    case 'oe_submittals_submittals':
      return `/submittals?id=${encodeURIComponent(hit.id)}`;
    case 'oe_correspondence_correspondence':
      return `/correspondence?id=${encodeURIComponent(hit.id)}`;
    case 'oe_validation':
      return `/validation?id=${encodeURIComponent(hit.id)}`;
    case 'oe_chat': {
      // Jump to the chat session that contains the message — the
      // session_id rides in the payload from the chat vector adapter.
      const sessionId =
        typeof hit.payload?.session_id === 'string' ? hit.payload.session_id : '';
      return sessionId
        ? `/chat?session=${encodeURIComponent(sessionId)}`
        : '/chat';
    }
    case 'oe_change_orders':
      // `?highlight=` is the house convention for list screens, and
      // ChangeOrdersPage reads it (ChangeOrdersPage.tsx:2107).
      return `/changeorders?highlight=${encodeURIComponent(hit.id)}`;
    case 'oe_variations':
      return '/variations';
    case 'oe_moc':
      return '/moc';
    case 'oe_cost_items':
      return '/costs';
    default:
      return '#';
  }
}

/** The localised name of the kind of thing a collection holds.
 *
 *  This wording heads a group of results and stands in for the type of a
 *  hit that has no title of its own, so it belongs to the locale files
 *  rather than to this module. `t` is a required argument for that
 *  reason - an optional one would let a call site quietly render English
 *  to every reader, which is the defect this function used to be.
 *
 *  Acronyms are keyed like everything else here even though most
 *  languages keep them as they are. A locale that leaves BOQ, BIM or RFI
 *  alone has made that decision; a term never offered for translation
 *  has not.
 *
 *  Args:
 *    t: The i18next translator, from `useTranslation()`.
 *    collection: Backend collection key, for example `oe_boq_positions`.
 *
 *  Returns:
 *    The label in the reader's language.
 */
export function collectionLabel(t: TFunction, collection: string): string {
  switch (collection) {
    case 'oe_boq_positions':
      return t('global_search.collection.boq', { defaultValue: 'BOQ' });
    case 'oe_documents':
      return t('global_search.collection.documents', {
        defaultValue: 'Documents',
      });
    case 'oe_tasks':
      return t('global_search.collection.tasks', { defaultValue: 'Tasks' });
    case 'oe_risks':
      return t('global_search.collection.risks', { defaultValue: 'Risks' });
    case 'oe_bim_elements':
      return t('global_search.collection.bim', { defaultValue: 'BIM' });
    case 'oe_requirements':
      return t('global_search.collection.requirements', {
        defaultValue: 'Requirements',
      });
    case 'oe_rfi_rfis':
      return t('global_search.collection.rfi', { defaultValue: 'RFI' });
    case 'oe_submittals_submittals':
      return t('global_search.collection.submittals', {
        defaultValue: 'Submittals',
      });
    case 'oe_correspondence_correspondence':
      return t('global_search.collection.correspondence', {
        defaultValue: 'Correspondence',
      });
    case 'oe_validation':
      return t('global_search.collection.validation', {
        defaultValue: 'Validation',
      });
    case 'oe_chat':
      return t('global_search.collection.chat', { defaultValue: 'Chat' });
    case 'oe_change_orders':
      return t('global_search.collection.change_orders', {
        defaultValue: 'Change Orders',
      });
    case 'oe_variations':
      return t('global_search.collection.variations', {
        defaultValue: 'Variations',
      });
    case 'oe_moc':
      return t('global_search.collection.moc', {
        defaultValue: 'Management of Change',
      });
    case 'oe_cost_items':
      return t('global_search.collection.costs', {
        defaultValue: 'Cost Database',
      });
    default:
      // A collection this build has never heard of has no key to read, so
      // the raw name without its `oe_` prefix is the only honest answer.
      // Inventing a key here would only add one no locale can answer.
      return collection.replace(/^oe_/, '');
  }
}

/** The label a person can recognise a hit by.
 *
 *  Two shapes arrive here with nothing to say. A hit can carry an empty
 *  title, and it can carry its own id as the title, because `VectorHit.title`
 *  falls back to the row id when a payload holds neither a title nor any
 *  text. The second one is truthy, so a plain `title || id` hands it straight
 *  to the screen. Both read as a bare UUID, which names nothing to the person
 *  scanning the list.
 *
 *  Both halves of the last-resort wording come from the caller - the
 *  sentence through `unnamed` and the name of the kind through
 *  `kindLabel` - so this stays a pure function and every string it can
 *  produce for an unnamed hit stays in the locale files.
 *
 *  Args:
 *    hit: The hit to name.
 *    kindLabel: Resolves a collection key to its localised name; pass
 *      `(c) => collectionLabel(t, c)`.
 *    unnamed: Renders the fallback sentence from the kind and a short
 *      reference.
 *
 *  Returns:
 *    The title the backend sent, or the fallback wording.
 */
export function hitLabel(
  hit: UnifiedSearchHit,
  kindLabel: (collection: string) => string,
  unnamed: (kind: string, ref: string) => string,
): string {
  const title = (hit.title ?? '').trim();
  if (title && title !== hit.id) return title;
  return unnamed(kindLabel(hit.collection), String(hit.id).slice(0, 8));
}
