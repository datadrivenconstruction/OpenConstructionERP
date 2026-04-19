/**
 * API helpers for Meetings.
 *
 * All endpoints are prefixed with /v1/meetings/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* -- Types ----------------------------------------------------------------- */

export type MeetingType =
  | 'progress'
  | 'design'
  | 'safety'
  | 'subcontractor'
  | 'kickoff'
  | 'closeout';

export type MeetingStatus = 'scheduled' | 'in_progress' | 'completed' | 'cancelled';

export type AttendeeStatus = 'present' | 'absent' | 'excused';

export interface Attendee {
  id: string;
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
  status: MeetingStatus;
  attendees: Attendee[];
  agenda_items: AgendaItem[];
  action_items: ActionItem[];
  notes: string;
  minutes?: string | null;
  document_ids: string[];
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
  location?: string;
  chairperson_id?: string;
  attendees?: { name: string; company?: string; status?: string }[];
  minutes?: string;
  document_ids?: string[];
}

export interface UpdateMeetingPayload {
  title?: string;
  meeting_type?: MeetingType;
  meeting_date?: string;
  location?: string;
  chairperson_id?: string;
  attendees?: { name: string; company?: string; status?: string }[];
  minutes?: string;
  document_ids?: string[];
  status?: MeetingStatus;
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
};

function normaliseMeeting(m: MeetingWire): Meeting {
  const date = m.date ?? m.meeting_date ?? '';
  const chairperson = m.chairperson ?? m.chairperson_id ?? '';
  const attendees: Attendee[] = (m.attendees ?? []).map((a, i) => ({
    id: a.id ?? a.user_id ?? `att-${i}`,
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
      if (body?.detail) detail = body.detail;
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

  const url =
    `/api/v1/meetings/import-summary?project_id=${encodeURIComponent(projectId)}` +
    (preview ? '&preview=true' : '');

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: formData,
  });

  if (!response.ok) {
    let detail = 'Import failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
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
