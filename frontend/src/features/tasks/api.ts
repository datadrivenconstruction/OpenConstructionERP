/**
 * API helpers for Tasks.
 *
 * All endpoints are prefixed with /v1/tasks/.
 */

import { apiGet, apiPost, apiPatch, triggerDownload } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type TaskType = 'task' | 'topic' | 'info' | 'decision' | 'personal';
export type TaskStatus = 'open' | 'in_progress' | 'completed';
export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent';

export interface ChecklistItem {
  id: string;
  label: string;
  checked: boolean;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string;
  task_type: TaskType;
  status: TaskStatus;
  priority: TaskPriority;
  assigned_to: string | null;
  assigned_to_name: string | null;
  due_date: string | null;
  checklist: ChecklistItem[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskFilters {
  project_id?: string;
  task_type?: TaskType | '';
  status?: TaskStatus | '';
  assigned_to?: string;
}

export interface CreateTaskPayload {
  project_id: string;
  title: string;
  description?: string;
  task_type?: TaskType;
  priority?: TaskPriority;
  assigned_to?: string;
  due_date?: string;
  checklist?: { label: string; checked: boolean }[];
}

export interface UpdateTaskPayload {
  title?: string;
  description?: string;
  task_type?: TaskType;
  status?: TaskStatus;
  priority?: TaskPriority;
  assigned_to?: string | null;
  due_date?: string | null;
  checklist?: { label: string; checked: boolean }[];
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchTasks(filters?: TaskFilters): Promise<Task[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.task_type) params.set('task_type', filters.task_type);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.assigned_to) params.set('assigned_to', filters.assigned_to);
  const qs = params.toString();
  return apiGet<Task[]>(`/v1/tasks${qs ? `?${qs}` : ''}`);
}

export async function createTask(data: CreateTaskPayload): Promise<Task> {
  return apiPost<Task>('/v1/tasks', data);
}

export async function updateTask(id: string, data: UpdateTaskPayload): Promise<Task> {
  return apiPatch<Task>(`/v1/tasks/${id}`, data);
}

export async function completeTask(id: string): Promise<Task> {
  return apiPost<Task>(`/v1/tasks/${id}/complete`);
}

export async function exportTasks(projectId: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(
    `/api/v1/tasks/export?project_id=${encodeURIComponent(projectId)}`,
    { method: 'GET', headers },
  );
  if (!response.ok) {
    let detail = 'Export failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
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
