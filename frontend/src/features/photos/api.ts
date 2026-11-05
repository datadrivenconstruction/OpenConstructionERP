// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Photo archive API: one photo entity for every module, served by /api/v1/photos/.

import { apiDelete, apiGet, apiPatch, apiPost, fetchWithAuth, downloadWithAuth } from '@/shared/lib/api';
import type { DeviceCapture } from '@/shared/lib/photoEvidence';
import { filtersToQuery, type PhotoFilters } from './model';

export type TargetKind =
  | 'boq_position'
  | 'schedule_activity'
  | 'punch_item'
  | 'inspection'
  | 'field_report'
  | 'diary'
  | 'safety_obs'
  | 'location'
  | 'plan_pin';

export type AIKind = 'caption' | 'tags' | 'progress' | 'hazard';

export interface PhotoLink {
  id: string;
  photo_id: string;
  target_kind: TargetKind;
  target_id: string;
  created_by?: string | null;
  created_at?: string | null;
}

export interface ArchivePhoto {
  id: string;
  project_id: string;
  filename: string;
  caption: string | null;
  category: string;
  tags: string[];
  taken_at: string | null;
  created_at: string | null;
  created_by: string;
  gps_lat: number | null;
  gps_lon: number | null;
  gps_accuracy_m: number | null;
  width: number | null;
  height: number | null;
  sha256: string | null;
  source_module: string;
  source_id: string | null;
  category_suggestion?: Record<string, unknown> | null;
  thumb_status: 'pending' | 'ready' | 'failed' | 'skipped' | string;
  location_id: string | null;
  zone: string | null;
  is_archived: boolean;
  evidence_grade: 'full' | 'partial' | 'none' | string;
  taken_at_source: string | null;
  file_url: string;
  thumb_url: string;
  links: PhotoLink[];
}

export interface PhotoPage {
  items: ArchivePhoto[];
  next_cursor: string | null;
  total: number;
}

export interface UploadResult {
  items: ArchivePhoto[];
  errors: { filename: string; error: string }[];
}

export interface TimelineDay {
  date: string;
  count: number;
  undated: number;
  photos: ArchivePhoto[];
}

export interface PhotoFeature {
  type: 'Feature';
  id: string;
  geometry: { type: 'Point'; coordinates: [number, number] };
  properties: Record<string, unknown>;
}

export interface PhotoGeoJSON {
  type: 'FeatureCollection';
  features: PhotoFeature[];
  anchor?: { lat: number; lon: number } | null;
}

export interface Album {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  cover_photo_id: string | null;
  sort_order: number;
  photo_count: number;
  created_at: string | null;
}

export interface Compare {
  id: string;
  project_id: string;
  title: string;
  before: ArchivePhoto;
  after: ArchivePhoto;
  created_at: string | null;
}

export interface Suggestion {
  id: string;
  photo_id: string;
  kind: AIKind;
  payload: Record<string, unknown>;
  confidence: number;
  provider: string | null;
  model: string | null;
  status: 'pending' | 'accepted' | 'edited' | 'rejected';
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string | null;
}

export interface Pin {
  id: string;
  document_id: string;
  page: number;
  x: number;
  y: number;
  note: string | null;
  photo_ref: string | null;
}

export interface Job {
  job_id: string;
  status: string;
  kind: string;
}

export interface ExportStatus {
  job_id: string;
  status: string;
  progress_percent: number;
  photo_count: number | null;
  size_bytes: number | null;
  ready: boolean;
}

export interface ValidationReport {
  status: 'passed' | 'warnings' | 'errors' | string;
  score: number;
  findings: { rule_id: string; severity: string; message: string; element_ref?: string | null }[];
}


export const photosKeys = {
  all: ['photo-archive'] as const,
  list: (projectId: string, filters: PhotoFilters) => ['photo-archive', 'list', projectId, filters] as const,
  timeline: (projectId: string, filters: PhotoFilters) => ['photo-archive', 'timeline', projectId, filters] as const,
  map: (projectId: string, filters: PhotoFilters) => ['photo-archive', 'map', projectId, filters] as const,
  photo: (id: string) => ['photo-archive', 'photo', id] as const,
  byTarget: (projectId: string, kind: string, id: string) => ['photo-archive', 'by-target', projectId, kind, id] as const,
  albums: (projectId: string) => ['photo-archive', 'albums', projectId] as const,
  compares: (projectId: string) => ['photo-archive', 'compares', projectId] as const,
  compare: (id: string) => ['photo-archive', 'compare', id] as const,
  suggestions: (photoId: string) => ['photo-archive', 'ai', photoId] as const,
  pins: (photoId: string) => ['photo-archive', 'pins', photoId] as const,
  validation: (projectId: string) => ['photo-archive', 'validation', projectId] as const,
};

function withProject(projectId: string, query: string): string {
  const params = new URLSearchParams(query);
  params.set('project_id', projectId);
  return params.toString();
}

export function listPhotos(projectId: string, filters: PhotoFilters, cursor?: string | null, limit = 60) {
  const params = new URLSearchParams(withProject(projectId, filtersToQuery(filters)));
  params.set('limit', String(limit));
  if (cursor) params.set('cursor', cursor);
  return apiGet<PhotoPage>(`/v1/photos/?${params.toString()}`);
}

export const fetchTimeline = async (projectId: string, filters: PhotoFilters): Promise<TimelineDay[]> => {
  const params = new URLSearchParams(withProject(projectId, filtersToQuery(filters)));
  params.set('limit', '1000');
  return (await apiGet<{ items: TimelineDay[] }>(`/v1/photos/timeline/?${params.toString()}`)).items;
};

export const fetchMap = (projectId: string, filters: PhotoFilters) =>
  apiGet<PhotoGeoJSON>(`/v1/photos/map/?${withProject(projectId, filtersToQuery(filters))}`);

export const fetchPhoto = (id: string) => apiGet<ArchivePhoto>(`/v1/photos/${id}/`);

export const patchPhoto = (
  id: string,
  body: { caption?: string | null; category?: string; tags?: string[]; zone?: string | null },
) =>
  apiPatch<ArchivePhoto>(`/v1/photos/${id}/`, body);

export const deletePhoto = (id: string) => apiDelete<{ result: 'deleted' | 'archived' }>(`/v1/photos/${id}/`);

export const fetchByTarget = async (projectId: string, kind: string, id: string): Promise<ArchivePhoto[]> =>
  (
    await apiGet<{ items: ArchivePhoto[] }>(
      `/v1/photos/by-target/?project_id=${encodeURIComponent(projectId)}&kind=${encodeURIComponent(kind)}&id=${encodeURIComponent(id)}&limit=500`,
    )
  ).items;

export const addLink = (photoId: string, target_kind: TargetKind, target_id: string) =>
  apiPost<PhotoLink>(`/v1/photos/${photoId}/links/`, { target_kind, target_id });

export const removeLink = (photoId: string, target_kind: string, target_id: string) =>
  apiDelete(
    `/v1/photos/${photoId}/links/?target_kind=${encodeURIComponent(target_kind)}&target_id=${encodeURIComponent(target_id)}`,
  );

export const fetchAlbums = async (projectId: string): Promise<Album[]> =>
  (
    await apiGet<{ items: Album[]; total: number }>(
      `/v1/photos/albums/?project_id=${encodeURIComponent(projectId)}&limit=500`,
    )
  ).items;
export const createAlbum = (projectId: string, name: string, description?: string) =>
  apiPost<Album>(`/v1/photos/albums/`, { project_id: projectId, name, description: description || null });
export const renameAlbum = (id: string, body: { name?: string; description?: string | null; cover_photo_id?: string }) =>
  apiPatch<Album>(`/v1/photos/albums/${id}/`, body);
export const deleteAlbum = (id: string) => apiDelete(`/v1/photos/albums/${id}/`);
export const addToAlbum = (id: string, photo_ids: string[]) =>
  apiPost<{ added: number; photo_count: number }>(`/v1/photos/albums/${id}/items/`, { photo_ids });
export const removeFromAlbum = (id: string, photo_ids: string[]) =>
  apiPost<{ removed: number; photo_count: number }>(`/v1/photos/albums/${id}/items/remove/`, { photo_ids });

export const fetchCompares = async (projectId: string): Promise<Compare[]> =>
  (await apiGet<{ items: Compare[] }>(`/v1/photos/compare/?project_id=${encodeURIComponent(projectId)}&limit=500`)).items;
export const fetchCompare = (id: string) => apiGet<Compare>(`/v1/photos/compare/${id}/`);
export const createCompare = (projectId: string, before: string, after: string, title: string) =>
  apiPost<Compare>(`/v1/photos/compare/`, {
    project_id: projectId,
    before_photo_id: before,
    after_photo_id: after,
    title,
  });

export const analyzePhoto = (photoId: string, kinds: AIKind[]) =>
  apiPost<Job>(`/v1/photos/${photoId}/ai/analyze/?kinds=${kinds.join(',')}`);
export const fetchSuggestions = async (photoId: string): Promise<Suggestion[]> =>
  (await apiGet<{ items: Suggestion[] }>(`/v1/photos/${photoId}/ai/?limit=500`)).items;
export const acceptSuggestion = (id: string, payload?: Record<string, unknown>) =>
  apiPost<Suggestion>(`/v1/photos/ai/${id}/accept/`, payload ? { payload } : {});
export const rejectSuggestion = (id: string) => apiPost<Suggestion>(`/v1/photos/ai/${id}/reject/`);

export const fetchPins = async (photoId: string): Promise<Pin[]> =>
  (await apiGet<{ items: Pin[] }>(`/v1/photos/${photoId}/pins/?limit=500`)).items;

export const startExport = (projectId: string, opts: { photo_ids?: string[]; album_id?: string }) =>
  apiPost<Job>(`/v1/photos/export/`, { project_id: projectId, ...opts });
export const fetchExport = (jobId: string) => apiGet<ExportStatus>(`/v1/photos/export/${jobId}/`);
export const downloadExport = (jobId: string) =>
  downloadWithAuth(`/api/v1/photos/export/${jobId}/file/`, `photos-${jobId.slice(0, 8)}.zip`);

export const fetchValidation = (projectId: string) =>
  apiGet<ValidationReport>(`/v1/photos/validation/?project_id=${encodeURIComponent(projectId)}`);

/** Map the browser capture onto the `device` JSON the upload endpoint reads. */
export function deviceJson(capture: DeviceCapture | null | undefined): string | null {
  if (!capture) return null;
  const out: Record<string, unknown> = { captured_at: capture.capturedAt };
  if (Number.isFinite(capture.lat) && Number.isFinite(capture.lon)) {
    out.lat = capture.lat;
    out.lon = capture.lon;
    if (Number.isFinite(capture.accuracyM)) out.accuracy_m = capture.accuracyM;
  }
  if (Number.isFinite(capture.headingDeg)) out.heading_deg = capture.headingDeg;
  return JSON.stringify(out);
}

export async function uploadPhotos(
  projectId: string,
  files: File[],
  opts: { category?: string; caption?: string; tags?: string[]; device?: DeviceCapture | null; target?: { kind: TargetKind; id: string } },
): Promise<UploadResult> {
  const form = new FormData();
  for (const f of files) form.append('files', f);
  if (opts.category) form.append('category', opts.category);
  if (opts.caption) form.append('caption', opts.caption);
  if (opts.tags?.length) form.append('tags', opts.tags.join(','));
  const device = deviceJson(opts.device);
  if (device) form.append('device', device);
  if (opts.target) {
    form.append('target_kind', opts.target.kind);
    form.append('target_id', opts.target.id);
  }
  const res = await fetchWithAuth(`/api/v1/photos/upload/?project_id=${encodeURIComponent(projectId)}`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    let detail = '';
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = typeof body.detail === 'string' ? body.detail : '';
    } catch {
      /* body is not JSON */
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return (await res.json()) as UploadResult;
}
