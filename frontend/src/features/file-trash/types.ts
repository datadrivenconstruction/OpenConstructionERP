// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Wire types for the File Trash feature (W2).
 *
 * Mirrors `backend/app/modules/file_trash/schemas.py` — keep in
 * sync when the backend changes a field.
 */

export type TrashKind =
  | 'document'
  | 'photo'
  | 'sheet'
  | 'bim_model'
  | 'dwg_drawing'
  | 'takeoff'
  | 'report'
  | 'markup';

export interface TrashItem {
  id: string;
  project_id: string;
  original_kind: TrashKind;
  original_id: string;
  canonical_name: string;
  payload_json: Record<string, unknown>;
  trashed_at: string;
  trashed_by_id: string | null;
  retention_days: number;
  restored_at: string | null;
  restored_by_id: string | null;
  purged_at: string | null;
  restore_token: string;
  file_size: number;
  created_at: string;
  updated_at: string;
}

export interface TrashListResponse {
  items: TrashItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TrashSoftDeletePayload {
  project_id: string;
  kind: TrashKind;
  original_id: string;
  canonical_name?: string;
  payload?: Record<string, unknown> | null;
  retention_days?: number;
}

export interface TrashStats {
  project_id: string;
  count: number;
  total_bytes: number;
  oldest_trashed_at: string | null;
  newest_trashed_at: string | null;
}
