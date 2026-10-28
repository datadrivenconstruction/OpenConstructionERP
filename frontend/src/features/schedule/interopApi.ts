// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// API for three schedule interop features: the progress sheet round-trip,
// scheduling profiles with attributed recalculation, and the stored source of
// an imported schedule. All routes live under /api/v1/schedule.

import type { Page } from '@/shared/lib/apiHelpers';
import { apiDelete, apiGet, apiPatch, apiPost, apiPut, API_BASE, getAuthToken } from '@/shared/lib/api';


/* ── Scheduling profiles ──────────────────────────────────────────────── */

export type ProgressMode = 'retained_logic' | 'progress_override' | 'actual_dates';
export type LagCalendar = 'elapsed' | 'predecessor' | 'successor' | 'project';
export type OpenEnds = 'project_finish' | 'own_finish';
export type CriticalRule = 'total_float' | 'longest_path';

export interface ProfileSettings {
  progress_mode: ProgressMode;
  lag_calendar: LagCalendar;
  open_ends: OpenEnds;
  critical_rule: CriticalRule;
  critical_float_threshold: number;
}

export interface SchedulingProfile extends ProfileSettings {
  id: string;
  project_id: string;
  name: string;
  description: string;
  is_default: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export type ProfileDraft = ProfileSettings & { name: string; description: string; is_default: boolean };

export interface EffectiveProfile {
  schedule_id: string;
  profile_id: string | null;
  profile_name: string | null;
  source: 'schedule' | 'project_default' | 'builtin';
  settings: ProfileSettings;
}

/** Setting keys a recalculated activity can be attributed to. */
export type ChangeCause =
  | 'progress_mode'
  | 'lag_calendar'
  | 'status'
  | 'open_ends'
  | 'critical_rule'
  | 'critical_float_threshold';

export interface RecalculatedActivity {
  activity_id: string;
  activity_code: string | null;
  name: string;
  current_start: string | null;
  current_end: string | null;
  new_start: string;
  new_end: string;
  start_shift_days: number;
  finish_shift_days: number;
  total_float: number;
  was_critical: boolean;
  is_critical: boolean;
  completed: boolean;
  started: boolean;
  out_of_sequence: boolean;
  on_longest_path: boolean;
  open_start: boolean;
  open_finish: boolean;
  changed_by: ChangeCause[];
}

export interface RecalculateResult {
  schedule_id: string;
  applied: boolean;
  profile_id: string | null;
  profile_name: string | null;
  source: EffectiveProfile['source'];
  settings: ProfileSettings;
  data_date: string | null;
  current_finish: string | null;
  new_finish: string | null;
  changed_count: number;
  critical_count: number;
  out_of_sequence_count: number;
  open_end_count: number;
  setting_effects: Partial<Record<ChangeCause, number>>;
  activities: RecalculatedActivity[];
}

export const DEFAULT_PROFILE_SETTINGS: ProfileSettings = {
  progress_mode: 'retained_logic',
  lag_calendar: 'elapsed',
  open_ends: 'project_finish',
  critical_rule: 'total_float',
  critical_float_threshold: 0,
};

/* ── Progress sheet ───────────────────────────────────────────────────── */

export interface ProgressSheetFilters {
  wbs?: string;
  assigneeId?: string;
  dateFrom?: string;
  dateTo?: string;
  includeCompleted?: boolean;
  locale?: string;
}

export interface FieldChange {
  old: string | number | null;
  new: string | number | null;
}

export interface SheetIssue {
  rule_id: string;
  code: string;
  severity: 'error' | 'warning' | 'info' | string;
  message: string;
}

export interface SheetPreviewRow {
  row_number: number;
  activity_id: string | null;
  activity_code: string | null;
  name: string | null;
  changes: Record<string, FieldChange>;
  issues: SheetIssue[];
  stale: boolean;
  has_errors: boolean;
  applicable: boolean;
}

export interface SheetPreview {
  schedule_id: string;
  filename: string;
  sha256: string;
  exported_at: string | null;
  exported_data_date: string | null;
  status_date: string;
  row_count: number;
  changed_count: number;
  error_count: number;
  stale_count: number;
  rows: SheetPreviewRow[];
}

export interface SheetApplyResult {
  schedule_id: string;
  batch_id: string;
  status_date: string;
  applied_count: number;
  applied_activity_ids: string[];
  skipped: { row_number: number; activity_id: string | null; code: string }[];
  data_date_advanced: boolean;
}

/* ── Import source ────────────────────────────────────────────────────── */

export interface ImportSourceRecord {
  format: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  document_id: string | null;
  document_issue: string | null;
  imported_at: string | null;
  imported_by: string | null;
  activity_count: number;
  status: 'pending_review' | 'accepted' | string;
  accepted_at: string | null;
  accepted_by: string | null;
}

export interface SourceComparisonRow {
  activity_id: string;
  activity_code: string | null;
  name: string;
  source_id: string | null;
  source_start: string | null;
  source_finish: string | null;
  source_duration_days: number | null;
  current_start: string | null;
  current_finish: string | null;
  current_duration_days: number | null;
  start_deviation_days: number | null;
  finish_deviation_days: number | null;
}

export interface SourceComparison {
  schedule_id: string;
  source: ImportSourceRecord;
  activity_count: number;
  deviating_count: number;
  max_finish_deviation_days: number;
  source_finish: string | null;
  current_finish: string | null;
  project_finish_deviation_days: number | null;
  activities: SourceComparisonRow[];
}

/* ── Transport helpers for files ──────────────────────────────────────── */

/** Error carrying the server's machine-readable code, when it sent one. */
export class InteropApiError extends Error {
  code: string | null;
  status: number;
  constructor(message: string, status: number, code: string | null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function authHeaders(json: boolean): Record<string, string> {
  const headers: Record<string, string> = { 'X-DDC-Client': 'OE/1.0' };
  if (json) headers['Accept'] = 'application/json';
  const token = getAuthToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

async function toError(res: Response): Promise<InteropApiError> {
  let message = `Request failed (${res.status})`;
  let code: string | null = null;
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === 'string') message = detail;
    else if (detail && typeof detail === 'object') {
      if (typeof detail.message === 'string') message = detail.message;
      if (typeof detail.code === 'string') code = detail.code;
    }
  } catch {
    /* not JSON */
  }
  return new InteropApiError(message, res.status, code);
}

function filenameFrom(res: Response, fallback: string): string {
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (star?.[1]) return decodeURIComponent(star[1]);
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain?.[1] ?? fallback;
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    a.remove();
    URL.revokeObjectURL(url);
  }, 1000);
}

async function readForm<T>(sent: Promise<Response>): Promise<T> {
  const res = await sent;
  if (!res.ok) throw await toError(res);
  return res.json() as Promise<T>;
}

/** Query string of the sheet filters (exported for tests). */
export function progressSheetQuery(filters: ProgressSheetFilters): string {
  const qs = new URLSearchParams();
  if (filters.wbs) qs.set('wbs', filters.wbs);
  if (filters.assigneeId) qs.set('assignee_id', filters.assigneeId);
  if (filters.dateFrom) qs.set('date_from', filters.dateFrom);
  if (filters.dateTo) qs.set('date_to', filters.dateTo);
  if (filters.includeCompleted) qs.set('include_completed', 'true');
  if (filters.locale) qs.set('locale', filters.locale);
  const s = qs.toString();
  return s ? `?${s}` : '';
}

export const interopApi = {
  /* Profiles */
  listProfiles: (projectId: string) =>
    apiGet<Page<SchedulingProfile>>(
      `/v1/schedule/scheduling-profiles/?project_id=${encodeURIComponent(projectId)}`,
    ).then((page) => page.items),
  createProfile: (projectId: string, draft: ProfileDraft) =>
    apiPost<SchedulingProfile>('/v1/schedule/scheduling-profiles/', { project_id: projectId, ...draft }),
  updateProfile: (profileId: string, draft: Partial<ProfileDraft>) =>
    apiPatch<SchedulingProfile>(`/v1/schedule/scheduling-profiles/${encodeURIComponent(profileId)}`, draft),
  deleteProfile: (profileId: string) =>
    apiDelete(`/v1/schedule/scheduling-profiles/${encodeURIComponent(profileId)}`),
  getScheduleProfile: (scheduleId: string) =>
    apiGet<EffectiveProfile>(`/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/scheduling-profile`),
  assignScheduleProfile: (scheduleId: string, profileId: string | null) =>
    apiPut<EffectiveProfile>(`/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/scheduling-profile`, {
      profile_id: profileId,
    }),
  previewRecalculation: (scheduleId: string, profileId: string | null) =>
    apiPost<RecalculateResult>(`/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/recalculate/preview`, {
      profile_id: profileId,
    }),
  applyRecalculation: (scheduleId: string, profileId: string | null) =>
    apiPost<RecalculateResult>(`/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/recalculate/apply`, {
      profile_id: profileId,
    }),

  /* Progress sheet */
  async downloadProgressSheet(scheduleId: string, filters: ProgressSheetFilters): Promise<number> {
    const res = await fetch(
      `${API_BASE}/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/progress-sheet${progressSheetQuery(filters)}`,
      { method: 'GET', headers: authHeaders(false) },
    );
    if (!res.ok) throw await toError(res);
    saveBlob(await res.blob(), filenameFrom(res, 'progress.xlsx'));
    return Number(res.headers.get('X-Row-Count') ?? 0);
  },
  previewProgressSheet(scheduleId: string, file: File, statusDate: string | null, locale?: string) {
    const form = new FormData();
    form.append('file', file);
    if (statusDate) form.append('status_date', statusDate);
    if (locale) form.append('locale', locale);
    return readForm<SheetPreview>(
      fetch(`${API_BASE}/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/progress-sheet/preview`, { method: 'POST', headers: authHeaders(true), body: form }),
    );
  },
  applyProgressSheet(
    scheduleId: string,
    file: File,
    body: { sha256: string; statusDate: string; rowNumbers: number[]; locale?: string },
  ) {
    const form = new FormData();
    form.append('file', file);
    form.append('expected_sha256', body.sha256);
    form.append('status_date', body.statusDate);
    form.append('row_numbers', JSON.stringify(body.rowNumbers));
    if (body.locale) form.append('locale', body.locale);
    return readForm<SheetApplyResult>(
      fetch(`${API_BASE}/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/progress-sheet/apply`, { method: 'POST', headers: authHeaders(true), body: form }),
    );
  },

  /* Import source */
  getImportSource: (scheduleId: string) =>
    apiGet<SourceComparison>(`/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/import-source`),
  acceptImportRecalculation: (scheduleId: string) =>
    apiPost<ImportSourceRecord>(`/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/import-source/accept`, {}),
  restoreImportSourceDates: (scheduleId: string) =>
    apiPost<{ schedule_id: string; moved: number }>(
      `/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/import-source/restore`,
      {},
    ),
};
