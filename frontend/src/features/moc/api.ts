// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Management of Change (MoC) feature API client.
 *
 * Thin, typed wrappers around the backend endpoints mounted at /v1/moc/.
 * Every function returns the typed payload so callers can drop straight
 * into `useQuery` / `useMutation`.
 *
 * Lifecycle (server-enforced FSM):
 *   proposed -> reviewed -> accepted -> implemented
 *                        \-> declined (terminal)
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* -- Types ----------------------------------------------------------------- */

export type MoCStatus =
  | 'proposed'
  | 'reviewed'
  | 'accepted'
  | 'declined'
  | 'implemented';

/** Transition verbs that map 1:1 to backend `POST /v1/moc/{id}/{action}`. */
export type MoCTransition = 'review' | 'accept' | 'decline' | 'implement';

/** Known change categories. The backend accepts any string (max 40), so the
 *  union is advisory for the picker only. */
export type MoCChangeCategory =
  | 'engineering'
  | 'scope'
  | 'design'
  | 'process'
  | 'material'
  | 'safety'
  | 'organizational'
  | 'regulatory'
  | 'other';

export type MoCRiskLevel = 'low' | 'medium' | 'high' | 'critical';

/** One impact-assessment line attached to a MoC entry. */
export interface MoCImpact {
  id: string;
  moc_entry_id: string;
  impact_area: string;
  description: string;
  severity: string;
  /** Decimal string (never a float, to avoid money rounding). */
  cost_impact: string;
  schedule_delta_days: number;
  currency: string;
  mitigation: string;
}

/** A Management-of-Change entry (mirrors backend `MoCEntryResponse`). */
export interface MoCEntry {
  id: string;
  project_id: string;
  /** Auto-assigned human code, e.g. "MOC-001". */
  code: string;
  title: string;
  description: string;
  change_category: string;
  risk_level: string;
  proposed_by: string | null;
  proposed_at: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_notes: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_notes: string;
  implemented_by: string | null;
  implemented_at: string | null;
  /** Decimal string. */
  cost_impact: string;
  schedule_delta_days: number;
  currency: string;
  status: MoCStatus;
  variation_request_id: string | null;
  variation_order_id: string | null;
  change_order_id: string | null;
  metadata: Record<string, unknown>;
  impacts: MoCImpact[];
}

export interface CreateMoCPayload {
  project_id: string;
  title: string;
  description?: string;
  change_category?: string;
  risk_level?: string;
  cost_impact?: string;
  schedule_delta_days?: number;
  currency?: string;
}

export interface UpdateMoCPayload {
  title?: string;
  description?: string;
  change_category?: string;
  risk_level?: string;
  cost_impact?: string;
  schedule_delta_days?: number;
  currency?: string;
  review_notes?: string;
  decision_notes?: string;
  variation_request_id?: string | null;
  variation_order_id?: string | null;
  change_order_id?: string | null;
}

export interface CreateImpactPayload {
  impact_area?: string;
  description?: string;
  severity?: string;
  cost_impact?: string;
  schedule_delta_days?: number;
  currency?: string;
  mitigation?: string;
}

/* -- API functions --------------------------------------------------------- */

/** List MoC entries for a project, optionally filtered by status. */
export function fetchMoCEntries(
  projectId: string,
  status?: MoCStatus | '',
): Promise<MoCEntry[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (status) params.set('status', status);
  return apiGet<MoCEntry[]>(`/v1/moc/?${params.toString()}`);
}

/** Fetch a single MoC entry (with its impact lines). */
export function getMoCEntry(id: string): Promise<MoCEntry> {
  return apiGet<MoCEntry>(`/v1/moc/${id}`);
}

/** Create a new MoC entry. Starts in `proposed`. */
export function createMoCEntry(data: CreateMoCPayload): Promise<MoCEntry> {
  return apiPost<MoCEntry, CreateMoCPayload>('/v1/moc/', data);
}

/** Patch an editable MoC entry (blocked server-side in terminal states). */
export function updateMoCEntry(
  id: string,
  data: UpdateMoCPayload,
): Promise<MoCEntry> {
  return apiPatch<MoCEntry, UpdateMoCPayload>(`/v1/moc/${id}`, data);
}

/** Delete a proposed MoC entry. */
export function deleteMoCEntry(id: string): Promise<void> {
  return apiDelete(`/v1/moc/${id}`);
}

/**
 * Advance the FSM. `notes` lands in `review_notes` (on review) or
 * `decision_notes` (on accept / decline).
 */
export function transitionMoCEntry(
  id: string,
  action: MoCTransition,
  notes?: string,
): Promise<MoCEntry> {
  return apiPost<MoCEntry, { notes?: string }>(`/v1/moc/${id}/${action}`, {
    notes: notes || undefined,
  });
}

/** Add an impact-assessment line to a MoC entry. */
export function addMoCImpact(
  entryId: string,
  data: CreateImpactPayload,
): Promise<MoCImpact> {
  return apiPost<MoCImpact, CreateImpactPayload>(
    `/v1/moc/${entryId}/impacts`,
    data,
  );
}

/** Delete an impact-assessment line. */
export function deleteMoCImpact(entryId: string, impactId: string): Promise<void> {
  return apiDelete(`/v1/moc/${entryId}/impacts/${impactId}`);
}
