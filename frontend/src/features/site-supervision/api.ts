// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Site Supervision.
 *
 * All endpoints are prefixed with /v1/site-supervision/. Design-side
 * supervision visits and their observation entries, jurisdiction-neutral:
 * a regional pack can persist a discipline / category / status value outside
 * the built-in vocabularies below without a migration, so the UI treats these
 * lists as the common set rather than a hard enum.
 */

import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  getAuthToken,
  triggerDownload,
} from '@/shared/lib/api';

/* ── Vocabularies ──────────────────────────────────────────────────────── */

export type Discipline = 'architecture' | 'structure' | 'mep' | 'geotech' | 'general' | 'other';

export type VisitStatus = 'planned' | 'conducted' | 'reported';

export type EntryCategory =
  | 'conformance'
  | 'deviation'
  | 'hidden_works'
  | 'instruction'
  | 'motivated_refusal';

export type EntryStatus = 'open' | 'addressed' | 'refused_motivated' | 'closed';

export const DISCIPLINES: Discipline[] = [
  'architecture',
  'structure',
  'mep',
  'geotech',
  'general',
  'other',
];

export const VISIT_STATUSES: VisitStatus[] = ['planned', 'conducted', 'reported'];

export const ENTRY_CATEGORIES: EntryCategory[] = [
  'conformance',
  'deviation',
  'hidden_works',
  'instruction',
  'motivated_refusal',
];

export const ENTRY_STATUSES: EntryStatus[] = ['open', 'addressed', 'refused_motivated', 'closed'];

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface SupervisionVisit {
  id: string;
  project_id: string;
  planned_date: string | null;
  actual_date: string | null;
  visitor: string;
  discipline: string;
  status: string;
  summary: string;
  photo_refs: string[];
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SupervisionEntry {
  id: string;
  visit_id: string;
  project_id: string;
  ordinal: string;
  observation: string;
  category: string;
  structured_fields: Record<string, unknown>;
  links_to_change_ref: string | null;
  status: string;
  resolved_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateVisitPayload {
  project_id: string;
  planned_date?: string | null;
  actual_date?: string | null;
  visitor?: string;
  discipline?: string;
  status?: string;
  summary?: string;
  photo_refs?: string[];
  metadata?: Record<string, unknown>;
}

export interface UpdateVisitPayload {
  planned_date?: string | null;
  actual_date?: string | null;
  visitor?: string;
  discipline?: string;
  status?: string;
  summary?: string;
  photo_refs?: string[];
  metadata?: Record<string, unknown>;
}

export interface CreateEntryPayload {
  visit_id: string;
  ordinal?: string;
  observation?: string;
  category?: string;
  structured_fields?: Record<string, unknown>;
  links_to_change_ref?: string | null;
  status?: string;
}

export interface UpdateEntryPayload {
  ordinal?: string;
  observation?: string;
  category?: string;
  structured_fields?: Record<string, unknown>;
  links_to_change_ref?: string | null;
  status?: string;
}

export interface VisitFilters {
  project_id: string;
  status?: string;
  discipline?: string;
}

/** Localized vocabulary label pairs returned by GET /meta. */
export interface MetaOption {
  code: string;
  label: string;
}

export interface SiteSupervisionMeta {
  disciplines: MetaOption[];
  visit_statuses: MetaOption[];
  entry_categories: MetaOption[];
  entry_statuses: MetaOption[];
}

/** Planned-versus-conducted rollup for a project (GET /plan-vs-fact). */
export interface PlanVsFact {
  planned_count: number;
  conducted_count: number;
  reported_count: number;
  overdue_count: number;
  completion_ratio: number;
  overdue_visits: SupervisionVisit[];
  [key: string]: unknown;
}

/** One row of the hidden-works acceptance register (GET /hidden-works). */
export interface HiddenWorksRow {
  entry_id: string;
  visit_id: string;
  ordinal: string;
  observation: string;
  status: string;
  visit_date: string | null;
  [key: string]: unknown;
}

/** One row feeding the change / MOC route (GET /change-links). */
export interface ChangeLinkRow {
  entry_id: string;
  visit_id: string;
  category: string;
  observation: string;
  links_to_change_ref: string | null;
  [key: string]: unknown;
}

/* ── Visits: CRUD ──────────────────────────────────────────────────────── */

export async function fetchVisits(filters: VisitFilters): Promise<SupervisionVisit[]> {
  const params = new URLSearchParams();
  params.set('project_id', filters.project_id);
  if (filters.status) params.set('status', filters.status);
  if (filters.discipline) params.set('discipline', filters.discipline);
  return apiGet<SupervisionVisit[]>(`/v1/site-supervision/visits/?${params.toString()}`);
}

export async function createVisit(data: CreateVisitPayload): Promise<SupervisionVisit> {
  return apiPost<SupervisionVisit>('/v1/site-supervision/visits/', data);
}

export async function fetchVisit(id: string): Promise<SupervisionVisit> {
  return apiGet<SupervisionVisit>(`/v1/site-supervision/visits/${id}/`);
}

export async function updateVisit(
  id: string,
  data: UpdateVisitPayload,
): Promise<SupervisionVisit> {
  return apiPatch<SupervisionVisit>(`/v1/site-supervision/visits/${id}/`, data);
}

export async function deleteVisit(id: string): Promise<void> {
  await apiDelete(`/v1/site-supervision/visits/${id}/`);
}

/* ── Visits: state machine ─────────────────────────────────────────────── */

export async function conductVisit(id: string): Promise<SupervisionVisit> {
  return apiPost<SupervisionVisit>(`/v1/site-supervision/visits/${id}/conduct`);
}

export async function reportVisit(id: string): Promise<SupervisionVisit> {
  return apiPost<SupervisionVisit>(`/v1/site-supervision/visits/${id}/report`);
}

export async function fetchVisitEntries(visitId: string): Promise<SupervisionEntry[]> {
  return apiGet<SupervisionEntry[]>(`/v1/site-supervision/visits/${visitId}/entries/`);
}

/**
 * Export a visit and its entries as a structured, jurisdiction-neutral
 * record and trigger a JSON file download.
 */
export async function exportVisit(visit: SupervisionVisit): Promise<void> {
  const token = getAuthToken();
  const res = await fetch(`/api/v1/site-supervision/visits/${encodeURIComponent(visit.id)}/export`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-DDC-Client': 'OE/1.0',
    },
  });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  const dateStamp = (visit.actual_date || visit.planned_date || visit.created_at).slice(0, 10);
  triggerDownload(blob, `site-supervision-visit-${dateStamp}-${visit.id.slice(0, 8)}.json`);
}

/* ── Entries: CRUD ─────────────────────────────────────────────────────── */

export async function createEntry(data: CreateEntryPayload): Promise<SupervisionEntry> {
  return apiPost<SupervisionEntry>('/v1/site-supervision/entries/', data);
}

export async function fetchEntry(id: string): Promise<SupervisionEntry> {
  return apiGet<SupervisionEntry>(`/v1/site-supervision/entries/${id}/`);
}

export async function updateEntry(
  id: string,
  data: UpdateEntryPayload,
): Promise<SupervisionEntry> {
  return apiPatch<SupervisionEntry>(`/v1/site-supervision/entries/${id}/`, data);
}

export async function refuseEntry(id: string, reason: string): Promise<SupervisionEntry> {
  return apiPost<SupervisionEntry>(`/v1/site-supervision/entries/${id}/refuse`, { reason });
}

export async function deleteEntry(id: string): Promise<void> {
  await apiDelete(`/v1/site-supervision/entries/${id}/`);
}

/* ── Analytics ─────────────────────────────────────────────────────────── */

export async function fetchPlanVsFact(projectId: string): Promise<PlanVsFact> {
  return apiGet<PlanVsFact>(`/v1/site-supervision/plan-vs-fact?project_id=${encodeURIComponent(projectId)}`);
}

export async function fetchHiddenWorks(projectId: string): Promise<HiddenWorksRow[]> {
  return apiGet<HiddenWorksRow[]>(`/v1/site-supervision/hidden-works?project_id=${encodeURIComponent(projectId)}`);
}

export async function fetchChangeLinks(projectId: string): Promise<ChangeLinkRow[]> {
  return apiGet<ChangeLinkRow[]>(`/v1/site-supervision/change-links?project_id=${encodeURIComponent(projectId)}`);
}

/* ── Meta ──────────────────────────────────────────────────────────────── */

export async function fetchMeta(): Promise<SiteSupervisionMeta> {
  return apiGet<SiteSupervisionMeta>('/v1/site-supervision/meta');
}
