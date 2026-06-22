/**
 * API helpers for the Risk Register module.
 *
 * Endpoints (mounted at /api/v1/risk):
 *   POST   /v1/risk/projects/{project_id}/simulate
 *     — Run a Monte Carlo (PERT) simulation across the project's risks.
 *
 * The result is also persisted on every risk row's ``last_simulation``
 * JSON column server-side so a page refresh keeps the drill-down.
 */

import { apiPost } from '@/shared/lib/api';

/* ── Auto-escalation (TOP-30 #24) ──────────────────────────────────────── */

/** Body for a manual escalation sweep over a project's risks. */
export interface RiskEscalateRequest {
  /** Override the default escalation threshold (1-25 PMBOK product scale). */
  threshold?: number;
}

/** Summary returned by an escalation sweep. */
export interface RiskEscalateResult {
  scanned: number;
  escalated: number;
  /** Count of escalations grouped by trigger (severity / review_lapsed). */
  triggers: Record<string, number>;
}

/**
 * Run an on-demand auto-escalation sweep for ``projectId``.
 *
 * Escalates every not-yet-escalated risk whose severity product crosses the
 * threshold or whose next-review date has lapsed. Idempotent: already
 * escalated risks are skipped. Requires the ``risk.escalate`` permission
 * (MANAGER). The same sweep is run periodically by the backend scheduler.
 */
export async function escalateProjectRisks(
  projectId: string,
  body: RiskEscalateRequest = {},
): Promise<RiskEscalateResult> {
  return apiPost<RiskEscalateResult, RiskEscalateRequest>(
    `/v1/risk/projects/${projectId}/escalate`,
    body,
  );
}

/** Mode flag controlling which PERT triple(s) the simulator samples. */
export type RiskSimulateMode = 'cost' | 'schedule' | 'both';

/** POST body for ``/v1/risk/projects/{id}/simulate``. */
export interface RiskSimulateRequest {
  /** Number of Monte Carlo iterations. Backend clamps to [1000, 100000]. */
  iterations?: number;
  mode?: RiskSimulateMode;
}

/**
 * One bin in the contingency histogram (10-bin equal-width by default).
 *
 * ``lower``/``upper`` are Decimal money serialised as a JSON *string* by the
 * backend (e.g. ``"100000.00"``). Keep the type honest so call-sites coerce
 * with ``Number()`` at the boundary instead of string-concatenating
 * ("100000.00" + "150000.00" → "100000.00150000.00", then ``/ 2`` → NaN).
 */
export interface RiskHistogramBin {
  lower: number | string;
  upper: number | string;
  count: number;
}

/** One bar in the tornado / sensitivity chart, sorted desc by contribution. */
export interface RiskTornadoEntry {
  risk_id: string;
  code: string;
  /**
   * Mean probability-weighted contribution to the project contingency.
   * Decimal-as-string on the wire — coerce with ``Number()`` before arithmetic.
   */
  contribution: number | string;
}

/** Result of a Monte Carlo simulation, mirroring the backend Pydantic model. */
export interface RiskSimulationResult {
  iterations: number;
  risk_count: number;
  mode: RiskSimulateMode;
  // Cost percentiles are Decimal-as-string on the wire (or null when the
  // project mixes currencies / has no cost risks) — coerce with Number().
  p50_cost: number | string | null;
  p80_cost: number | string | null;
  p95_cost: number | string | null;
  p50_schedule_days: number | null;
  p80_schedule_days: number | null;
  p95_schedule_days: number | null;
  histogram_bins: RiskHistogramBin[];
  tornado: RiskTornadoEntry[];
  /** Project currency (data-driven; "" means unknown — render currency-less). */
  currency: string;
}

/**
 * Trigger a Monte Carlo simulation for ``projectId``.
 *
 * The backend permission required is ``risk.read`` (re-used from the
 * existing risk endpoints). Returns the full result snapshot — the
 * caller can render histogram + tornado directly without an extra
 * fetch.
 */
export async function simulateRisk(
  projectId: string,
  body: RiskSimulateRequest = {},
): Promise<RiskSimulationResult> {
  const payload: RiskSimulateRequest = {
    iterations: body.iterations ?? 10000,
    mode: body.mode ?? 'both',
  };
  return apiPost<RiskSimulationResult, RiskSimulateRequest>(
    `/v1/risk/projects/${projectId}/simulate`,
    payload,
  );
}
