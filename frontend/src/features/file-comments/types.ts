// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Wire types for the File Comments feature (W6).
 *
 * Mirrors `backend/app/modules/file_comments/schemas.py` — keep in
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

export interface FileCommentMention {
  id: string;
  comment_id: string;
  mentioned_user_id: string;
  notified_at: string | null;
  created_at: string;
}

export interface FileCommentResponse {
  id: string;
  project_id: string;
  file_kind: FileKind;
  file_id: string;
  file_version_snapshot: string | null;
  /** Epic C — unified version-chain FK. NULL = pre-Epic-C comment;
   *  treat as current. */
  file_version_id: string | null;
  parent_id: string | null;
  author_id: string;
  /** Pre-resolved display label for ``author_id`` (full name, falling
   *  back to email, then a short id). Server-side enrichment - render
   *  this instead of slicing the raw id. NULL only for legacy payloads
   *  predating the enrichment; fall back to a short id then. */
  author_name: string | null;
  body: string;
  page_number: number | null;
  anchor_x: number | null;
  anchor_y: number | null;
  resolved: boolean;
  resolved_at: string | null;
  resolved_by_id: string | null;
  created_at: string;
  updated_at: string;
  mentions: FileCommentMention[];
}

export interface FileCommentThread extends FileCommentResponse {
  replies: FileCommentThread[];
}

export interface FileCommentListResponse {
  file_kind: FileKind;
  file_id: string;
  threads: FileCommentThread[];
  total: number;
}

export interface FileCommentCreatePayload {
  project_id: string;
  file_kind: FileKind;
  file_id: string;
  parent_id?: string | null;
  body: string;
  page_number?: number | null;
  anchor_x?: number | null;
  anchor_y?: number | null;
  file_version_snapshot?: string | null;
  /** Epic C — explicit version pin. Omit to default to the current
   *  chain head (the usual behaviour). */
  file_version_id?: string | null;
}

export interface FileCommentUpdatePayload {
  body?: string | null;
  resolved?: boolean | null;
}

export interface UnreadMentionItem {
  mention_id: string;
  comment_id: string;
  project_id: string;
  file_kind: FileKind;
  file_id: string;
  author_id: string;
  body_excerpt: string;
  created_at: string;
}

export interface UnreadMentionListResponse {
  items: UnreadMentionItem[];
  total: number;
}
