// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Meetings.
 *
 * All endpoints are prefixed with /v1/meetings/.
 */

import {
  apiGet,
  apiPost,
  apiPatch,
  apiDelete,
  extractErrorMessageFromBody,
} from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* -- Types ----------------------------------------------------------------- */

// The vocabulary the backend validates against, in the order the pickers show
// it. Both the meetings page and the recurring-series dialog used to keep their
// own copy of this list, so a type could reach one dropdown and not the other.
// `commercial` is the cost side of a job - valuations, payment applications,
// variations and the monthly cost review.
export const MEETING_TYPES = [
  'progress',
  'design',
  'safety',
  'subcontractor',
  'kickoff',
  'closeout',
  'commercial',
] as const;

// Derived, not restated: a value that is in the list is in the type, and the
// `Record<MeetingType, ...>` maps below the pickers then fail the build until
// they carry an entry for it.
export type MeetingType = (typeof MEETING_TYPES)[number];

// draft is the state the API creates a meeting in when the caller does not name
// one, and the state machine only lets it move on to scheduled or cancelled.
// Leaving it out of this union did not stop the value arriving - it only stopped
// the page from having a label, a colour or a filter for it.
export type MeetingStatus = 'draft' | 'scheduled' | 'in_progress' | 'completed' | 'cancelled';

export type AttendeeStatus = 'present' | 'absent' | 'excused';

export interface Attendee {
  id: string;
  /** Contact id when this attendee was picked from the directory (links to it). */
  user_id?: string | null;
  name: string;
  role: string;
  status: AttendeeStatus;
}

export interface AgendaItem {
  id: string;
  title: string;
  presenter: string;
  duration_minutes: number;
  notes: string;
}

export interface ActionItem {
  id: string;
  description: string;
  owner: string;
  due_date: string;
  completed: boolean;
}

export interface Meeting {
  id: string;
  project_id: string;
  meeting_number: number;
  title: string;
  meeting_type: MeetingType;
  date: string;
  location: string;
  chairperson: string;
  /** Raw chairperson reference - a contact id when picked, else free text. */
  chairperson_id: string;
  status: MeetingStatus;
  attendees: Attendee[];
  agenda_items: AgendaItem[];
  action_items: ActionItem[];
  notes: string;
  minutes?: string | null;
  document_ids: string[];
  /** Recurring-series id (the master meeting id); null for a one-off meeting. */
  series_id?: string | null;
  is_series_master?: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface MeetingFilters {
  project_id?: string;
  meeting_type?: MeetingType | '';
  status?: MeetingStatus | '';
}

export interface CreateMeetingPayload {
  project_id: string;
  title: string;
  meeting_type: MeetingType;
  meeting_date: string;
  // Omitting this is not the same as not caring: the API defaults a new meeting
  // to draft, and a draft cannot be completed until something schedules it.
  // The form asks for a date, so what it collects is a scheduled meeting.
  status?: MeetingStatus;
  location?: string;
  chairperson_id?: string;
  attendees?: { name: string; user_id?: string; company?: string; status?: string }[];
  minutes?: string;
  document_ids?: string[];
  metadata?: Record<string, unknown>;
}

export interface UpdateMeetingPayload {
  title?: string;
  meeting_type?: MeetingType;
  meeting_date?: string;
  location?: string;
  chairperson_id?: string;
  attendees?: { name: string; user_id?: string; company?: string; status?: string }[];
  minutes?: string;
  document_ids?: string[];
  status?: MeetingStatus;
  metadata?: Record<string, unknown>;
}

/* -- Wire <-> UI normaliser ----------------------------------------------- */

type AttendeeWire = {
  id?: string;
  user_id?: string;
  name?: string;
  role?: string;
  company?: string;
  status?: AttendeeStatus;
};

type MeetingWire = Omit<Meeting, 'date' | 'chairperson' | 'attendees' | 'meeting_number'> & {
  date?: string;
  meeting_date?: string;
  chairperson?: string;
  chairperson_id?: string | null;
  attendees?: AttendeeWire[];
  meeting_number?: string | number;
  notes?: string;
  metadata?: Record<string, unknown> | null;
};

function normaliseMeeting(m: MeetingWire): Meeting {
  const date = m.date ?? m.meeting_date ?? '';
  const chairperson_id = m.chairperson_id ?? '';
  // The backend stores only chairperson_id; when a contact was picked we also
  // persist its display name in metadata so the UI shows a name, not a UUID.
  const metaName =
    (m.metadata as { chairperson_name?: string } | undefined)?.chairperson_name ?? '';
  const chairperson = m.chairperson ?? metaName ?? chairperson_id;
  const attendees: Attendee[] = (m.attendees ?? []).map((a, i) => ({
    id: a.id ?? a.user_id ?? `att-${i}`,
    user_id: a.user_id ?? null,
    name: a.name ?? '',
    role: a.role ?? a.company ?? '',
    status: (a.status ?? 'present') as AttendeeStatus,
  }));
  const meeting_number =
    typeof m.meeting_number === 'number'
      ? m.meeting_number
      : Number.parseInt(String(m.meeting_number ?? '').replace(/\D+/g, ''), 10) || 0;
  return {
    ...m,
    date,
    chairperson,
    chairperson_id,
    attendees,
    meeting_number,
    notes: m.notes ?? '',
  } as Meeting;
}

/* -- API Functions --------------------------------------------------------- */

export async function fetchMeetings(filters?: MeetingFilters): Promise<Meeting[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.meeting_type) params.set('meeting_type', filters.meeting_type);
  if (filters?.status) params.set('status', filters.status);
  // Raise from the server default cap (50) to its accepted ceiling (le=100) so
  // the KPI tiles (counted from list.length) and the client-side search cover
  // up to 100 records instead of silently dropping older rows.
  params.set('limit', '100');
  const qs = params.toString();
  const rows = await apiGet<MeetingWire[]>(`/v1/meetings/${qs ? `?${qs}` : ''}`);
  return rows.map(normaliseMeeting);
}

export async function createMeeting(data: CreateMeetingPayload): Promise<Meeting> {
  const row = await apiPost<MeetingWire>('/v1/meetings/', data);
  return normaliseMeeting(row);
}

export async function updateMeeting(
  id: string,
  data: UpdateMeetingPayload,
): Promise<Meeting> {
  const row = await apiPatch<MeetingWire>(`/v1/meetings/${id}`, data);
  return normaliseMeeting(row);
}

export async function deleteMeeting(id: string): Promise<void> {
  return apiDelete(`/v1/meetings/${id}`);
}

export async function completeMeeting(id: string): Promise<Meeting> {
  const row = await apiPost<MeetingWire>(`/v1/meetings/${id}/complete/`);
  return normaliseMeeting(row);
}

/* -- Meeting attachment upload (delegates to DocumentService) ------------- */

export interface MeetingAttachment {
  id: string;
  name: string;
  size: number;
  mime_type?: string | null;
}

export async function uploadMeetingDocument(
  projectId: string,
  file: File,
): Promise<MeetingAttachment> {
  if (!projectId) throw new Error('projectId is required');
  const token = useAuthStore.getState().accessToken;
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(
    `/api/v1/documents/upload/?project_id=${encodeURIComponent(projectId)}&category=meeting`,
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
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }
  const body = await res.json();
  return {
    id: String(body.id),
    name: String(body.name ?? body.filename ?? file.name),
    size: Number(body.file_size ?? body.size_bytes ?? file.size),
    mime_type: body.mime_type ?? file.type ?? null,
  };
}

export function getMeetingDocumentDownloadUrl(documentId: string): string {
  return `/api/v1/documents/${documentId}/download`;
}

export async function fetchMeetingDocument(
  documentId: string,
): Promise<MeetingAttachment> {
  const body = await apiGet<{
    id: string;
    name?: string;
    filename?: string;
    file_size?: number;
    size_bytes?: number;
    mime_type?: string | null;
  }>(`/v1/documents/${documentId}`);
  return {
    id: String(body.id),
    name: String(body.name ?? body.filename ?? documentId),
    size: Number(body.file_size ?? body.size_bytes ?? 0),
    mime_type: body.mime_type ?? null,
  };
}

/* -- Import Preview Types -------------------------------------------------- */

export interface ImportPreviewAttendee {
  name: string;
  company: string;
  role: string;
}

export interface ImportPreviewActionItem {
  description: string;
  owner: string;
  due_date: string | null;
}

export interface ImportPreviewDecision {
  decision: string;
  made_by: string;
}

export interface ImportPreviewResponse {
  title: string;
  meeting_type: MeetingType;
  source: string;
  summary: string;
  key_topics: string[];
  attendees: ImportPreviewAttendee[];
  action_items: ImportPreviewActionItem[];
  decisions: ImportPreviewDecision[];
  agenda_items: Array<{ topic: string; presenter: string | null; notes: string | null }>;
  minutes: string;
  ai_enhanced: boolean;
  segments_parsed: number;
}

/* -- Import Functions ----------------------------------------------------- */

async function _importSummaryRequest(
  projectId: string,
  file: File,
  preview: boolean,
): Promise<Response> {
  const token = useAuthStore.getState().accessToken;
  const formData = new FormData();
  formData.append('file', file);

  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const qs = preview ? '&preview=true' : '';
  const url = `/api/v1/meetings/import-summary/?project_id=${encodeURIComponent(projectId)}${qs}`;

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: formData,
  });

  if (!response.ok) {
    let detail = 'Import failed';
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  return response;
}

export async function importMeetingSummaryPreview(
  projectId: string,
  file: File,
): Promise<ImportPreviewResponse> {
  const response = await _importSummaryRequest(projectId, file, true);
  return response.json();
}

export async function importMeetingSummary(
  projectId: string,
  file: File,
): Promise<Meeting> {
  const response = await _importSummaryRequest(projectId, file, false);
  return response.json();
}

/* -- Recurring Series ----------------------------------------------------- */

export type RecurrenceFreq = 'DAILY' | 'WEEKLY' | 'MONTHLY';

export const WEEKDAY_TOKENS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as const;
export type WeekdayToken = (typeof WEEKDAY_TOKENS)[number];

export interface RecurrenceSpec {
  freq: RecurrenceFreq;
  byday: WeekdayToken[];
  count: number; // 1..52
}

export function buildRRule(spec: RecurrenceSpec): string {
  const parts: string[] = [`FREQ=${spec.freq}`];
  if (spec.freq === 'WEEKLY' && spec.byday.length > 0) {
    parts.push(`BYDAY=${spec.byday.join(',')}`);
  }
  parts.push(`COUNT=${Math.max(1, Math.min(52, spec.count))}`);
  return parts.join(';');
}

export interface CreateSeriesPayload {
  project_id: string;
  title: string;
  meeting_type: MeetingType;
  meeting_date: string; // YYYY-MM-DD
  location?: string;
  chairperson_id?: string;
  attendees?: { name: string; user_id?: string; company?: string; status?: string }[];
  minutes?: string;
  document_ids?: string[];
  status?: MeetingStatus;
  recurrence_rule: string;
  materialize_until?: string; // YYYY-MM-DD
}

export interface MeetingSeriesResponse {
  series_id: string;
  master: Meeting;
  occurrences: Meeting[];
}

export async function createSeries(
  data: CreateSeriesPayload,
): Promise<MeetingSeriesResponse> {
  const res = await apiPost<{
    series_id: string;
    master: MeetingWire;
    occurrences: MeetingWire[];
  }>('/v1/meetings/series/', data);
  return {
    series_id: res.series_id,
    master: normaliseMeeting(res.master),
    occurrences: (res.occurrences ?? []).map(normaliseMeeting),
  };
}

export async function materializeSeries(
  masterId: string,
  until: string,
): Promise<MeetingSeriesResponse> {
  const res = await apiPost<{
    series_id: string;
    master: MeetingWire;
    occurrences: MeetingWire[];
  }>(`/v1/meetings/series/${masterId}/materialize/`, { until });
  return {
    series_id: res.series_id,
    master: normaliseMeeting(res.master),
    occurrences: (res.occurrences ?? []).map(normaliseMeeting),
  };
}

/* -- Attendance Check-in -------------------------------------------------- */

export interface AttendanceRow {
  id: string;
  meeting_id: string;
  user_id: string | null;
  external_name: string | null;
  checked_in_at: string | null;
  signature_image_path: string | null;
  created_at: string;
  updated_at: string;
}

export async function checkIn(
  meetingId: string,
  signature_image_data?: string,
): Promise<AttendanceRow> {
  return apiPost<AttendanceRow>(`/v1/meetings/${meetingId}/check-in/`, {
    signature_image_data: signature_image_data ?? null,
  });
}

export async function recordExternalAttendee(
  meetingId: string,
  name: string,
  signature_image_data?: string,
): Promise<AttendanceRow> {
  return apiPost<AttendanceRow>(
    `/v1/meetings/${meetingId}/external-attendee/`,
    {
      name,
      signature_image_data: signature_image_data ?? null,
    },
  );
}

export async function getAttendance(meetingId: string): Promise<AttendanceRow[]> {
  return apiGet<AttendanceRow[]>(`/v1/meetings/${meetingId}/attendance/`);
}

/* -- Action register (carry-over across a series) ------------------------- */

export type ActionStatus = 'open' | 'in_progress' | 'done' | 'cancelled';

export const ACTION_STATUSES: ActionStatus[] = ['open', 'in_progress', 'done', 'cancelled'];

export interface ActionRegisterItem {
  id: string;
  project_id: string;
  series_id: string | null;
  origin_meeting_id: string;
  origin_meeting_number: string;
  origin_meeting_date: string | null;
  description: string;
  owner_id: string | null;
  owner_name: string | null;
  due_date: string | null;
  status: ActionStatus;
  overdue: boolean;
  brought_forward: boolean;
  closed_in_meeting_id: string | null;
  closed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MeetingActions {
  meeting_id: string;
  own: ActionRegisterItem[];
  brought_forward: ActionRegisterItem[];
}

export interface SeriesActionRegister {
  series_id: string | null;
  total: number;
  open: number;
  in_progress: number;
  done: number;
  cancelled: number;
  overdue: number;
  actions: ActionRegisterItem[];
}

export interface CreateActionPayload {
  description: string;
  owner_id?: string | null;
  owner_name?: string | null;
  due_date?: string | null;
  status?: ActionStatus;
}

export interface UpdateActionPayload {
  description?: string;
  owner_id?: string | null;
  owner_name?: string | null;
  due_date?: string | null;
  status?: ActionStatus;
  closing_meeting_id?: string | null;
}

export async function fetchMeetingActions(meetingId: string): Promise<MeetingActions> {
  return apiGet<MeetingActions>(`/v1/meetings/${meetingId}/actions/`);
}

export async function addMeetingAction(
  meetingId: string,
  payload: CreateActionPayload,
): Promise<ActionRegisterItem> {
  return apiPost<ActionRegisterItem>(`/v1/meetings/${meetingId}/actions/`, payload);
}

export async function updateMeetingAction(
  actionId: string,
  payload: UpdateActionPayload,
): Promise<ActionRegisterItem> {
  return apiPatch<ActionRegisterItem>(`/v1/meetings/actions/${actionId}`, payload);
}

export async function deleteMeetingAction(actionId: string): Promise<void> {
  return apiDelete(`/v1/meetings/actions/${actionId}`);
}

export async function fetchSeriesActionRegister(seriesId: string): Promise<SeriesActionRegister> {
  return apiGet<SeriesActionRegister>(`/v1/meetings/series/${seriesId}/actions/`);
}

/* -- Auto-draft minutes --------------------------------------------------- */

export type MinutesStatus = 'draft' | 'issued';

export interface MinutesAttendee {
  name: string;
  company: string;
}

export interface MinutesAgendaLine {
  number: string;
  topic: string;
  presenter: string;
  discussion: string;
  decision: string;
  required: boolean;
}

export interface MinutesActionLine {
  description: string;
  owner: string;
  due_date: string | null;
  status: string;
  overdue: boolean;
  brought_forward: boolean;
  origin_meeting_number: string;
}

export interface MinutesContent {
  title: string;
  meeting_number: string;
  meeting_type: string;
  meeting_date: string | null;
  location: string;
  chairperson: string;
  attendees_present: MinutesAttendee[];
  attendees_absent: MinutesAttendee[];
  agenda: MinutesAgendaLine[];
  action_items: MinutesActionLine[];
  decisions: string[];
  /** Questions left open, confirmed from a recording. */
  open_questions?: string[];
  next_meeting_date: string | null;
  summary: string;
  /** ISO 639-1 language of the meeting; the PDF prints its labels in it. */
  language?: string | null;
  generated_at: string | null;
}

export interface Minutes {
  id: string;
  project_id: string;
  meeting_id: string;
  status: MinutesStatus;
  content: MinutesContent;
  next_meeting_date: string | null;
  issued_at: string | null;
  issued_by: string | null;
  distributed_at: string | null;
  distributed_to: string[];
  created_at: string;
  updated_at: string;
}

export interface GenerateMinutesPayload {
  next_meeting_date?: string;
  agenda?: Array<{
    number?: string;
    topic?: string;
    presenter?: string;
    discussion?: string;
    decision?: string;
    required?: boolean;
  }>;
  regenerate?: boolean;
}

export interface DistributeMinutesResult {
  minutes_id: string;
  recipients: number;
  notified_user_ids: string[];
}

/** GET the minutes for a meeting, returning ``null`` when none exist yet (404). */
export async function fetchMinutes(meetingId: string): Promise<Minutes | null> {
  const token = useAuthStore.getState().accessToken;
  const res = await fetch(`/api/v1/meetings/${meetingId}/minutes/`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-DDC-Client': 'OE/1.0',
    },
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    let detail = 'Failed to load minutes';
    try {
      detail = extractErrorMessageFromBody(await res.json()) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }
  return (await res.json()) as Minutes;
}

export async function generateMinutes(
  meetingId: string,
  payload: GenerateMinutesPayload = {},
): Promise<Minutes> {
  return apiPost<Minutes>(`/v1/meetings/${meetingId}/minutes/generate/`, payload);
}

export async function updateMinutes(
  meetingId: string,
  payload: { content?: MinutesContent; next_meeting_date?: string },
): Promise<Minutes> {
  return apiPatch<Minutes>(`/v1/meetings/${meetingId}/minutes/`, payload);
}

export async function issueMinutes(meetingId: string): Promise<Minutes> {
  return apiPost<Minutes>(`/v1/meetings/${meetingId}/minutes/issue/`);
}

export async function distributeMinutes(meetingId: string): Promise<DistributeMinutesResult> {
  return apiPost<DistributeMinutesResult>(`/v1/meetings/${meetingId}/minutes/distribute/`);
}

export function getMinutesPdfUrl(meetingId: string): string {
  return `/api/v1/meetings/${meetingId}/minutes/export/pdf/`;
}
