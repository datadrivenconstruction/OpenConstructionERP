// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Wire types for the File References feature (W9).
 *
 * Mirrors `backend/app/modules/file_references/schemas.py` — keep in
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

export type TargetType =
  | 'rfi'
  | 'issue'
  | 'task'
  | 'submittal'
  | 'punch_item'
  | 'change_order'
  | 'meeting'
  | 'field_report'
  | 'tender_package'
  | 'bid'
  | 'contract'
  | 'transmittal'
  | 'inspection'
  | 'ncr'
  | 'bcf_topic'
  | 'boq_position'
  | 'project'
  | 'clash_run';

export type ViolationCode =
  | 'not-iso19650'
  | 'missing-volume'
  | 'bad-level'
  | 'bad-role-code'
  | 'bad-number'
  | 'too-many-parts'
  | 'too-few-parts';

export interface Iso19650Parts {
  project: string | null;
  originator: string | null;
  volume: string | null;
  level: string | null;
  type: string | null;
  role: string | null;
  number: string | null;
  status: string | null;
  revision: string | null;
}

export interface Iso19650Result {
  filename: string;
  rule_set: string;
  is_valid: boolean;
  violation_codes: ViolationCode[];
  parts: Iso19650Parts;
}

export interface NamingViolationResponse {
  id: string;
  project_id: string;
  rule_set: string;
  file_kind: FileKind;
  file_id: string;
  filename: string;
  violation_codes: ViolationCode[];
  summary: string | null;
  acknowledged_at: string | null;
  acknowledged_by_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface NamingViolationListResponse {
  items: NamingViolationResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface ProjectScanResponse {
  project_id: string;
  rule_set: string;
  scanned: number;
  violations_added: number;
  violations_updated: number;
  violations_cleared: number;
}

export interface FileReferenceResponse {
  id: string;
  project_id: string;
  file_kind: FileKind;
  file_id: string;
  target_type: TargetType;
  target_id: string;
  relation: string;
  target_label: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface FileReferenceListResponse {
  items: FileReferenceResponse[];
  total: number;
}

export interface FileReferenceCreatePayload {
  project_id: string;
  file_kind: FileKind;
  file_id: string;
  target_type: TargetType;
  target_id: string;
  relation?: string;
  target_label?: string | null;
}
