/**
 * API helpers for the Daily Site Diary module.
 *
 * Backed by /api/v1/daily-diary/ — see backend/app/modules/daily_diary/router.py
 */

import {
  apiGet,
  apiPost,
  apiPatch,
  apiDelete,
  getAuthToken,
  triggerDownload,
} from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type DiaryStatus = 'open' | 'closed' | 'signed' | 'archived';
export type EntryType =
  | 'visitor'
  | 'event'
  | 'delivery'
  | 'completion'
  | 'incident_summary'
  | 'inspection_summary'
  | 'photo_note'
  | 'general';
export type WeatherSource = 'open_meteo' | 'manual' | 'sensor';
export type CaptureType = 'laser_scan' | 'photogrammetry' | 'mobile_scan';
export type SignerRole = 'owner' | 'supervisor' | 'inspector' | 'client';

export interface DailyDiary {
  id: string;
  project_id: string;
  diary_date: string;
  site_supervisor_id?: string | null;
  weather_summary: Record<string, unknown>;
  labour_count: number;
  equipment_count: number;
  status: DiaryStatus;
  notes?: string | null;
  closed_at?: string | null;
  closed_by?: string | null;
  owner_signature_ref?: string | null;
  supervisor_signature_ref?: string | null;
  pdf_export_ref?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WeatherRecord {
  id: string;
  project_id: string;
  captured_at: string;
  source: WeatherSource;
  temperature_c?: string | number | null;
  humidity_pct?: string | number | null;
  wind_speed_kmh?: string | number | null;
  precipitation_mm?: string | number | null;
  conditions_code?: string | null;
  conditions_text?: string | null;
  sunrise?: string | null;
  sunset?: string | null;
  location_lat?: number | null;
  location_lng?: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DiaryEntry {
  id: string;
  diary_id: string;
  entry_type: EntryType;
  entry_time: string;
  title: string;
  description?: string | null;
  source_module?: string | null;
  source_ref?: string | null;
  author_id?: string | null;
  photo_ids: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DiaryPhoto {
  id: string;
  diary_id?: string | null;
  project_id: string;
  taken_at: string;
  photographer_id?: string | null;
  lat?: number | null;
  lng?: number | null;
  location_label?: string | null;
  file_url: string;
  thumbnail_url?: string | null;
  mime_type: string;
  file_size_bytes: number;
  description?: string | null;
  tags: string[];
  is_360: boolean;
  is_drone: boolean;
  is_archived: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DroneSurvey {
  id: string;
  project_id: string;
  flown_at: string;
  pilot_name?: string | null;
  drone_model?: string | null;
  area_m2?: string | number | null;
  ortho_file_url?: string | null;
  dsm_file_url?: string | null;
  point_cloud_url?: string | null;
  elevation_min_m?: string | number | null;
  elevation_max_m?: string | number | null;
  notes?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface RealityCapture {
  id: string;
  project_id: string;
  captured_at: string;
  capture_type: CaptureType;
  file_url: string;
  point_count_estimate?: number | null;
  bbox_min?: Record<string, number> | null;
  bbox_max?: Record<string, number> | null;
  accuracy_mm?: string | number | null;
  notes?: string | null;
  linked_bim_model_ref?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DiaryArchiveSignature {
  id: string;
  diary_id: string;
  content_sha256: string;
  signed_at: string;
  signed_by?: string | null;
  signature_payload: Record<string, unknown>;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface DiaryDashboard {
  total_diaries: number;
  open_count: number;
  closed_count: number;
  signed_count: number;
  archived_count: number;
  photos_total: number;
  drone_surveys_total: number;
  reality_captures_total: number;
  diaries_by_date: Record<string, number>;
}

export interface DiaryCompleteness {
  diary_id: string;
  /** 0.0 to 1.0 — server returns a Decimal serialised as a string. */
  completeness: string | number;
  /** Translation tokens for the blocks still missing, e.g. ["weather", "photos"]. */
  missing: string[];
}

export interface WorkforceSummary {
  diary_id: string;
  project_id: string;
  diary_date: string;
  labour_count: number;
  equipment_count: number;
  by_company: Record<string, number>;
}

export interface WeatherFetchResult {
  project_id: string;
  target_date: string;
  fetched: boolean;
  record_id?: string | null;
  summary: Record<string, unknown>;
}

export interface SclBundleManifest {
  project_id: string;
  date_from: string;
  date_to: string;
  diary_count: number;
  weather_record_count: number;
  photo_count: number;
  drone_survey_count: number;
  bundle_sha256: string;
  contents: Record<string, unknown>[];
}

export interface ExifGps {
  found: boolean;
  lat?: number | null;
  lng?: number | null;
  altitude_m?: number | null;
  timestamp?: string | null;
}

/* ── Diaries ───────────────────────────────────────────────────────────── */

export function listDiaries(params: {
  project_id: string;
  date_from?: string;
  date_to?: string;
  status?: string;
  limit?: number;
}): Promise<DailyDiary[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<DailyDiary[]>(`/v1/daily-diary/diaries/?${qs.toString()}`);
}

export function createDiary(data: {
  project_id: string;
  diary_date: string;
  notes?: string;
  labour_count?: number;
  equipment_count?: number;
}): Promise<DailyDiary> {
  return apiPost<DailyDiary>('/v1/daily-diary/diaries/', data);
}

export function getDiary(id: string): Promise<DailyDiary> {
  return apiGet<DailyDiary>(`/v1/daily-diary/diaries/${id}`);
}

export function deleteDiary(id: string): Promise<void> {
  // Backend exposes DELETE /api/v1/daily-diary/diaries/{id} (204) gated by
  // the `daily_diary.delete` permission. UI surfaces are not wiring this
  // yet — exposed here so admin / cleanup tooling can call it without
  // re-implementing the URL.
  return apiDelete(`/v1/daily-diary/diaries/${id}`);
}

export function updateDiary(
  id: string,
  data: { notes?: string; labour_count?: number; equipment_count?: number },
): Promise<DailyDiary> {
  return apiPatch<DailyDiary>(`/v1/daily-diary/diaries/${id}`, data);
}

export function closeDiary(id: string): Promise<DailyDiary> {
  return apiPost<DailyDiary>(`/v1/daily-diary/diaries/${id}/close`, {});
}

export function signDiary(
  id: string,
  data: { signer_role: SignerRole; signer_name?: string },
): Promise<DiaryArchiveSignature> {
  return apiPost<DiaryArchiveSignature>(
    `/v1/daily-diary/diaries/${id}/sign`,
    data,
  );
}

export function archiveDiary(id: string): Promise<DailyDiary> {
  return apiPost<DailyDiary>(`/v1/daily-diary/diaries/${id}/archive`, {});
}

/**
 * Re-open a signed diary so a manager can amend it.
 *
 * Hits POST /api/v1/daily-diary/diaries/{id}/unlock (gated by the
 * `daily_diary.unlock` permission). The original archive signature is
 * preserved server-side so the integrity break stays forensic and
 * traceable. An archived diary cannot be unlocked (409).
 */
export function unlockDiary(id: string, reason?: string): Promise<DailyDiary> {
  const qs = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  return apiPost<DailyDiary>(`/v1/daily-diary/diaries/${id}/unlock${qs}`, {});
}

export function diaryDashboard(projectId: string): Promise<DiaryDashboard> {
  return apiGet<DiaryDashboard>(
    `/v1/daily-diary/dashboard?project_id=${encodeURIComponent(projectId)}`,
  );
}

export function diaryCompleteness(diaryId: string): Promise<DiaryCompleteness> {
  return apiGet<DiaryCompleteness>(
    `/v1/daily-diary/diaries/${encodeURIComponent(diaryId)}/completeness`,
  );
}

export function diaryWorkforceSummary(
  diaryId: string,
): Promise<WorkforceSummary> {
  return apiGet<WorkforceSummary>(
    `/v1/daily-diary/diaries/${encodeURIComponent(diaryId)}/workforce-summary`,
  );
}

/**
 * Build a hash-sealed SCL Protocol contemporary-record bundle manifest for
 * the project over a date range. Backed by POST /exports/scl-bundle
 * (gated by `daily_diary.export_scl_bundle`).
 */
export function exportSclBundle(data: {
  project_id: string;
  date_from: string;
  date_to: string;
}): Promise<SclBundleManifest> {
  return apiPost<SclBundleManifest>('/v1/daily-diary/exports/scl-bundle', data);
}

/**
 * Download a diary as a PDF document.
 *
 * Hits GET /api/v1/daily-diary/diaries/{id}/pdf (returns application/pdf,
 * gated by the `daily_diary.read` permission) with the stored bearer token,
 * then streams the response to the browser as a file download. Mirrors the
 * blob-download pattern used by the BOQ export.
 *
 * @throws Error when the request fails so the caller can surface a toast.
 */
export async function downloadDiaryPdf(
  diaryId: string,
  diaryDate?: string,
): Promise<void> {
  const token = getAuthToken();
  const res = await fetch(
    `/api/v1/daily-diary/diaries/${encodeURIComponent(diaryId)}/pdf`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) {
    let message = `Export failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) message = String(body.detail);
    } catch {
      // Non-JSON error body — keep the status-code message.
    }
    throw new Error(message);
  }
  const blob = await res.blob();
  triggerDownload(blob, `diary-${diaryDate || diaryId}.pdf`);
}

/* ── Weather ───────────────────────────────────────────────────────────── */

export function weatherToday(
  projectId: string,
  day?: string,
): Promise<WeatherRecord[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', projectId);
  if (day) qs.set('day', day);
  return apiGet<WeatherRecord[]>(
    `/v1/daily-diary/weather/today?${qs.toString()}`,
  );
}

export function createWeather(data: {
  project_id: string;
  captured_at: string;
  source?: WeatherSource;
  temperature_c?: string;
  humidity_pct?: string;
  wind_speed_kmh?: string;
  precipitation_mm?: string;
  conditions_text?: string;
}): Promise<WeatherRecord> {
  return apiPost<WeatherRecord>('/v1/daily-diary/weather-records/', data);
}

/**
 * Fetch real weather from Open-Meteo for (project, date, coords) and persist
 * it as a WeatherRecord. Backed by POST /weather/fetch (gated by
 * `daily_diary.fetch_weather`).
 */
export function fetchWeather(data: {
  project_id: string;
  target_date: string;
  lat: number;
  lng: number;
  persist?: boolean;
}): Promise<WeatherFetchResult> {
  return apiPost<WeatherFetchResult>('/v1/daily-diary/weather/fetch', data);
}

/* ── Entries ───────────────────────────────────────────────────────────── */

export function listEntries(diaryId: string): Promise<DiaryEntry[]> {
  return apiGet<DiaryEntry[]>(
    `/v1/daily-diary/diaries/${encodeURIComponent(diaryId)}/entries`,
  );
}

export function createEntry(data: {
  diary_id: string;
  entry_type: EntryType;
  entry_time: string;
  title?: string;
  description?: string;
  // Optional provenance link to the upstream record this entry summarises
  // (e.g. a safety incident or a quality inspection). The backend
  // DiaryEntryCreate schema already accepts both fields.
  source_module?: string;
  source_ref?: string;
}): Promise<DiaryEntry> {
  return apiPost<DiaryEntry>('/v1/daily-diary/diary-entries/', data);
}

export function deleteEntry(id: string): Promise<void> {
  return apiDelete(`/v1/daily-diary/diary-entries/${id}`);
}

/* ── Photos ────────────────────────────────────────────────────────────── */

export function listPhotos(params: {
  project_id: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
}): Promise<DiaryPhoto[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<DiaryPhoto[]>(`/v1/daily-diary/photos/?${qs.toString()}`);
}

/**
 * Register a diary photo. The binary lives in object storage; this records
 * its URL + metadata. Backed by POST /diary-photos/ (gated by
 * `daily_diary.upload_photo`).
 */
export function createPhoto(data: {
  project_id: string;
  diary_id?: string | null;
  taken_at: string;
  file_url: string;
  thumbnail_url?: string | null;
  mime_type?: string;
  location_label?: string | null;
  lat?: number | null;
  lng?: number | null;
  description?: string | null;
  is_drone?: boolean;
}): Promise<DiaryPhoto> {
  return apiPost<DiaryPhoto>('/v1/daily-diary/diary-photos/', data);
}

/**
 * Extract GPS coordinates from a base64-encoded image's EXIF metadata.
 * Backed by POST /photos/extract-gps (magic-byte gated, gated by
 * `daily_diary.upload_photo`). Used to prefill lat/lng on photo upload.
 */
export function extractPhotoGps(imageBase64: string): Promise<ExifGps> {
  return apiPost<ExifGps>('/v1/daily-diary/photos/extract-gps', {
    image_base64: imageBase64,
  });
}

/* ── Drone surveys ─────────────────────────────────────────────────────── */

export function listDroneSurveys(projectId: string): Promise<DroneSurvey[]> {
  return apiGet<DroneSurvey[]>(
    `/v1/daily-diary/drone-surveys/?project_id=${encodeURIComponent(
      projectId,
    )}`,
  );
}

/**
 * Attach a drone survey to the project. Backed by POST /drone-surveys/
 * (gated by `daily_diary.attach_drone`).
 */
export function createDroneSurvey(data: {
  project_id: string;
  flown_at: string;
  drone_model?: string | null;
  pilot_name?: string | null;
  area_m2?: string | null;
  ortho_file_url?: string | null;
  point_cloud_url?: string | null;
  notes?: string | null;
}): Promise<DroneSurvey> {
  return apiPost<DroneSurvey>('/v1/daily-diary/drone-surveys/', data);
}

/* ── Reality captures ──────────────────────────────────────────────────── */

export function listRealityCaptures(
  projectId: string,
): Promise<RealityCapture[]> {
  return apiGet<RealityCapture[]>(
    `/v1/daily-diary/reality-captures/?project_id=${encodeURIComponent(
      projectId,
    )}`,
  );
}

/**
 * Attach a reality-capture dataset (laser scan / photogrammetry / mobile
 * scan) to the project. Backed by POST /reality-captures/ (gated by
 * `daily_diary.attach_reality_capture`).
 */
export function createRealityCapture(data: {
  project_id: string;
  captured_at: string;
  capture_type: CaptureType;
  file_url: string;
  point_count_estimate?: number | null;
  accuracy_mm?: string | null;
  notes?: string | null;
}): Promise<RealityCapture> {
  return apiPost<RealityCapture>('/v1/daily-diary/reality-captures/', data);
}

/* ── Archive signatures ────────────────────────────────────────────────── */

export function listArchiveSignatures(
  diaryId: string,
): Promise<DiaryArchiveSignature[]> {
  return apiGet<DiaryArchiveSignature[]>(
    `/v1/daily-diary/archive-signatures/?diary_id=${encodeURIComponent(
      diaryId,
    )}`,
  );
}
