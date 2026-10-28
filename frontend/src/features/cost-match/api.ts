// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Cost Match module.
 *
 * Backed by /api/v1/cost-match/ — see
 * backend/app/modules/cost_match/router.py
 *
 * Money, quantities and confidence arrive as plain-decimal **strings**. The
 * backend is explicit about why (schemas.py): a unit rate crossing the wire as
 * a JSON number loses precision in every JavaScript client, and a confidence
 * that becomes a float turns a "0.75" boundary into 0.7499999999999999 in a
 * client-side comparison. They stay strings here and are parsed only where one
 * is compared, in costMatchStatus.ts.
 *
 * Enum-shaped response fields are typed `string`, not a union. The backend
 * declares them as bare `str` so a reader never crashes on a value a later
 * version writes; the unions below type what may be *sent*. Narrowing an
 * arriving value is `resultTier` / `decisionStateOf`'s job.
 *
 * The last two calls read the *costs* module rather than this one. They are
 * here rather than imported from `features/costs` because an override target
 * has to be scoped to the exact base the run is pinned to — cost_source plus
 * region plus catalog_id — and `GET /v1/costs/` is the only endpoint that
 * accepts all three together.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** Tier filter accepted by the results endpoint. Mirrors models.TIERS. */
export type TierFilter = 'exact' | 'high_confidence' | 'needs_review' | 'unmatched';

/** Decision-state filter accepted by the results endpoint. */
export type DecisionStateFilter = 'pending' | 'confirmed' | 'overridden' | 'rejected';

/** What a person may rule. `pending` is a state, never a ruling. */
export type DecisionKind = 'confirmed' | 'overridden' | 'rejected';

/** Run status. `closed` refuses further rulings until it is re-opened. */
export type RunStatus = 'matched' | 'closed';

/**
 * The cap the backend puts on one submission (schemas.MAX_BATCH_LINES).
 *
 * Past it a paste stops being a review queue and becomes a data migration. A
 * request carrying more is rejected whole, so the composer caps and says so
 * rather than letting 501 lines fail as one 422.
 */
export const MAX_BATCH_LINES = 500;

/**
 * One free-text line from the foreign bill.
 *
 * `description` may be blank on purpose: a pasted bill really does contain
 * header-only and empty rows, and dropping them here would hide them from both
 * the reviewer and the `cost_match.source_description_present` rule that exists
 * to report them.
 */
export interface MatchLineInput {
  description: string;
  unit?: string;
  /** Decimal string, or null when the bill carried no readable quantity. */
  quantity?: string | null;
  /** The subcontractor's own item code, when their bill carried one. */
  source_ref?: string;
}

export interface MatchRunCreateBody {
  project_id: string;
  name?: string;
  source_label?: string;
  /** Language the descriptions are scored in. Not the reader's language. */
  source_locale?: string;
  cost_source?: string;
  region?: string | null;
  catalog_id?: string | null;
  candidate_limit?: number;
  notes?: string | null;
  lines: MatchLineInput[];
}

/** Only the reviewer-editable metadata. The pinned base is not patchable. */
export interface MatchRunUpdateBody {
  name?: string;
  source_label?: string;
  status?: RunStatus;
  notes?: string | null;
}

/**
 * Aggregated state of one run.
 *
 * Computed from the results in SQL on every read and never stored, so a badge
 * here cannot disagree with the queue it describes. `queue_length` is the
 * pending half of the two tiers where the machine is explicitly not claiming an
 * answer.
 */
export interface MatchRunCounts {
  total: number;
  exact: number;
  high_confidence: number;
  needs_review: number;
  unmatched: number;
  pending: number;
  confirmed: number;
  overridden: number;
  rejected: number;
  queue_length: number;
}

export interface MatchRun {
  id: string;
  project_id: string;
  name: string;
  source_label: string;
  source_locale: string;
  cost_source: string;
  region: string | null;
  catalog_id: string | null;
  status: string;
  /** How many lines were submitted. Immutable, unlike every count above. */
  item_count: number;
  candidate_limit: number;
  created_by: string | null;
  tenant_id: string | null;
  notes: string | null;
  counts: MatchRunCounts;
  created_at: string;
  updated_at: string;
}

/**
 * A runner-up cost item kept on the result so an override is a pick.
 *
 * `band` is the matcher's own traffic light for this candidate, already
 * resolved server-side. Render it; do not re-threshold `confidence`.
 */
export interface MatchCandidate {
  cost_item_id: string | null;
  code: string;
  description: string;
  unit: string;
  rate: string | null;
  currency: string;
  confidence: string;
  band: string;
  reason_codes: string[];
}

/** One ruling from the append-only history of a result. */
export interface MatchDecision {
  id: string;
  result_id: string;
  run_id: string;
  /** Per-result counter assigned by the service. The ordering to trust. */
  seq: number;
  decision: string;
  /** What the machine was showing when the person ruled, frozen here. */
  tier_at_decision: string;
  confidence_at_decision: string;
  decided_cost_item_id: string | null;
  decided_code: string;
  decided_description: string;
  decided_unit: string;
  decided_rate: string | null;
  decided_currency: string;
  decided_by: string | null;
  note: string | null;
  created_at: string;
}

export interface MatchResult {
  id: string;
  run_id: string;
  project_id: string;
  line_no: number;
  source_ref: string;
  source_description: string;
  source_unit: string;
  source_quantity: string | null;
  /** The automatic pass. Never moves after the run. */
  tier: string;
  confidence: string;
  /** A second candidate scored identically; the winner was picked by input
   *  order, which is not a judgement, so the screen has to say so. */
  tie: boolean;
  hint_code: string;
  /** Matcher vocabulary (`exact_match`, `unit_mismatch`). Never rendered raw —
   *  `explanation` is the same thing as a sentence in the reader's language. */
  reason_codes: string[];
  factors: Record<string, number>;
  alternatives: MatchCandidate[];
  suggested_cost_item_id: string | null;
  suggested_code: string;
  suggested_description: string;
  suggested_unit: string;
  suggested_rate: string | null;
  suggested_currency: string;
  /** The human pass. The only field a review moves. */
  decision_state: string;
  decisions: MatchDecision[];
  /** Rendered from `reason_codes` in the locale the read asked for. */
  explanation: string;
  /** Why there is nothing to offer, rendered the same way. */
  hint: string | null;
  created_at: string;
  updated_at: string;
}

export interface MatchResultPage {
  run_id: string;
  total: number;
  offset: number;
  limit: number;
  items: MatchResult[];
}

/**
 * A person's ruling.
 *
 * `confirmed` adopts the suggestion as it stands and must not name an item.
 * `overridden` must name one. `rejected` records that nothing in this base
 * fits, which is a real answer, and must not name one either.
 */
export interface MatchDecisionBody {
  decision: DecisionKind;
  cost_item_id?: string | null;
  note?: string | null;
}

export interface CostMatchFinding {
  rule_id: string;
  severity: string;
  category: string;
  message: string;
  key: string;
  element_ref: string | null;
  suggestion: string | null;
  context: Record<string, unknown>;
}

export interface CostMatchValidationReport {
  target_type: string;
  target_id: string | null;
  status: string;
  error_count: number;
  warning_count: number;
  info_count: number;
  passed_count: number;
  findings: CostMatchFinding[];
  unsupported_rule_sets: string[];
}

/** One row of the cost base, as the costs module's search returns it. */
export interface CostBaseItem {
  id: string;
  code: string;
  description: string;
  unit: string;
  /** Declared `number` by the costs schema, delivered as a decimal string. */
  rate: string | number | null;
  currency?: string;
}

/* ── Calls ─────────────────────────────────────────────────────────────── */

const BASE = '/v1/cost-match';

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : '';
}

/**
 * Match a pasted batch against one cost base.
 *
 * Scored in the same round trip. Nothing is applied: every line comes back
 * pending and waits for a person, whatever tier it landed in.
 */
export function createRun(body: MatchRunCreateBody): Promise<MatchRun> {
  return apiPost<MatchRun, MatchRunCreateBody>(`${BASE}/runs/`, body);
}

/** Runs on one project, newest first, each with its live counts. */
export function listRuns(params: {
  projectId: string;
  status?: RunStatus;
  offset?: number;
  limit?: number;
}): Promise<MatchRun[]> {
  return apiGet<MatchRun[]>(
    `${BASE}/runs/${qs({
      project_id: params.projectId,
      status: params.status,
      offset: params.offset,
      limit: params.limit,
    })}`,
  );
}

export function getRun(runId: string): Promise<MatchRun> {
  return apiGet<MatchRun>(`${BASE}/runs/${runId}`);
}

/** Rename a run, re-label its source, or open and close its review. */
export function updateRun(runId: string, body: MatchRunUpdateBody): Promise<MatchRun> {
  return apiPatch<MatchRun, MatchRunUpdateBody>(`${BASE}/runs/${runId}`, body);
}

/** Delete a run with its results and their whole ruling history. */
export function deleteRun(runId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/runs/${runId}`);
}

/**
 * One page of a run's results in submission order.
 *
 * `locale` is the *reader's* language: it decides what language `explanation`
 * and `hint` come back in, and defaults to English server-side. It is not
 * `run.source_locale`, which is the language the descriptions were scored in.
 */
export function listRunResults(
  runId: string,
  params: {
    tier?: TierFilter;
    decisionState?: DecisionStateFilter;
    locale?: string;
    offset?: number;
    limit?: number;
  } = {},
): Promise<MatchResultPage> {
  return apiGet<MatchResultPage>(
    `${BASE}/runs/${runId}/results${qs({
      tier: params.tier,
      decision_state: params.decisionState,
      locale: params.locale,
      offset: params.offset,
      limit: params.limit,
    })}`,
  );
}

/**
 * The lines that still need a person before anything can be priced.
 *
 * Narrower than "everything pending": the two tiers where the machine is
 * explicitly not claiming an answer. Exact and confident lines still need
 * confirming, and are asked for with `decisionState: 'pending'` instead.
 */
export function listReviewQueue(
  runId: string,
  params: { locale?: string; offset?: number; limit?: number } = {},
): Promise<MatchResultPage> {
  return apiGet<MatchResultPage>(
    `${BASE}/runs/${runId}/review-queue${qs({
      locale: params.locale,
      offset: params.offset,
      limit: params.limit,
    })}`,
  );
}

/**
 * Confirm, override or reject one suggested match.
 *
 * The only way a suggestion becomes something the project uses. Appended to the
 * line's history rather than replacing it, so a change of mind stays visible.
 */
export function decideResult(resultId: string, body: MatchDecisionBody): Promise<MatchDecision> {
  return apiPost<MatchDecision, MatchDecisionBody>(`${BASE}/results/${resultId}/decision`, body);
}

/** The `cost_match` rule set over a whole run, both scopes merged. */
export function validateRun(runId: string, locale?: string): Promise<CostMatchValidationReport> {
  return apiPost<CostMatchValidationReport>(`${BASE}/runs/${runId}/validate${qs({ locale })}`);
}

/* ── Cost base reads (costs module) ────────────────────────────────────── */

/** Regions that actually have cost items loaded, for pinning a run's base. */
export function listCostBaseRegions(): Promise<string[]> {
  return apiGet<string[]>('/v1/costs/regions/');
}

/**
 * Search the cost base a run is pinned to, for an override target.
 *
 * Scoped by all three of the run's pinning fields, because the decision
 * endpoint accepts only an active item of that exact base and answers 404 for
 * anything else. `lite` strips the per-row component array, which on a CWICR
 * row is tens of kilobytes this picker never reads.
 */
export function searchCostBase(params: {
  q: string;
  costSource?: string;
  region?: string | null;
  catalogId?: string | null;
  locale?: string;
  limit?: number;
}): Promise<{ items: CostBaseItem[] }> {
  return apiGet<{ items: CostBaseItem[] }>(
    `/v1/costs/${qs({
      q: params.q,
      source: params.costSource,
      region: params.region,
      catalog_id: params.catalogId,
      locale: params.locale,
      limit: params.limit ?? 20,
      lite: true,
    })}`,
  );
}
