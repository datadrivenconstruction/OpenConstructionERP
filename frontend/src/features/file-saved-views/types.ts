// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wire types for the file-saved-views (W5) module.
//
// Mirrors backend/app/modules/file_saved_views/schemas.py — keep them
// in sync when the backend changes a field.

export interface FilterSnapshot {
  kind?: string | null;
  q?: string | null;
  sort?: string | null;
  extension?: string | null;
  tag_ids?: string[];
  date_range?: Record<string, unknown> | null;
  custom_keys?: Record<string, unknown>;
  /** Allow forward-compat keys without breaking the contract. */
  [key: string]: unknown;
}

export interface SavedViewResponse {
  id: string;
  user_id: string;
  project_id: string | null;
  name: string;
  icon: string | null;
  filter_json: FilterSnapshot;
  sort_order: number;
  is_pinned: boolean;
  is_shared: boolean;
  last_used_at: string | null;
  use_count: number;
  created_at: string;
  updated_at: string;
  /** True when the view belongs to the calling user. */
  is_own: boolean;
}

export interface SavedViewListResponse {
  items: SavedViewResponse[];
  total: number;
}

export interface SavedViewCreatePayload {
  name: string;
  project_id?: string | null;
  icon?: string | null;
  filter_json: FilterSnapshot;
  is_pinned?: boolean;
  is_shared?: boolean;
  sort_order?: number;
}

export interface SavedViewUpdatePayload {
  name?: string;
  icon?: string | null;
  filter_json?: FilterSnapshot;
  is_pinned?: boolean;
  is_shared?: boolean;
  sort_order?: number;
}
