// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed client for the /api/v1/retrieval/* surface.

import { apiDelete, apiGet, apiPost } from '@/shared/lib/api';
import type {
  RetrievalQuery,
  RetrievalResponse,
  SavedSearch,
  SavedSearchFacets,
  SavedSearchListResponse,
} from './types';

const BASE = '/v1/retrieval';

/** Run a faceted, ranked search across a project's record. */
export const searchRecords = (projectId: string, query: RetrievalQuery) => {
  const params = new URLSearchParams({ project_id: projectId });
  for (const [key, value] of Object.entries(query)) {
    if (value && value.trim() !== '') {
      params.set(key, value.trim());
    }
  }
  return apiGet<RetrievalResponse>(`${BASE}/search?${params.toString()}`);
};

/**
 * Fill in the facets the server expects. It stores all six as columns, so a
 * partially-filled query is sent with the rest as empty strings rather than as
 * missing keys - that way clearing a facet on an existing pin actually clears
 * it instead of leaving the old value in place.
 */
function toFacets(query: RetrievalQuery): SavedSearchFacets {
  return {
    text: query.text?.trim() ?? '',
    party: query.party?.trim() ?? '',
    record_type: query.record_type?.trim() ?? '',
    date_from: query.date_from?.trim() ?? '',
    date_to: query.date_to?.trim() ?? '',
    entity: query.entity?.trim() ?? '',
  };
}

/** The caller's pinned searches on a project, most recently used first. */
export const listSavedSearches = (projectId: string) => {
  const params = new URLSearchParams({ project_id: projectId });
  return apiGet<SavedSearchListResponse>(`${BASE}/saved-searches?${params.toString()}`);
};

/** Pin a search. Re-saving the same facets updates that pin rather than adding a second. */
export const createSavedSearch = (projectId: string, label: string, query: RetrievalQuery) =>
  apiPost<SavedSearch>(`${BASE}/saved-searches`, {
    project_id: projectId,
    label,
    query: toFacets(query),
  });

/** Record that the caller replayed a pin, so it climbs their list. */
export const recordSavedSearchUse = (savedId: string) =>
  apiPost<SavedSearch>(`${BASE}/saved-searches/${savedId}/use`, {});

/** Unpin a search. */
export const deleteSavedSearch = (savedId: string) =>
  apiDelete<void>(`${BASE}/saved-searches/${savedId}`);
