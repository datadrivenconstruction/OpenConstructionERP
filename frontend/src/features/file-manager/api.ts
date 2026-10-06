// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** API client for the project file manager (Issue #109). */

import { apiDelete, apiGet, apiPatch, apiPost, extractErrorMessageFromBody } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import type { DocumentBatchReferences } from '@/features/documents/api';
import type {
  EmailLinkResponse,
  ExportOptions,
  ExportPreview,
  FileFavorite,
  FileFilters,
  FileKind,
  FileListResponse,
  FileTreeNode,
  FolderPermissionCreatePayload,
  FolderPermissionRow,
  ImportMode,
  ImportPreview,
  ImportResult,
  ShareLinkAccessResponse,
  ShareLinkCreatePayload,
  ShareLinkPublicInfo,
  ShareLinkResponse,
  SheetRow,
  StorageLocations,
} from './types';

const PROJECTS_BASE = '/v1/projects';

function buildAuthHeaders(): Headers {
  const headers = new Headers({ Accept: 'application/json' });
  const token = useAuthStore.getState().accessToken;
  if (token) headers.set('Authorization', `Bearer ${token}`);
  return headers;
}

export async function fetchFileTree(
  projectId: string,
  filters: { q?: string; extension?: string } = {},
): Promise<FileTreeNode[]> {
  const params = new URLSearchParams();
  if (filters.q) params.set('q', filters.q);
  if (filters.extension) params.set('extension', filters.extension);
  const qs = params.toString();
  const path = `${PROJECTS_BASE}/${projectId}/files/tree/${qs ? `?${qs}` : ''}`;
  return apiGet<FileTreeNode[]>(path);
}

export async function fetchFileList(
  projectId: string,
  filters: FileFilters = {},
): Promise<FileListResponse> {
  const params = new URLSearchParams();
  if (filters.category) params.set('category', filters.category);
  if (filters.kinds?.length) params.set('kinds', filters.kinds.join(','));
  if (filters.extension) params.set('extension', filters.extension);
  if (filters.q) params.set('q', filters.q);
  if (filters.sort) params.set('sort', filters.sort);
  if (filters.limit !== undefined) params.set('limit', String(filters.limit));
  if (filters.offset !== undefined) params.set('offset', String(filters.offset));
  const qs = params.toString();
  const path = `${PROJECTS_BASE}/${projectId}/files/${qs ? `?${qs}` : ''}`;
  return apiGet<FileListResponse>(path);
}

export async function fetchStorageLocations(projectId: string): Promise<StorageLocations> {
  return apiGet<StorageLocations>(`${PROJECTS_BASE}/${projectId}/files/locations/`);
}

export async function previewExport(
  projectId: string,
  options: ExportOptions,
): Promise<ExportPreview> {
  return apiPost<ExportPreview, ExportOptions>(
    `${PROJECTS_BASE}/${projectId}/export/preview/`,
    options,
  );
}

/** Download the .ocep zip for ``projectId`` and trigger a browser save. */
export async function downloadBundle(
  projectId: string,
  options: ExportOptions,
  fallbackName = 'project.ocep',
): Promise<{ filename: string; sizeBytes: number }> {
  const res = await fetch(`/api${PROJECTS_BASE}/${projectId}/export/`, {
    method: 'POST',
    headers: { ...Object.fromEntries(buildAuthHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // not JSON — keep statusText
    }
    throw new Error(detail || `Export failed (${res.status})`);
  }
  // Pull filename from Content-Disposition.
  const cd = res.headers.get('content-disposition') || '';
  const match = cd.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] ?? fallbackName;

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.style.display = 'none';
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 1000);
  return { filename, sizeBytes: blob.size };
}

/**
 * Save a bearer-protected file URL by fetching it WITH the Authorization
 * header and downloading the resulting blob.
 *
 * The file download endpoints (`/documents/*`, `/bim_hub/*`,
 * `/dwg-takeoff/*`) authenticate with the JWT bearer token, which lives in
 * localStorage, not a cookie. A plain `<a href download>`, `window.open`, or
 * an `<iframe src>` is a top-level browser navigation that does NOT carry the
 * Authorization header, so the request 401s ("Not authenticated") and the
 * user sees a "log in / file not available" error. Routing the download
 * through `fetch` lets us attach the header and hand the browser a blob.
 */
export async function downloadProtectedFile(url: string, filename: string): Promise<void> {
  const res = await fetch(url, { headers: buildAuthHeaders() });
  if (!res.ok) {
    let detail = `Download failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  a.rel = 'noopener';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    a.remove();
    URL.revokeObjectURL(objectUrl);
  }, 1000);
}

/**
 * Fetch a bearer-protected file and return an object URL for inline preview
 * (e.g. a PDF `<iframe>`). The caller owns the returned URL and MUST revoke
 * it with `URL.revokeObjectURL` when the preview unmounts. Returns null on
 * any failure so the caller can fall back to an icon instead of a broken
 * frame.
 */
export async function fetchProtectedObjectUrl(url: string): Promise<string | null> {
  try {
    const res = await fetch(url, { headers: buildAuthHeaders() });
    if (!res.ok) return null;
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  } catch {
    return null;
  }
}

export async function validateImport(file: File): Promise<ImportPreview> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`/api${PROJECTS_BASE}/import/validate/`, {
    method: 'POST',
    headers: buildAuthHeaders(),
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Bundle is invalid (${res.status})`);
  }
  return (await res.json()) as ImportPreview;
}

export async function commitImport(opts: {
  file: File;
  mode: ImportMode;
  targetProjectId?: string;
  newProjectName?: string;
}): Promise<ImportResult> {
  const form = new FormData();
  form.append('file', opts.file);
  form.append('mode', opts.mode);
  if (opts.targetProjectId) form.append('target_project_id', opts.targetProjectId);
  if (opts.newProjectName) form.append('new_project_name', opts.newProjectName);
  const res = await fetch(`/api${PROJECTS_BASE}/import/`, {
    method: 'POST',
    headers: buildAuthHeaders(),
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Import failed (${res.status})`);
  }
  return (await res.json()) as ImportResult;
}

export async function mintEmailLink(
  fileId: string,
  ttlHours = 72,
): Promise<EmailLinkResponse> {
  return apiPost<EmailLinkResponse, void>(
    `${PROJECTS_BASE}/files/${fileId}/email-link/?ttl_hours=${ttlHours}`,
  );
}

/* ── Password-protected share links ──────────────────────────────────── */

const DOCUMENTS_BASE = '/v1/documents';

/** Mint a new share link for the given document. */
export async function createShareLink(
  documentId: string,
  payload: ShareLinkCreatePayload,
): Promise<ShareLinkResponse> {
  return apiPost<ShareLinkResponse, ShareLinkCreatePayload>(
    `${DOCUMENTS_BASE}/${documentId}/share-links/`,
    payload,
  );
}

/** List active (non-revoked) share links for a document. Owner-only. */
export async function listShareLinks(
  documentId: string,
): Promise<ShareLinkResponse[]> {
  return apiGet<ShareLinkResponse[]>(
    `${DOCUMENTS_BASE}/${documentId}/share-links/`,
  );
}

/** Soft-revoke a share link. Owner-only. */
export async function revokeShareLink(
  documentId: string,
  linkId: string,
): Promise<void> {
  const res = await fetch(
    `/api${DOCUMENTS_BASE}/${documentId}/share-links/${linkId}/`,
    {
      method: 'DELETE',
      headers: buildAuthHeaders(),
    },
  );
  if (!res.ok && res.status !== 204) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Revoke failed (${res.status})`);
  }
}

/* ── Public (unauthenticated) endpoints used by /share/:token ────────── */

/** Recipient-facing probe — returns filename + flags. No auth required. */
export async function fetchShareLinkInfo(
  token: string,
): Promise<ShareLinkPublicInfo> {
  const res = await fetch(`/api${DOCUMENTS_BASE}/share-links/${token}/`, {
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Link not found (${res.status})`);
  }
  return (await res.json()) as ShareLinkPublicInfo;
}

/* ── Folder permissions (owner-only) ─────────────────────────────────── */

/** List all non-revoked folder permissions for a project. */
export async function listFolderPermissions(
  projectId: string,
  filters: { scope_kind?: string; scope_path?: string | null } = {},
): Promise<FolderPermissionRow[]> {
  const params = new URLSearchParams();
  if (filters.scope_kind) params.set('scope_kind', filters.scope_kind);
  if (filters.scope_path) params.set('scope_path', filters.scope_path);
  const qs = params.toString();
  const path = `${PROJECTS_BASE}/${projectId}/folder-permissions/${qs ? `?${qs}` : ''}`;
  return apiGet<FolderPermissionRow[]>(path);
}

/** Grant viewer / editor / owner role to a member on a (kind, path) folder. */
export async function grantFolderPermission(
  projectId: string,
  payload: FolderPermissionCreatePayload,
): Promise<FolderPermissionRow> {
  return apiPost<FolderPermissionRow, FolderPermissionCreatePayload>(
    `${PROJECTS_BASE}/${projectId}/folder-permissions/`,
    payload,
  );
}

/** Soft-revoke a folder grant by id. */
export async function revokeFolderPermission(
  projectId: string,
  permissionId: string,
): Promise<void> {
  const res = await fetch(
    `/api${PROJECTS_BASE}/${projectId}/folder-permissions/${permissionId}/`,
    {
      method: 'DELETE',
      headers: buildAuthHeaders(),
    },
  );
  if (!res.ok && res.status !== 204) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Revoke failed (${res.status})`);
  }
}

/* ── Public (unauthenticated) endpoints used by /share/:token ────────── */

/** Submit the password (if any), receive the authenticated download URL. */
export async function accessShareLink(
  token: string,
  password?: string,
): Promise<ShareLinkAccessResponse> {
  const res = await fetch(
    `/api${DOCUMENTS_BASE}/share-links/${token}/access/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ password: password ?? null }),
    },
  );
  if (res.status === 401) {
    throw new Error('UNAUTHORIZED');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Access failed (${res.status})`);
  }
  return (await res.json()) as ShareLinkAccessResponse;
}

/* ── Per-user favourites / pins ──────────────────────────────────────── */

const FAVORITES_BASE = '/v1/file-favorites';

/** List the current user's favourites for a project (pinned first). */
export async function fetchFavorites(
  projectId: string,
  opts: { onlyPinned?: boolean } = {},
): Promise<FileFavorite[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (opts.onlyPinned) params.set('only_pinned', 'true');
  return apiGet<FileFavorite[]>(`${FAVORITES_BASE}/?${params.toString()}`);
}

/** Star (or update the pin flag of) a file for the current user.
 * Idempotent on ``(file_kind, file_id)`` — posting twice flips the pin. */
export async function starFile(
  projectId: string,
  kind: FileKind,
  fileId: string,
  pinned = false,
): Promise<FileFavorite> {
  return apiPost<FileFavorite, {
    project_id: string;
    file_kind: FileKind;
    file_id: string;
    pinned: boolean;
  }>(`${FAVORITES_BASE}/`, {
    project_id: projectId,
    file_kind: kind,
    file_id: fileId,
    pinned,
  });
}

/** Remove a favourite. Idempotent — a missing row still resolves. */
export async function unstarFile(
  projectId: string,
  kind: FileKind,
  fileId: string,
): Promise<void> {
  const params = new URLSearchParams({
    project_id: projectId,
    file_kind: kind,
    file_id: fileId,
  });
  await apiDelete(`${FAVORITES_BASE}/?${params.toString()}`);
}

/* ── Document lifecycle (CDE) state ──────────────────────────────────── */

/** The ISO 19650 / BS 1192 lifecycle states a document can be set to. */
export type CdeState = 'wip' | 'shared' | 'published' | 'archived';

/** Subset of the document response we care about after a metadata patch. */
export interface DocumentPatchResponse {
  id: string;
  cde_state: CdeState | null;
  category: string | null;
  name: string;
}

/** Promote / demote a document's CDE lifecycle state.
 *
 * Backed by ``PATCH /v1/documents/{id}``. The documents module already
 * accepts a ``cde_state`` of wip / shared / published / archived. Only the
 * ``document`` kind is backed by that table, so callers must guard on kind
 * before invoking. The file manager rows surface the current value via
 * ``row.extra.cde_state``.
 */
export async function setDocumentCdeState(
  documentId: string,
  cdeState: CdeState,
): Promise<DocumentPatchResponse> {
  return apiPatch<DocumentPatchResponse, { cde_state: CdeState }>(
    `${DOCUMENTS_BASE}/${documentId}`,
    { cde_state: cdeState },
  );
}

/** Rename a document via ``PATCH /v1/documents/{id}``.
 *
 * The documents module's ``DocumentUpdate`` schema already accepts a
 * ``name`` field (1-255 chars, whitespace-stripped). Only the ``document``
 * kind is backed by that table, so callers must guard on
 * ``kind === 'document'`` before invoking. The file manager rows surface
 * the current value via ``row.name``.
 */
export async function renameDocument(
  documentId: string,
  name: string,
): Promise<DocumentPatchResponse> {
  return apiPatch<DocumentPatchResponse, { name: string }>(
    `${DOCUMENTS_BASE}/${documentId}`,
    { name },
  );
}

/* ── Drawing sheets ──────────────────────────────────────────────────── */

/**
 * Split a multi-page drawing set into one sheet row per page.
 *
 * Backed by ``POST /v1/documents/sheets/split-pdf/``, which stores the PDF as
 * a project document and then walks it page by page: the sheet number, title,
 * revision and scale are read out of the page text, the discipline comes from
 * the number prefix, and a thumbnail is rendered per page. Returns the rows it
 * created, which is what the register lists.
 *
 * Sent as raw multipart rather than through ``apiPost`` for two reasons: the
 * browser has to own the multipart boundary, and a full drawing set takes far
 * longer to split than the JSON client's 45s abort allows.
 */
export async function splitPdfIntoSheets(
  projectId: string,
  file: File,
): Promise<SheetRow[]> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(
    `/api${DOCUMENTS_BASE}/sheets/split-pdf/?project_id=${encodeURIComponent(projectId)}`,
    {
      method: 'POST',
      headers: buildAuthHeaders(),
      body: form,
    },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Split failed (${res.status})`);
  }
  return (await res.json()) as SheetRow[];
}

/* ── Per-kind delete helpers (bulk-delete dispatcher) ────────────────── */

/** Bulk-delete response shape returned by /v1/documents/batch/delete/.
 *
 *  `references` reports what the delete severed, the same shape the batch
 *  references endpoint returns. */
export interface BulkDeleteResponse {
  requested: number;
  deleted: number;
  references?: DocumentBatchReferences;
}

/** Outcome of a single per-kind delete pass. */
export interface KindDeleteOutcome {
  kind: FileKind;
  requested: number;
  deleted: number;
  errors: { id: string; message: string }[];
}

/** Per-id DELETE for a single file row. Falls back to per-id loops when
 * the receiving module exposes no batch endpoint. Errors bubble so the
 * dispatcher can record a per-id failure entry.
 */
export async function deleteByKind(kind: FileKind, fileId: string): Promise<void> {
  const path = deletePathForKind(kind, fileId);
  await apiDelete(path);
}

/** Bulk-delete documents through the existing module-side batch endpoint.
 *
 *  The server answers 409 (and deletes nothing) while any selected document is
 *  still pointed at by a row the delete would strand or unlink. Pass
 *  `acknowledgeReferences` only after the person has been shown that report,
 *  e.g. through `BulkDeleteReferencesWarning`. */
export async function bulkDeleteDocuments(
  ids: string[],
  acknowledgeReferences = false,
): Promise<BulkDeleteResponse> {
  return apiPost<BulkDeleteResponse, { ids: string[]; acknowledge_references: boolean }>(
    '/v1/documents/batch/delete/',
    { ids, acknowledge_references: acknowledgeReferences },
  );
}

/** Build the canonical DELETE path for one file kind + id. Exported so
 * tests and the dispatcher share the same routing table.
 */
export function deletePathForKind(kind: FileKind, fileId: string): string {
  const enc = encodeURIComponent(fileId);
  switch (kind) {
    case 'document':
      return `/v1/documents/${enc}`;
    case 'photo':
      return `/v1/documents/photos/${enc}`;
    case 'sheet':
      return `/v1/documents/sheets/${enc}`;
    case 'bim_model':
      return `/v1/bim_hub/${enc}`;
    case 'dwg_drawing':
      return `/v1/dwg_takeoff/drawings/${enc}`;
    case 'takeoff':
      return `/v1/takeoff/documents/${enc}`;
    case 'report':
      return `/v1/reporting/reports/${enc}`;
    case 'markup':
      return `/v1/markups/${enc}`;
  }
}

/** The fields of a sheet the detail panel can correct. Mirrors `SheetUpdate`;
 *  `null` clears a field, an absent key leaves it alone. */
export interface SheetPatch {
  sheet_number?: string | null;
  sheet_title?: string | null;
  discipline?: string | null;
  revision?: string | null;
  revision_date?: string | null;
  scale?: string | null;
}

/**
 * Correct a sheet's title block fields.
 *
 * Backed by ``PATCH /v1/documents/sheets/{id}``. A changed number or revision
 * makes the backend restack the sheet, which can flip ``is_current`` on this
 * row and on its neighbours, so the caller refetches the register rather than
 * patching its cache by hand.
 */
export async function updateSheet(sheetId: string, patch: SheetPatch): Promise<SheetRow> {
  return apiPatch<SheetRow, SheetPatch>(`${DOCUMENTS_BASE}/sheets/${sheetId}`, patch);
}

/** What re-reading a project's title blocks changed. Mirrors `SheetRereadSummary`. */
export interface SheetRereadSummary {
  sheets_checked: number;
  sheets_updated: number;
  fields_updated: number;
  files_missing: number;
  /** Sheets whose current state was set by hand against the revision order; the hand setting was kept. */
  current_conflicts: string[];
}

/**
 * Read every sheet's title block again from the PDF the register already holds.
 *
 * Backed by ``POST /v1/documents/sheets/reread-title-blocks/``. Fields corrected
 * by hand are left alone; the revision stacks are rebuilt, so the caller
 * refetches the register.
 */
export async function rereadTitleBlocks(projectId: string): Promise<SheetRereadSummary> {
  return apiPost<SheetRereadSummary, void>(
    `${DOCUMENTS_BASE}/sheets/reread-title-blocks/?project_id=${encodeURIComponent(projectId)}`,
  );
}
