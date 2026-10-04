// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Photo Gallery.
 *
 * All photo endpoints are prefixed with /v1/documents/photos/.
 */

import { apiGet, apiPatch, apiPost, apiDelete, type Page } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type PhotoCategory = 'site' | 'progress' | 'defect' | 'delivery' | 'safety' | 'aerial' | 'other';

export interface PhotoItem {
  id: string;
  project_id: string;
  document_id: string | null;
  filename: string;
  caption: string | null;
  gps_lat: number | null;
  gps_lon: number | null;
  tags: string[];
  taken_at: string | null;
  category: PhotoCategory;
  metadata: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
  /** True when a server-side thumbnail is available. Grid renders should
   *  prefer `getPhotoThumbUrl(id)`; fall back to the full file for the
   *  lightbox view or when this flag is false. */
  has_thumbnail?: boolean;
}

/**
 * A day of site photos, as the timeline view renders it.
 *
 * Built on the client by {@link groupPhotosByDay} from the photo page the
 * timeline route returns. The server used to group, which left it answering
 * with a list of days that could not say how many photos it had cut.
 */
export interface PhotoTimelineGroup {
  /** `YYYY-MM-DD`, the capture day (upload day when EXIF carried none). */
  date: string;
  photos: PhotoItem[];
}

/**
 * Group a photo page into days, newest day first.
 *
 * The key is the leading ten characters of `taken_at`, falling back to
 * `created_at` - a string cut, not a `Date`, so a timestamp the server wrote
 * without a zone cannot be re-read in the browser's zone and land on the day
 * before. Photos keep the order they arrived in inside their day.
 */
export function groupPhotosByDay(photos: PhotoItem[]): PhotoTimelineGroup[] {
  const byDay = new Map<string, PhotoItem[]>();
  for (const photo of photos) {
    const day = (photo.taken_at ?? photo.created_at ?? '').slice(0, 10);
    const bucket = byDay.get(day);
    if (bucket) bucket.push(photo);
    else byDay.set(day, [photo]);
  }
  return [...byDay.entries()]
    .sort((a, b) => (a[0] < b[0] ? 1 : a[0] > b[0] ? -1 : 0))
    .map(([date, dayPhotos]) => ({ date, photos: dayPhotos }));
}

export type DefectSeverity = 'low' | 'medium' | 'high';

/** AI / heuristic category suggestion stored in a photo's `metadata` on
 *  upload. NEVER auto-applied — the user confirms it in the gallery. */
export interface PhotoCategorySuggestion {
  suggested_category: PhotoCategory;
  /** 0..1 model probability, or null when a heuristic with no score. */
  confidence: number | null;
  /** 'ai' (vision model) or 'heuristic' (deterministic keyword match). */
  source: 'ai' | 'heuristic';
  /** Short lower-case auto-tags the model saw (vision only). Empty when none. */
  suggested_tags: string[];
  /** Severity rating for a suggested `defect` photo, or null otherwise. */
  defect_severity: DefectSeverity | null;
}

/** Read the category suggestion out of a photo's metadata blob, if present
 *  and well-formed. Returns null otherwise so callers can guard cleanly. */
export function getCategorySuggestion(photo: PhotoItem): PhotoCategorySuggestion | null {
  const raw = photo.metadata?.['category_suggestion'];
  if (!raw || typeof raw !== 'object') return null;
  const rec = raw as Record<string, unknown>;
  const cat = rec['suggested_category'];
  const validCats: readonly string[] = ['site', 'progress', 'defect', 'delivery', 'safety', 'aerial', 'other'];
  if (typeof cat !== 'string' || !validCats.includes(cat)) return null;
  const conf = rec['confidence'];
  const src = rec['source'];
  const rawTags = rec['suggested_tags'];
  const tags = Array.isArray(rawTags)
    ? rawTags.filter((x): x is string => typeof x === 'string')
    : [];
  const sev = rec['defect_severity'];
  const validSev: readonly string[] = ['low', 'medium', 'high'];
  return {
    suggested_category: cat as PhotoCategory,
    confidence: typeof conf === 'number' ? conf : null,
    source: src === 'ai' ? 'ai' : 'heuristic',
    suggested_tags: tags,
    defect_severity:
      typeof sev === 'string' && validSev.includes(sev) ? (sev as DefectSeverity) : null,
  };
}

/** True when the photo's GPS was auto-filled from EXIF on upload. */
export function isGpsFromExif(photo: PhotoItem): boolean {
  return photo.metadata?.['gps_source'] === 'exif';
}

/** True when the photo's capture date was auto-filled from EXIF on upload. */
export function isDateFromExif(photo: PhotoItem): boolean {
  return photo.metadata?.['taken_at_source'] === 'exif';
}

export interface PhotoFilters {
  category?: PhotoCategory | '';
  tag?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
}

export interface PhotoUpdatePayload {
  caption?: string;
  tags?: string[];
  category?: PhotoCategory;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

/**
 * One page of the project's site photos.
 *
 * The server default is 100 photos and a job site produces more than that in
 * a week, so the envelope travels to the caller: `total` is how many photos
 * the filters matched, `items` is the page. See the route's own note on
 * `tag`, which it narrows in Python after counting.
 */
export async function fetchPhotos(
  projectId: string,
  filters?: PhotoFilters,
): Promise<Page<PhotoItem>> {
  if (!projectId) return { items: [], total: 0, offset: 0, limit: 0 };
  const params = new URLSearchParams({ project_id: projectId });
  if (filters?.category) params.set('category', filters.category);
  if (filters?.tag) params.set('tag', filters.tag);
  if (filters?.date_from) params.set('date_from', filters.date_from);
  if (filters?.date_to) params.set('date_to', filters.date_to);
  if (filters?.search) params.set('search', filters.search);
  return apiGet<Page<PhotoItem>>(`/v1/documents/photos/?${params.toString()}`);
}

/*
 * `fetchPhotoGallery` used to sit here, reading GET /v1/documents/photos/gallery/.
 * That route answered with character-for-character the same body as the
 * timeline one below, and nothing in this app ever called this helper. Both
 * are gone; use `fetchPhotoTimeline` for either surface.
 */

/**
 * The photos behind the timeline view, newest first.
 *
 * Same page shape as the gallery: the route stopped grouping by day, because
 * a list of days cannot report how many photos it left out. Group it with
 * {@link groupPhotosByDay}.
 */
export async function fetchPhotoTimeline(projectId: string): Promise<Page<PhotoItem>> {
  if (!projectId) return { items: [], total: 0, offset: 0, limit: 0 };
  return apiGet<Page<PhotoItem>>(`/v1/documents/photos/timeline/?project_id=${projectId}`);
}

export async function fetchPhoto(id: string): Promise<PhotoItem> {
  return apiGet<PhotoItem>(`/v1/documents/photos/${id}`);
}

export function getPhotoFileUrl(id: string): string {
  // Trailing slash is required: the backend route is
  // ``/photos/{id}/file/`` and the API runs with redirect_slashes off,
  // so the slashless form 404s and the full-size view never loads.
  return `/api/v1/documents/photos/${id}/file/`;
}

/** Thumbnail endpoint. Falls back to the full file server-side when no
 *  thumbnail exists, so callers can use this unconditionally. */
export function getPhotoThumbUrl(id: string): string {
  return `/api/v1/documents/photos/${id}/thumb/`;
}

export async function uploadPhoto(
  projectId: string,
  file: File,
  metadata: {
    category?: string;
    caption?: string;
    gps_lat?: number;
    gps_lon?: number;
    tags?: string[];
    taken_at?: string;
  },
): Promise<PhotoItem> {
  if (!projectId) throw new Error('projectId is required');
  const formData = new FormData();
  formData.append('file', file);
  if (metadata.category) formData.append('category', metadata.category);
  if (metadata.caption) formData.append('caption', metadata.caption);
  if (metadata.gps_lat != null) formData.append('gps_lat', String(metadata.gps_lat));
  if (metadata.gps_lon != null) formData.append('gps_lon', String(metadata.gps_lon));
  if (metadata.tags?.length) formData.append('tags', metadata.tags.join(','));
  if (metadata.taken_at) formData.append('taken_at', metadata.taken_at);

  const token = useAuthStore.getState().accessToken;
  const res = await fetch(`/api/v1/documents/photos/upload/?project_id=${projectId}`, {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-DDC-Client': 'OE/1.0',
    },
    body: formData,
  });
  if (!res.ok) {
    let detail = 'Upload failed';
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

export async function updatePhoto(id: string, data: PhotoUpdatePayload): Promise<PhotoItem> {
  return apiPatch<PhotoItem>(`/v1/documents/photos/${id}`, data);
}

export async function deletePhoto(id: string): Promise<void> {
  return apiDelete(`/v1/documents/photos/${id}`);
}

/* ── General documents (non-photo) ─────────────────────────────────────── */

export interface DocumentItem {
  id: string;
  project_id: string;
  /** Original filename, e.g. "A_book_of_house_plans.pdf". The backend
   *  serialises this as ``name`` (CDE document model); it is NOT ``filename``.
   *  An earlier version of this type guessed ``filename``/``size_bytes`` and
   *  every read came back undefined, which crashed the Geo "Place on map"
   *  picker on ``name.toLowerCase()``. Keep these aligned to the API. */
  name: string;
  description: string | null;
  category: string;
  file_size: number;
  mime_type: string | null;
  version: number;
  is_current_revision: boolean;
  parent_document_id: string | null;
  drawing_number?: string | null;
  revision_code?: string | null;
  discipline?: string | null;
  suitability_code?: string | null;
  cde_state?: string | null;
  security_classification?: string | null;
  tags?: string[];
  metadata?: Record<string, unknown>;
  uploaded_by: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * One page of the project's document register.
 *
 * Returns the envelope rather than the rows because the server answers with
 * its first 50 documents by default, and a caller handed an array of 50 has
 * no way to find out whether that is the register or the start of it. Callers
 * that only need the rows read `.items`, but then they own the notice: mount
 * `TruncationNotice` with this page so the reader is told what they are
 * looking at.
 *
 * An empty project id yields an empty page rather than a request, which is
 * what the old array-returning version did too.
 */
export async function fetchDocuments(projectId: string): Promise<Page<DocumentItem>> {
  if (!projectId) return { items: [], total: 0, offset: 0, limit: 0 };
  return apiGet<Page<DocumentItem>>(`/v1/documents/?project_id=${projectId}`);
}

export async function uploadDocument(
  projectId: string,
  file: File,
  category: string = 'other',
): Promise<DocumentItem> {
  if (!projectId) throw new Error('projectId is required');
  const formData = new FormData();
  formData.append('file', file);
  const token = useAuthStore.getState().accessToken;
  const res = await fetch(
    `/api/v1/documents/upload/?project_id=${projectId}&category=${encodeURIComponent(category)}`,
    {
      method: 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        'X-DDC-Client': 'OE/1.0',
      },
      body: formData,
    },
  );
  if (!res.ok) {
    let detail = 'Upload failed';
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

export async function deleteDocument(id: string): Promise<void> {
  return apiDelete(`/v1/documents/${id}`);
}

/** How badly a module's hold on a document survives the document.
 *
 *  `strands`  the referring column is NOT NULL, so the row cannot record
 *             that the document went away and is left pointing at nothing.
 *  `unlinks`  the row survives and loses its attachment.
 *  `retains`  the row is meant to outlive the document (append-only audit,
 *             or a copy the module already keeps for itself). */
export type DocumentReferenceImpact = 'strands' | 'unlinks' | 'retains';

export interface DocumentReferenceItem {
  key: string;
  module: string;
  model: string;
  impact: DocumentReferenceImpact;
  count: number;
}

export interface DocumentReferences {
  document_id: string;
  total: number;
  strands: number;
  unlinks: number;
  retains: number;
  references: DocumentReferenceItem[];
}

/** What still points at a document, for the delete confirmation.
 *
 *  Advisory only: the delete endpoint neither consults this nor is blocked by
 *  it. Several of these links are documented as deliberately severable, so
 *  the decision stays with the person confirming - the point is that they
 *  make it knowing. */
export async function fetchDocumentReferences(id: string): Promise<DocumentReferences> {
  return apiGet<DocumentReferences>(`/v1/documents/${id}/references`);
}

/** What still points at any document of a selection, for a bulk delete.
 *
 *  `total`/`strands`/`unlinks`/`retains` and `references` are summed over the
 *  selection; `documents` holds the per-document answers for the documents
 *  something points at, heaviest first. `checked` is how many of the asked-for
 *  ids the caller may open and were looked at - ids outside it are neither
 *  counted nor named. */
export interface DocumentBatchReferences {
  checked: number;
  referenced_documents: number;
  total: number;
  strands: number;
  unlinks: number;
  retains: number;
  references: DocumentReferenceItem[];
  documents: DocumentReferences[];
}

export async function fetchBatchDocumentReferences(ids: string[]): Promise<DocumentBatchReferences> {
  return apiPost<DocumentBatchReferences, { ids: string[] }>('/v1/documents/batch/references/', { ids });
}

/** Download a stored document's bytes as a Blob (auth-aware).
 *
 *  Used by the Geo Hub "Place on map" picker, which re-uploads a stored
 *  PDF drawing as a map raster overlay. ``apiGet`` only deals in JSON, so
 *  we hand-roll the fetch with the same auth + client headers. */
export async function downloadDocumentBlob(id: string): Promise<Blob> {
  const token = useAuthStore.getState().accessToken;
  const res = await fetch(`/api/v1/documents/${id}/download`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-DDC-Client': 'OE/1.0',
    },
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  return res.blob();
}

/** Epic C — upload a NEW revision of an existing document.
 *
 *  Hits ``POST /api/v1/documents/{id}/revisions/``. The chain key stays
 *  anchored to the existing document's name so the file-versions
 *  dropdown shows V01, V02, V03 … sequentially regardless of what the
 *  user names the incoming file.
 */
export async function uploadDocumentRevision(
  documentId: string,
  file: File,
  notes?: string | null,
): Promise<DocumentItem> {
  if (!documentId) throw new Error('documentId is required');
  const formData = new FormData();
  formData.append('file', file);
  if (notes) formData.append('notes', notes);
  const token = useAuthStore.getState().accessToken;
  const res = await fetch(`/api/v1/documents/${documentId}/revisions/`, {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-DDC-Client': 'OE/1.0',
    },
    body: formData,
  });
  if (!res.ok) {
    let detail = 'Revision upload failed';
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}
