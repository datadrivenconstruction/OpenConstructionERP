// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wire types for the File Transmittals (W7) feature.
// Mirrors backend/app/modules/file_transmittals/schemas.py — keep in sync.

export type TransmittalReason =
  | 'for_review'
  | 'for_construction'
  | 'for_approval'
  | 'for_information'
  | 'for_record';

export type TransmittalStatus =
  | 'draft'
  | 'sent'
  | 'acknowledged'
  | 'rejected';

export type FileKind =
  | 'document'
  | 'photo'
  | 'sheet'
  | 'bim_model'
  | 'dwg_drawing'
  | 'takeoff'
  | 'report'
  | 'markup';

export interface TransmittalItem {
  id: string;
  transmittal_id: string;
  file_kind: FileKind;
  file_id: string;
  file_version_snapshot: string | null;
  canonical_name_snapshot: string;
  sort_order: number;
}

export interface TransmittalRecipient {
  id: string;
  transmittal_id: string;
  email: string;
  display_name: string | null;
  role: string | null;
  acknowledged_at: string | null;
  acknowledge_token: string | null;
}

export interface Transmittal {
  id: string;
  project_id: string;
  number: string;
  subject: string;
  reason_code: TransmittalReason | string;
  sender_id: string | null;
  sent_at: string;
  status: TransmittalStatus | string;
  notes: string | null;
  cover_sheet_path: string | null;
  items: TransmittalItem[];
  recipients: TransmittalRecipient[];
  created_at: string;
  updated_at: string;
}

export interface TransmittalListRow {
  id: string;
  project_id: string;
  number: string;
  subject: string;
  reason_code: string;
  sender_id: string | null;
  sent_at: string;
  status: string;
  item_count: number;
  recipient_count: number;
  acknowledged_count: number;
  created_at: string;
  updated_at: string;
}

export interface TransmittalItemPayload {
  file_kind: FileKind;
  file_id: string;
  canonical_name_snapshot: string;
  file_version_snapshot?: string | null;
  sort_order?: number;
}

export interface TransmittalRecipientPayload {
  email: string;
  display_name?: string | null;
  role?: string | null;
}

export interface TransmittalCreatePayload {
  project_id: string;
  subject: string;
  reason_code: TransmittalReason;
  notes?: string | null;
  items?: TransmittalItemPayload[];
  recipients?: TransmittalRecipientPayload[];
}

export interface TransmittalAcknowledgeResponse {
  transmittal_number: string;
  subject: string;
  acknowledged_at: string;
  recipient_email: string;
}
