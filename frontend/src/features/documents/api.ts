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
  return `/api/v1/documents/photos/${id}/file`;
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
  filename: string;
  size_bytes: number;
  mime_type: string | null;
  category: string;
  created_by: string | null;
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
