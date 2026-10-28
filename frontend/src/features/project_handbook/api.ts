// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the project handbook and the data room of a project.
//
// Backend module: backend/app/modules/project_handbook/router.py, mounted at
// /api/v1/project_handbook/. Every project route lives under /projects/{project_id}/.
// Each call writes its full path as a literal, so the route check of the repo
// can compare it with the router, method included.
//
// Errors arrive as `detail = {code, message_key, message, violations?}`. The
// screens show the server's sentence for a refusal.

import { ApiError, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export type ChapterStatus = 'draft' | 'in_review' | 'approved' | 'revising';
export type ChapterAction = 'edit' | 'submit' | 'return' | 'approve';

/** One capability as the server decided it. `applies` is false when the action does not fit the state at all. */
export interface Can {
  allowed: boolean;
  reason: string | null;
  applies?: boolean;
}

export interface Chapter {
  id: string;
  code: string;
  area_code: string;
  folder_code: string;
  order: number;
  title: string;
  catalogue_title: string;
  title_key: string | null;
  required: boolean;
  sources: string[];
  owner_id: string | null;
  owner_name: string;
  content: string;
  status: ChapterStatus;
  draft_version: number;
  approved_version: number | null;
  submitted_by: string | null;
  submitted_by_name: string;
  submitted_at: string | null;
  approved_by: string | null;
  approved_by_name: string;
  approved_at: string | null;
  linked_rows: number | null;
  can?: Record<ChapterAction, Can>;
}

/** A record of another module as a chapter shows it: read live, never copied into the chapter. */
export interface LinkedRow {
  label: string;
  detail: string;
  label_key: string | null;
  group: string;
}

export interface LinkedSource {
  source: string;
  route: string;
  rows: LinkedRow[];
}

export interface ChapterVersion {
  version: number;
  title: string;
  content: string;
  owner_id: string | null;
  submitted_by: string | null;
  submitted_at: string | null;
  approved_by: string;
  approved_by_name: string;
  approved_at: string;
}

export interface ChapterDetail extends Chapter {
  linked: LinkedSource[];
  versions: ChapterVersion[];
}

export interface HandbookCounts {
  chapters: number;
  approved: number;
  in_review: number;
  required: number;
  required_approved: number;
}

export interface Handbook {
  id: string;
  project_id: string;
  title: string;
  edition: string;
  catalogue_source: string;
  catalogue_id: string;
  catalogue_version: number;
  chapters: Chapter[];
  counts: HandbookCounts;
}

export interface Finding {
  code: string;
  ref: string;
  severity: 'error' | 'warning';
  detail: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

/** A folder of the data room. A catalogue folder names itself by a locale key, a hand-made one by its text. */
export interface DataRoomFolder {
  id: string;
  code: string;
  parent_id: string | null;
  name: string;
  name_key: string | null;
  area_code: string;
  phase_code: string;
  source: 'catalogue' | 'manual';
  sort_order: number;
  documents: number;
  documents_total: number;
}

export interface DataRoom {
  folders: DataRoomFolder[];
  unfiled: number;
  documents: number;
}

export interface MaterialiseResult {
  created: number;
  updated: number;
  unchanged: number;
  folders: number;
}

export const handbookKeys = {
  project: (projectId: string) => ['project-handbook', projectId] as const,
  handbook: (projectId: string) => ['project-handbook', projectId, 'handbook'] as const,
  chapter: (projectId: string, code: string) => ['project-handbook', projectId, 'chapter', code] as const,
  findings: (projectId: string) => ['project-handbook', projectId, 'findings'] as const,
  dataRoom: (projectId: string) => ['project-handbook', projectId, 'data-room'] as const,
};

/* ── Errors ───────────────────────────────────────────────────────────── */

interface ErrorDetail {
  code?: unknown;
  message?: unknown;
}

function detailOf(err: unknown): ErrorDetail | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as ErrorDetail) : null;
}

/** The stable error code of a refusal, or null when the failure was not a handbook refusal. */
export function handbookErrorCode(err: unknown): string | null {
  const code = detailOf(err)?.code;
  return typeof code === 'string' ? code : null;
}

/** The sentence the server wrote for the refusal, already in the reader's language. */
export function handbookErrorMessage(err: unknown): string | null {
  const message = detailOf(err)?.message;
  return typeof message === 'string' && message.trim() ? message : null;
}

/* ── Handbook ─────────────────────────────────────────────────────────── */

export function getHandbook(projectId: string): Promise<Handbook> {
  return apiGet<Handbook>(`/v1/project_handbook/projects/${projectId}/handbook`);
}

export function createHandbook(projectId: string, body: { title: string; edition: string }): Promise<Handbook> {
  return apiPut<Handbook>(`/v1/project_handbook/projects/${projectId}/handbook`, body);
}

export function patchHandbook(projectId: string, body: { title?: string; edition?: string }): Promise<Handbook> {
  return apiPatch<Handbook>(`/v1/project_handbook/projects/${projectId}/handbook`, body);
}

export function syncChapters(projectId: string): Promise<{ created: number; updated: number }> {
  return apiPost<{ created: number; updated: number }>(`/v1/project_handbook/projects/${projectId}/handbook/sync`);
}

export interface ProjectMember {
  user_id: string;
  email: string;
  full_name: string;
}

/** The people who can own a chapter: the members of the project. */
export function listProjectMembers(projectId: string): Promise<ProjectMember[]> {
  return apiGet<ProjectMember[]>(`/v1/projects/${projectId}/members/`);
}

/* ── Chapters ─────────────────────────────────────────────────────────── */

export function getChapter(projectId: string, code: string): Promise<ChapterDetail> {
  return apiGet<ChapterDetail>(`/v1/project_handbook/projects/${projectId}/chapters/${code}`);
}

export function patchChapter(
  projectId: string,
  code: string,
  body: { title?: string; content?: string; owner_id?: string | null },
): Promise<ChapterDetail> {
  return apiPatch<ChapterDetail>(`/v1/project_handbook/projects/${projectId}/chapters/${code}`, body);
}

export function submitChapter(projectId: string, code: string): Promise<ChapterDetail> {
  return apiPost<ChapterDetail>(`/v1/project_handbook/projects/${projectId}/chapters/${code}/submit`);
}

export function approveChapter(projectId: string, code: string): Promise<ChapterDetail> {
  return apiPost<ChapterDetail>(`/v1/project_handbook/projects/${projectId}/chapters/${code}/approve`);
}

export function returnChapter(projectId: string, code: string): Promise<ChapterDetail> {
  return apiPost<ChapterDetail>(`/v1/project_handbook/projects/${projectId}/chapters/${code}/return`);
}

export function listFindings(projectId: string): Promise<Page<Finding>> {
  return apiGet<Page<Finding>>(`/v1/project_handbook/projects/${projectId}/findings`);
}

/** The whole handbook as one PDF. The server names the file. */
export function downloadHandbook(projectId: string): Promise<void> {
  return downloadWithAuth(`/api/v1/project_handbook/projects/${projectId}/export`, 'project_handbook.pdf');
}

/* ── Data room ────────────────────────────────────────────────────────── */

export function getDataRoom(projectId: string): Promise<DataRoom> {
  return apiGet<DataRoom>(`/v1/project_handbook/projects/${projectId}/data-room`);
}

export function materialiseDataRoom(projectId: string): Promise<MaterialiseResult> {
  return apiPost<MaterialiseResult>(`/v1/project_handbook/projects/${projectId}/data-room/materialise`);
}
