// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** One ranked record returned by the findability search. */
export interface RetrievalResult {
  record_type: string;
  record_id: string;
  title: string;
  snippet: string;
  source_module: string;
  party: string;
  occurred_at: string;
  entity_refs: string[];
  score: number;
  matched_facets: string[];
  provenance: Record<string, unknown>;
}

/** A ranked, faceted view across the project record. */
export interface RetrievalResponse {
  count: number;
  results: RetrievalResult[];
}

/** Facets a caller can constrain a search by. Every field is optional. */
export interface RetrievalQuery {
  text?: string;
  party?: string;
  date_from?: string;
  date_to?: string;
  entity?: string;
  record_type?: string;
  as_of?: string;
}

/**
 * The six facets a saved search replays. The server always sends all six (empty
 * string for an unset one), which is why every field is required here while
 * `RetrievalQuery` leaves them optional - a `SavedSearchFacets` is therefore
 * usable anywhere a `RetrievalQuery` is expected.
 */
export interface SavedSearchFacets {
  text: string;
  party: string;
  record_type: string;
  date_from: string;
  date_to: string;
  entity: string;
}

/** One validation finding the server recorded against a saved search. */
export interface SavedSearchFinding {
  rule_id: string;
  severity: string;
  message: string;
  suggestion?: string | null;
}

/**
 * A search the user pinned, as the server stores it. Server-owned since the
 * saved list has to survive a reload and follow the person to another browser;
 * recent searches stay local (see ./savedSearches).
 */
export interface SavedSearch {
  id: string;
  project_id: string;
  label: string;
  query: SavedSearchFacets;
  /** Server-side signature over the facets - two pins never share one. */
  signature: string;
  use_count: number;
  last_used_at?: string | null;
  created_at: string;
  updated_at: string;
  /** 'passed' | 'warnings' | 'pending' - what the rule set concluded. */
  validation_status: string;
  validation_findings: SavedSearchFinding[];
}

/** Every search the caller pinned on one project, most useful first. */
export interface SavedSearchListResponse {
  count: number;
  results: SavedSearch[];
}
