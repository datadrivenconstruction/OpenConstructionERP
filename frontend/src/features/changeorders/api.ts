// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Change-orders feature API client.
 *
 * Thin wrappers around the backend's approval-chain endpoints. Each
 * function returns the typed payload so callers can drop straight into
 * `useQuery` / `useMutation` without re-typing the response shape.
 *
 * Endpoints
 * ---------
 * - POST  /v1/changeorders/{id}/approval-chain   — start a chain
 * - POST  /v1/changeorders/{id}/advance-approval — record a decision
 * - GET   /v1/changeorders/{id}/approvals        — list rows in step order
 */

import { apiGet, apiPost } from '@/shared/lib/api';

/** One row in a change order's approval chain (mirrors backend `ApprovalRow`). */
export interface ApprovalRow {
  id: string;
  change_order_id: string;
  step_order: number;
  /** ``null`` when the assigned user has been deleted (FK is SET NULL). */
  approver_user_id: string | null;
  /** ``pending`` | ``approved`` | ``rejected``. */
  decision: 'pending' | 'approved' | 'rejected';
  decided_at: string | null;
  comments: string | null;
  created_at: string;
}

/** Body for ``POST /v1/changeorders/{id}/approval-chain``. */
export interface ApprovalStartBody {
  approver_user_ids: string[];
}

/** Body for ``POST /v1/changeorders/{id}/advance-approval``. */
export interface ApprovalAdvanceBody {
  decision: 'approved' | 'rejected';
  comments?: string;
  /** Bill of quantities the approved scope is written into. Read only on the
   *  final step, where the chain hands over to the same writeback the
   *  single-step approval performs. Without it the last approver on a project
   *  holding several unlocked bills is refused a question they cannot answer. */
  boq_id?: string;
}

/** Start a construction-management-platform-style multi-step approval chain on a change order. */
export function startApprovalChain(
  changeOrderId: string,
  approverUserIds: string[],
): Promise<ApprovalRow[]> {
  return apiPost<ApprovalRow[], ApprovalStartBody>(
    `/v1/changeorders/${changeOrderId}/approval-chain`,
    { approver_user_ids: approverUserIds },
  );
}

/**
 * Record the calling user's decision on the active chain step.
 *
 * The caller must be the approver assigned to ``current_approval_step``;
 * any other user receives 403. A rejection short-circuits the chain
 * (the CO flips to ``rejected`` and downstream steps stay pending);
 * the final approval flips the CO to ``approved`` and triggers the
 * usual budget / BOQ writeback.
 */
export function advanceApproval(
  changeOrderId: string,
  body: ApprovalAdvanceBody,
): Promise<ApprovalRow> {
  return apiPost<ApprovalRow, ApprovalAdvanceBody>(
    `/v1/changeorders/${changeOrderId}/advance-approval`,
    body,
  );
}

/** List approval rows for a change order, ordered by ``step_order``. */
export function getApprovals(changeOrderId: string): Promise<ApprovalRow[]> {
  return apiGet<ApprovalRow[]>(
    `/v1/changeorders/${changeOrderId}/approvals`,
  );
}

// ── What-If impact simulator (TOP-30 #11) ──────────────────────────────────

/** Optional overrides for a what-if projection. Empty body = the CO as-is. */
export interface SimulateImpactBody {
  cost_impact?: string;
  schedule_impact_days?: number;
}

export interface ImpactCost {
  budget_before: string;
  budget_after: string;
  delta: string;
  pct_of_budget: number;
}

export interface ImpactSchedule {
  current_end_date: string | null;
  projected_end_date: string | null;
  days_added: number;
  finish_moves: boolean;
}

export interface ImpactEVM {
  bac_before: string;
  bac_after: string;
  eac_before: string;
  eac_after: string;
  vac_before: string;
  vac_after: string;
  spi: string;
  cpi: string;
}

export interface ImpactBOQ {
  item_count: number;
  sections_added: number;
  positions_added: number;
  target_boq_name: string | null;
  /** The project holds more than one unlocked bill, so the preview cannot name
   *  one and the approval will refuse to pick one. Distinct from
   *  `target_boq_name === null`, which also means "no unlocked bill at all" -
   *  a caller that renders both as "the project BOQ" reproduces the guess the
   *  backend stopped making. */
  target_boq_ambiguous: boolean;
}

/** Every `detail.error` the approval endpoint refuses with. The union below is
 *  derived from this array rather than written twice, so a code added to one
 *  cannot go missing from the other. */
const WRITEBACK_REFUSAL_CODES = [
  'ambiguous_boq',
  'boq_not_found',
  'boq_project_mismatch',
  'boq_locked',
] as const;

/** Structured 409 body from `POST /changeorders/{id}/approve/` when the
 *  approved scope has nowhere unambiguous to go.
 *
 *  The approval is refused, not merely reported: nothing is written, so the
 *  caller names a bill and retries. `candidates` carries the bills that could
 *  take the scope, which is what a picker is built from. */
export interface WritebackRefusal {
  error: (typeof WRITEBACK_REFUSAL_CODES)[number];
  message: string;
  candidates: Array<{ id: string; name: string }>;
}

/** True when an error body is the backend's "which bill?" refusal.
 *
 *  Branching on `error` rather than on the message keeps the UI's wording in
 *  the locale files: the `message` field is server-side English, fine as a
 *  last resort in a toast and wrong as the thing a screen is built around.
 *
 *  All four codes are treated alike on purpose. They differ in why the target
 *  failed, but they agree on what the caller now holds: a bill list that no
 *  longer describes the project. A bill locked between the fetch and the click
 *  answers `boq_locked`, and matching only `ambiguous_boq` there would leave
 *  the stale option on screen for the user to pick a second time. */
export function isWritebackRefusal(body: unknown): boolean {
  if (!body || typeof body !== 'object') return false;
  const detail = (body as { detail?: unknown }).detail;
  if (!detail || typeof detail !== 'object') return false;
  const code = (detail as { error?: unknown }).error;
  return WRITEBACK_REFUSAL_CODES.some((c) => c === code);
}

/** Full what-if projection (mirrors backend `SimulateImpactResponse`). */
export interface SimulateImpactResponse {
  order_id: string;
  code: string;
  base_currency: string;
  as_of: string;
  co_cost_native: string;
  co_currency: string;
  co_cost_base: string;
  fx_converted: boolean;
  cost: ImpactCost;
  schedule: ImpactSchedule;
  evm: ImpactEVM;
  boq: ImpactBOQ;
  notes: string[];
}

/** Run a read-only cost/schedule/EVM/BOQ projection for a change order. */
export function simulateImpact(
  changeOrderId: string,
  body: SimulateImpactBody = {},
): Promise<SimulateImpactResponse> {
  return apiPost<SimulateImpactResponse, SimulateImpactBody>(
    `/v1/changeorders/${changeOrderId}/simulate-impact/`,
    body,
  );
}

/** Snapshot the current what-if projection into the CO audit trail. */
export function publishScenario(
  changeOrderId: string,
  body: SimulateImpactBody = {},
): Promise<unknown> {
  return apiPost<unknown, SimulateImpactBody>(
    `/v1/changeorders/${changeOrderId}/publish-scenario/`,
    body,
  );
}

// ── AI / heuristic draft (TOP-30 #11) ──────────────────────────────────────

export interface AIDraftBody {
  project_id: string;
  source_kind: 'free_text' | 'rfi' | 'daily_log';
  source_id?: string | null;
  source_text: string;
  currency?: string;
}

export interface AIDraftLine {
  description: string;
  unit: string;
  quantity: string;
  rate: string;
  cost_delta: string;
  confidence: number;
}

/** A review-ready change-order draft (never auto-saved). */
export interface AIDraftResponse {
  title: string;
  description: string;
  reason_category: string;
  cost_impact: string;
  schedule_impact_days: number;
  currency: string;
  lines: AIDraftLine[];
  confidence: number;
  ai_used: boolean;
  provider: string;
  source_kind: string;
  source_id: string | null;
  note: string;
}

/** Draft a change order from source text (AI when a key is set, else heuristic). */
export function aiDraftChangeOrder(body: AIDraftBody): Promise<AIDraftResponse> {
  // longRunning: the call waits for an AI provider (issue #499).
  return apiPost<AIDraftResponse, AIDraftBody>(`/v1/changeorders/ai-draft/`, body, { longRunning: true });
}
