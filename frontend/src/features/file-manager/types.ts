// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Wire types for the file manager (Issue #109).
 *
 * These mirror the Pydantic schemas in
 * backend/app/modules/projects/file_manager_schemas.py — keep them in
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

export type StorageBackend = 'local' | 's3';

export type BundleScope = 'metadata_only' | 'documents' | 'bim' | 'dwg' | 'full';

export type ImportMode = 'new_project' | 'merge_into_existing' | 'replace_existing';

export interface FileRow {
  id: string;
  kind: FileKind;
  name: string;
  project_id: string;
  size_bytes: number;
  mime_type: string | null;
  extension: string | null;
  modified_at: string | null;
  physical_path: string;
  relative_path: string;
  storage_backend: StorageBackend;
  download_url: string | null;
  preview_url: string | null;
  thumbnail_url: string | null;
  discipline: string | null;
  category: string | null;
  extra: Record<string, unknown>;
}

export interface FileTreeNode {
  id: string;
  label: string;
  kind: 'category' | 'type' | 'folder' | 'trash';
  file_count: number;
  total_bytes: number;
  physical_path: string | null;
  storage_backend: StorageBackend;
  children: FileTreeNode[];
}

export interface StorageLocations {
  project_id: string;
  project_name: string;
  storage_uses_default: boolean;
  storage_path_override: string | null;
  storage_backend: StorageBackend;
  db_path: string | null;
  uploads_root: string | null;
  photos_root: string | null;
  sheets_root: string | null;
  bim_root: string | null;
  dwg_root: string | null;
  extras: Record<string, string>;
  notes: string[];
}

export interface FileListResponse {
  project_id: string;
  items: FileRow[];
  total: number;
  limit: number;
  offset: number;
}

export interface ExportOptions {
  scope: BundleScope;
  include_documents?: boolean;
  include_photos?: boolean;
  include_sheets?: boolean;
  include_bim_models?: boolean;
  include_bim_elements?: boolean;
  include_bim_geometry?: boolean;
  include_dwg_drawings?: boolean;
  include_takeoff?: boolean;
  include_reports?: boolean;
}

export interface ExportPreview {
  scope: BundleScope;
  table_counts: Record<string, number>;
  attachment_count: number;
  estimated_size_bytes: number;
  bundle_format: string;
  bundle_format_version: string;
}

export interface BundleManifest {
  app: string;
  format: string;
  format_version: string;
  compat_min_app_version: string;
  exported_at: string;
  exported_by_email: string | null;
  project_id: string;
  project_name: string;
  project_currency: string | null;
  scope: BundleScope;
  tables: string[];
  record_counts: Record<string, number>;
  attachment_count: number;
  attachment_total_bytes: number;
  engine_name: string;
  engine_version: string;
}

export interface ImportPreview {
  manifest: BundleManifest;
  bundle_size_bytes: number;
  has_attachments: boolean;
  warnings: string[];
}

export interface ImportResult {
  project_id: string;
  mode: ImportMode;
  imported_counts: Record<string, number>;
  skipped_counts: Record<string, number>;
  attachment_count: number;
  warnings: string[];
}

export interface EmailLinkResponse {
  url: string;
  expires_at: string;
  file_id: string;
  file_name: string;
  size_bytes: number;
}

/* ── Password-protected share links ──────────────────────────────────── */

export interface ShareLinkCreatePayload {
  password?: string;
  expires_in_days?: number;
}

export interface ShareLinkResponse {
  id: string;
  token: string;
  url: string;
  document_id: string;
  requires_password: boolean;
  expires_at: string | null;
  created_at: string;
  download_count: number;
  revoked: boolean;
}

export interface ShareLinkPublicInfo {
  filename: string;
  requires_password: boolean;
  expired: boolean;
}

export interface ShareLinkAccessResponse {
  download_url: string;
  filename: string;
}

/* ── Folder permissions ──────────────────────────────────────────────── */

export type FolderRole = 'viewer' | 'editor' | 'owner';

export interface FolderPermissionRow {
  id: string;
  project_id: string;
  user_id: string;
  scope_kind: string;
  scope_path: string | null;
  role: FolderRole;
  granted_by: string;
  granted_at: string | null;
  revoked: boolean;
  created_at: string | null;
  updated_at: string | null;
  user_email: string | null;
  user_full_name: string | null;
}

export interface FolderPermissionCreatePayload {
  user_id: string;
  scope_kind: string;
  scope_path?: string | null;
  role: FolderRole;
}

export interface FileFilters {
  category?: FileKind;
  /**
   * Several kinds at once, where ``category`` selects exactly one. A caller
   * that wants two sources - the file picker asking for the documents area
   * plus the calling module's own store - sends this and gets one
   * project-scoped, permission-checked, paged answer rather than merging two
   * listings itself. An unknown kind is a 400 from the server.
   */
  kinds?: readonly FileKind[];
  extension?: string;
  q?: string;
  sort?: 'modified' | 'name' | 'size' | 'kind';
  limit?: number;
  offset?: number;
}

/* ── Per-user favourites / pins ──────────────────────────────────────── */

/** One ``user × file`` favourite row. Mirrors the backend
 * ``FavoriteResponse`` schema in
 * backend/app/modules/file_favorites/schemas.py. */
export interface FileFavorite {
  id: string;
  user_id: string;
  project_id: string;
  file_kind: FileKind;
  file_id: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

/** Stable lookup key for a favourite — matches the backend's
 * ``(file_kind, file_id)`` uniqueness scope. */
export function favoriteKey(kind: FileKind, fileId: string): string {
  return `${kind}:${fileId}`;
}

/* ── Drawing sheets ──────────────────────────────────────────────────── */

/** One indexed drawing sheet — a single page lifted out of a multi-page PDF
 * drawing set. Mirrors ``SheetResponse`` in
 * backend/app/modules/documents/schemas.py.
 *
 * ``document_id`` points at the parent document in the documents module (the
 * same table ``/v1/documents/`` lists), so it can be handed straight to the
 * plan room and takeoff deep-links without translation. ``thumbnail_path`` is a
 * server-side filesystem path, NOT a URL: no route currently serves it to an
 * authenticated client, so nothing renders it yet. */
export interface SheetRow {
  id: string;
  project_id: string;
  document_id: string;
  page_number: number;
  sheet_number: string | null;
  sheet_title: string | null;
  discipline: string | null;
  revision: string | null;
  revision_date: string | null;
  scale: string | null;
  is_current: boolean;
  previous_version_id: string | null;
  thumbnail_path: string | null;
  metadata: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
}
