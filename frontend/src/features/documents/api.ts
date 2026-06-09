/**
 * API helpers for Photo Gallery.
 *
 * All photo endpoints are prefixed with /v1/documents/photos/.
 */

import { apiGet, apiPatch, apiDelete } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type PhotoCategory = 'site' | 'progress' | 'defect' | 'delivery' | 'safety' | 'other';

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

export interface PhotoTimelineGroup {
  date: string;
  photos: PhotoItem[];
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
  const validCats: readonly string[] = ['site', 'progress', 'defect', 'delivery', 'safety', 'other'];
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

export async function fetchPhotos(
  projectId: string,
  filters?: PhotoFilters,
): Promise<PhotoItem[]> {
  if (!projectId) return [];
  const params = new URLSearchParams({ project_id: projectId });
  if (filters?.category) params.set('category', filters.category);
  if (filters?.tag) params.set('tag', filters.tag);
  if (filters?.date_from) params.set('date_from', filters.date_from);
  if (filters?.date_to) params.set('date_to', filters.date_to);
  if (filters?.search) params.set('search', filters.search);
  return apiGet<PhotoItem[]>(`/v1/documents/photos/?${params.toString()}`);
}

export async function fetchPhotoGallery(projectId: string): Promise<PhotoItem[]> {
  if (!projectId) return [];
  return apiGet<PhotoItem[]>(`/v1/documents/photos/gallery/?project_id=${projectId}`);
}

export async function fetchPhotoTimeline(projectId: string): Promise<PhotoTimelineGroup[]> {
  if (!projectId) return [];
  return apiGet<PhotoTimelineGroup[]>(`/v1/documents/photos/timeline/?project_id=${projectId}`);
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

export async function fetchDocuments(projectId: string): Promise<DocumentItem[]> {
  if (!projectId) return [];
  return apiGet<DocumentItem[]>(`/v1/documents/?project_id=${projectId}`);
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
