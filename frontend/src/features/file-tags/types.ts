// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Wire types for the W4 file-tags module.
 *
 * Mirrors backend/app/modules/file_tags/schemas.py — keep in sync.
 */

export type FileKind =
  | 'document'
  | 'photo'
  | 'sheet'
  | 'bim_model'
  | 'dwg_drawing'
  | 'takeoff'
  | 'report'
  | 'markup';

export type TagCategory = 'discipline' | 'phase' | 'package' | 'custom';

export interface TagRecord {
  id: string;
  project_id: string;
  name: string;
  display_name: string;
  color: string;
  category: TagCategory | null;
  created_at: string;
  updated_at: string;
  created_by_id: string | null;
  assignment_count: number;
}

export interface CreateTagPayload {
  project_id: string;
  display_name: string;
  color?: string;
  category?: TagCategory | null;
  name?: string;
}

export interface UpdateTagPayload {
  display_name?: string;
  color?: string;
  category?: TagCategory | null;
}

export interface BulkAssignPayload {
  file_kind: FileKind;
  file_ids: string[];
}

export interface BulkAssignResult {
  tag_id: string;
  file_kind: string;
  requested: number;
  changed: number;
  already_done: number;
}

export interface SeedDefaultsResult {
  project_id: string;
  created: number;
  existing: number;
  total: number;
  tags: TagRecord[];
}
