// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Wire types for the File Versioning feature (W1).
 *
 * Mirrors `backend/app/modules/file_versions/schemas.py` — keep in
 * sync when the backend changes a field.
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

export interface FileVersionResponse {
  id: string;
  project_id: string;
  file_kind: FileKind;
  file_id: string;
  version_number: number;
  canonical_name: string;
  previous_version_id: string | null;
  is_current: boolean;
  superseded_at: string | null;
  superseded_by_id: string | null;
  notes: string | null;
  uploaded_by_id: string | null;
  uploaded_at: string;
  file_size: number;
  checksum: string | null;
  created_at: string;
  updated_at: string;
}

export interface FileVersionCreatePayload {
  project_id: string;
  file_kind: FileKind;
  file_id: string;
  canonical_name: string;
  previous_version_id?: string | null;
  notes?: string | null;
  file_size?: number;
  checksum?: string | null;
}
