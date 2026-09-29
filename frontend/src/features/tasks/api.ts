// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Tasks.
 *
 * All endpoints are prefixed with /v1/tasks/.
 */

import {
  apiGet,
  apiPost,
  apiPatch,
  triggerDownload,
  extractErrorMessageFromBody,
  type Page,
} from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** Built-in task types. Custom category strings are also supported. */
export type BuiltinTaskType = 'task' | 'topic' | 'information' | 'decision' | 'personal';
export type TaskType = BuiltinTaskType | (string & {});
export type TaskStatus = 'draft' | 'open' | 'in_progress' | 'completed';
export type TaskPriority = 'low' | 'normal' | 'high' | 'urgent';

/** Checklist item shape — mirrors the backend `ChecklistItemEntry`
 *  schema exactly (`{id, text, completed}`). The backend never emits
 *  `label`/`checked`, so consuming those keys silently yields 0%
 *  progress. */
export interface ChecklistItem {
  id: string | null;
  text: string;
  completed: boolean;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  /** Nullable on the wire — `TaskResponse.description` is `str | None`. */
  description: string | null;
  task_type: TaskType;
  status: TaskStatus;
  priority: TaskPriority;
  /** Canonical assignee column on the backend. `assigned_to` is a
   *  read-only alias the API also returns. */
  responsible_id: string | null;
  assigned_to: string | null;
  assigned_to_name: string | null;
  due_date: string | null;
  checklist: ChecklistItem[];
  /** Server-computed checklist completion (0.0 - 100.0). */
  checklist_progress: number;
  created_by: string | null;
  meeting_id: string | null;
  metadata: Record<string, unknown>;
  /** Spatial pin to BIM elements (v1.3.30+).  Empty array when the task
   *  isn't linked to any 3D geometry. */
  bim_element_ids?: string[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  /** Server-computed: status != completed AND due_date strictly before
   *  today (UTC). Authoritative — do NOT recompute client-side, the
   *  naive `new Date(due_date) < new Date()` flags same-day tasks. */
  is_overdue: boolean;
}

export interface TaskFilters {
  project_id?: string;
  task_type?: TaskType | '';
  status?: TaskStatus | '';
  /** Filter by assignee UUID. Maps to the backend `responsible_id`
   *  query param. */
  responsible_id?: string;
}

export interface CreateTaskPayload {
  project_id: string;
  title: string;
  description?: string;
  task_type?: TaskType;
  priority?: TaskPriority;
  responsible_id?: string;
  due_date?: string;
  /** Spatially pin the new task to one or more BIM elements. The backend
   *  added this column in v1.3.30; passing the field on create avoids the
   *  follow-up PATCH /tasks/{id}/bim-links round-trip. */
  bim_element_ids?: string[];
  /** Free-form metadata stored alongside the task row. Used by the DWG
   *  takeoff page to pin a task to `dwg_drawing_id` + `dwg_entity_ids`
   *  without a dedicated backend column. */
  metadata?: Record<string, unknown>;
  /** Assign a contact. The server links its platform user, if it has one,
   *  as `responsible_id` and keeps the contact's name in the metadata. */
  assignee_contact_id?: string;
}

export interface UpdateTaskPayload {
  title?: string;
  description?: string;
  task_type?: TaskType;
  status?: TaskStatus;
  priority?: TaskPriority;
  /** Backend column is `responsible_id`. The old `assigned_to` key was
   *  silently ignored by the Pydantic `TaskUpdate` model, so assignee
   *  edits never persisted. */
  responsible_id?: string | null;
  due_date?: string | null;
  /** Free-form metadata (e.g. `{ assignee_name }` for typed, non-UUID
   *  assignees). Sent so editing a task doesn't wipe a typed name. */
  metadata?: Record<string, unknown>;
  /** See CreateTaskPayload. `null` drops the contact link. */
  assignee_contact_id?: string | null;
  checklist?: { id?: string | null; text: string; completed: boolean }[];
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchTasks(filters?: TaskFilters): Promise<Page<Task>> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.task_type) params.set('type', filters.task_type);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.responsible_id) params.set('responsible_id', filters.responsible_id);
  const qs = params.toString();
  /* Unconditional `?`. check_page_envelope_consumers.py binds a URL literal
     to the call it stands next to and its pattern stops at the first
     whitespace, so the conditional suffix this used to carry hid the route
     from it entirely. An empty query after a `?` parses as no query. */
  return apiGet<Page<Task>>(`/v1/tasks/?${qs}`);
}

/**
 * Tasks assigned to (or created by) the current user, across all
 * projects. The backend resolves the user from the JWT `sub` claim, so
 * this is the correct "My Tasks" source — the client cannot reliably
 * self-filter because it doesn't carry the user UUID.
 */
export async function fetchMyTasks(status?: TaskStatus): Promise<Page<Task>> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  const qs = params.toString();
  return apiGet<Page<Task>>(`/v1/tasks/my-tasks/?${qs}`);
}

export async function createTask(data: CreateTaskPayload): Promise<Task> {
  return apiPost<Task>('/v1/tasks/', data);
}

export async function updateTask(id: string, data: UpdateTaskPayload): Promise<Task> {
  return apiPatch<Task>(`/v1/tasks/${id}`, data);
}

export async function completeTask(id: string): Promise<Task> {
  return apiPost<Task>(`/v1/tasks/${id}/complete/`);
}

export async function deleteTask(id: string): Promise<void> {
  const { apiDelete } = await import('@/shared/lib/api');
  return apiDelete(`/v1/tasks/${id}`);
}

export async function exportTasks(projectId: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(
    `/api/v1/tasks/export/?project_id=${encodeURIComponent(projectId)}`,
    { method: 'GET', headers },
  );
  if (!response.ok) {
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || 'tasks_export.xlsx';
  triggerDownload(blob, filename);
}
