// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Site Prep (pre-construction mobilisation readiness).
 *
 * Every endpoint is project-scoped in the PATH, e.g.
 * `/v1/site-prep/projects/${projectId}/items`. The vocabularies below mirror
 * the backend `app.modules.site_prep.readiness` source of truth.
 */

import { apiGet, apiPost, apiPatch, apiDelete, ApiError } from '@/shared/lib/api';

const BASE = '/v1/site-prep';

/* -- Vocabularies (lock-step with the backend) ----------------------------- */

export const SITE_PREP_CATEGORIES = [
  'access',
  'accommodation_welfare',
  'temporary_utilities',
  'security_hoarding',
  'temporary_works',
  'environmental_controls',
  'logistics_laydown',
  'permits_consents',
  'inductions_training',
  'other',
] as const;
export type SitePrepCategory = (typeof SITE_PREP_CATEGORIES)[number];

export const SITE_PREP_ITEM_STATUSES = [
  'not_started',
  'in_progress',
  'ready',
  'blocked',
  'not_applicable',
] as const;
export type SitePrepItemStatus = (typeof SITE_PREP_ITEM_STATUSES)[number];

export const SITE_PREP_PLAN_STATUSES = ['draft', 'active', 'complete'] as const;
export type SitePrepPlanStatus = (typeof SITE_PREP_PLAN_STATUSES)[number];

/* -- Types ----------------------------------------------------------------- */

export interface SitePrepPlan {
  id: string;
  project_id: string;
  target_start_date: string | null;
  status: string;
  notes: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SitePrepItem {
  id: string;
  project_id: string;
  plan_id: string | null;
  category: string;
  title: string;
  description: string | null;
  status: string;
  responsible_party: string | null;
  due_date: string | null;
  completed_date: string | null;
  is_gate: boolean;
  sort_order: number;
  notes: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReadinessItemRef {
  item_id: string | null;
  title: string;
  category: string;
  status: string;
  is_gate: boolean;
  due_date: string | null;
}

export interface CategoryReadiness {
  category: string;
  total: number;
  applicable: number;
  ready: number;
  counts: Record<string, number>;
  readiness_percent: number | null;
  gate_total: number;
  gate_ready: boolean;
  blocked: number;
  overdue: number;
}

export interface ReadinessReport {
  project_id: string;
  as_of: string;
  target_start_date: string | null;
  days_to_target: number | null;
  gate_ready: boolean;
  on_track: boolean;
  total_items: number;
  applicable_items: number;
  ready_items: number;
  readiness_percent: number | null;
  overall: CategoryReadiness;
  categories: CategoryReadiness[];
  blocked_items: ReadinessItemRef[];
  overdue_items: ReadinessItemRef[];
}

export interface GateStatus {
  project_id: string;
  as_of: string;
  target_start_date: string | null;
  days_to_target: number | null;
  gate_ready: boolean;
  on_track: boolean;
  gate_total: number;
  gate_ready_count: number;
  gate_blocking: ReadinessItemRef[];
}

/* -- Payloads -------------------------------------------------------------- */

export interface SitePrepPlanPayload {
  target_start_date?: string | null;
  status?: SitePrepPlanStatus;
  notes?: string | null;
}

export interface SitePrepItemPayload {
  plan_id?: string | null;
  category: SitePrepCategory;
  title: string;
  description?: string | null;
  status?: SitePrepItemStatus;
  responsible_party?: string | null;
  due_date?: string | null;
  completed_date?: string | null;
  is_gate?: boolean;
  sort_order?: number;
  notes?: string | null;
}

/**
 * Patch body for a readiness item: every field optional.
 *
 * The route dumps with `exclude_unset=True`, so a field left out is left alone
 * in the database. That is what lets the modal send only what the user actually
 * edited instead of writing its whole copy of the row back and overwriting
 * somebody else's edit to a field nobody opened.
 */
export type SitePrepItemUpdate = Partial<SitePrepItemPayload>;

export interface ItemFilters {
  category?: SitePrepCategory;
  status?: SitePrepItemStatus;
}

/* -- Plan (one per project) ------------------------------------------------ */

/** Get the project's mobilisation plan, or `null` when none exists yet (404). */
export async function fetchPlan(projectId: string): Promise<SitePrepPlan | null> {
  try {
    return await apiGet<SitePrepPlan>(`${BASE}/projects/${projectId}/plan`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function createPlan(
  projectId: string,
  payload: SitePrepPlanPayload,
): Promise<SitePrepPlan> {
  return apiPost<SitePrepPlan>(`${BASE}/projects/${projectId}/plan`, payload);
}

export function updatePlan(
  projectId: string,
  payload: SitePrepPlanPayload,
): Promise<SitePrepPlan> {
  return apiPatch<SitePrepPlan>(`${BASE}/projects/${projectId}/plan`, payload);
}

/* -- Items ----------------------------------------------------------------- */

export function fetchItems(
  projectId: string,
  filters?: ItemFilters,
): Promise<SitePrepItem[]> {
  const params = new URLSearchParams();
  if (filters?.category) params.set('category', filters.category);
  if (filters?.status) params.set('status', filters.status);
  const qs = params.toString();
  return apiGet<SitePrepItem[]>(
    `${BASE}/projects/${projectId}/items${qs ? `?${qs}` : ''}`,
  );
}

export function createItem(
  projectId: string,
  payload: SitePrepItemPayload,
): Promise<SitePrepItem> {
  return apiPost<SitePrepItem>(`${BASE}/projects/${projectId}/items`, payload);
}

export function updateItem(
  projectId: string,
  itemId: string,
  payload: SitePrepItemUpdate,
): Promise<SitePrepItem> {
  return apiPatch<SitePrepItem>(
    `${BASE}/projects/${projectId}/items/${itemId}`,
    payload,
  );
}

export function deleteItem(projectId: string, itemId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/projects/${projectId}/items/${itemId}`);
}

/* -- Derived readiness ----------------------------------------------------- */

export function fetchReadiness(
  projectId: string,
  asOf?: string,
): Promise<ReadinessReport> {
  const qs = asOf ? `?as_of=${encodeURIComponent(asOf)}` : '';
  return apiGet<ReadinessReport>(`${BASE}/projects/${projectId}/readiness${qs}`);
}

export function fetchGateStatus(
  projectId: string,
  asOf?: string,
): Promise<GateStatus> {
  const qs = asOf ? `?as_of=${encodeURIComponent(asOf)}` : '';
  return apiGet<GateStatus>(`${BASE}/projects/${projectId}/gate-status${qs}`);
}
