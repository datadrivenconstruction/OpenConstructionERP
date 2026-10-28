// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Currency / FX register.
 *
 * Backed by /api/v1/fx/ — see backend/app/modules/fx/router.py. Every path
 * below carries its trailing slash because the routes are declared with one.
 *
 * Rates and money arrive as plain-decimal **strings**, not numbers. The backend
 * serialises Decimals that way on purpose: a rate is stored at ten decimal
 * places precisely because six loses about one percent of an inverse rate
 * against a weak currency, and a JSON float would hand that back. They stay
 * strings here, and are parsed only where one has to be compared or inverted —
 * see fxRates.ts, which is the only place that does arithmetic on one.
 *
 * `POST /revalue/` is the one endpoint not wired. It splits a movement into the
 * part caused by scope and the part caused by the rate, over a list of figures
 * the caller supplies; its input is a commitment register, not three fields on
 * a form, so it belongs on a cost report rather than here.
 */

import { apiDelete, apiGet, apiPost, apiPut } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** `live` tracks the newest rates; `pinned` holds a project to one set. */
export type RateMode = 'live' | 'pinned';

/** `market` uses published reference rates; `ppp` uses World Bank factors. */
export type ConvertMode = 'market' | 'ppp';

/**
 * Where a rate came from, carried by every response that applies one.
 *
 * `covers_requested_date` is the field to read carefully. It is documented as
 * "false when no set was on file for the requested date and an earlier one was
 * applied", but the date lookup already filters to sets on or before the date
 * asked for, so on that path the flag cannot be false. The screen therefore
 * compares `as_of` against the date it asked for itself rather than trusting
 * the flag to raise its hand.
 */
export interface RateProvenance {
  /** Date the applied rates are effective for. */
  as_of: string | null;
  /** Who published them: ecb | seed | manual | worldbank. */
  source: string;
  /** Where they were read from: rate_set | legacy_cache | seed | worldbank. */
  origin: string;
  /** Feed URL, contract clause or document the figures came from. */
  source_ref: string;
  /** When the set was captured, if known. ISO 8601 with a timezone. */
  fetched_at: string | null;
  rate_set_id: string | null;
  /** True when the applied set is locked against edits. */
  is_locked: boolean;
  covers_requested_date: boolean;
}

/** Health and freshness of the FX subsystem. */
export interface FxStatus {
  source: string;
  origin: string;
  rates_as_of: string | null;
  /** Currencies held in the legacy latest-rate cache. */
  cached_currencies: number;
  /** Currency codes available for conversion right now. */
  currencies: string[];
  /** Countries with a cached purchasing-power-parity factor. */
  ppp_countries: number;
  /** Published rate sets held in the register. */
  rate_sets: number;
  /** Whether the reference feed was reachable on the last probe. */
  network_ok: boolean;
}

/** Rate map for a base currency: units of each currency per 1 base. */
export interface FxRates extends RateProvenance {
  base: string;
  count: number;
  rates: Record<string, string>;
  note: string;
}

export interface ConvertRequest {
  amount: string;
  from_currency: string;
  to_currency: string;
  mode?: ConvertMode;
  /** Value the amount at the rates that applied on this date (YYYY-MM-DD). */
  on_date?: string | null;
  /** Apply this project's policy, so a pinned project reprices at its set. */
  project_id?: string | null;
  /** Use one named rate set, overriding both the date and the policy. */
  rate_set_id?: string | null;
}

/**
 * The result of a conversion.
 *
 * An unavailable mode is a **200** with `available: false`, `converted` and
 * `rate` null and a plain-language `note` — not an error. Nothing on the
 * request's failure path will fire for it, so the caller has to read the flag.
 */
export interface ConvertResult extends RateProvenance {
  amount: string;
  converted: string | null;
  rate: string | null;
  from_currency: string;
  to_currency: string;
  mode: ConvertMode;
  available: boolean;
  note: string;
}

/** A stored rate set without its individual quotes. */
export interface RateSetSummary {
  id: string;
  base_currency: string;
  /** Date the rates are effective for, not the date they were downloaded. */
  rate_date: string;
  /** Who published them: ecb | seed | manual. */
  source: string;
  source_ref: string;
  fetched_at: string | null;
  /** A locked set can no longer be rewritten or deleted. */
  is_locked: boolean;
  note: string;
  quote_count: number;
  currencies: string[];
}

/** A stored rate set with every quote it carries. */
export interface RateSetDetail extends RateSetSummary {
  rates: Record<string, string>;
}

export interface RateSetListResponse {
  total: number;
  items: RateSetSummary[];
}

/**
 * Record a hand-entered rate set: a contract rate, a bank quote, treasury.
 *
 * `base_currency` is accepted by the API but this screen never sends anything
 * other than the register's own base. Resolution looks up sets by that base
 * before rebasing, so a set stored against another one is only ever reachable
 * by naming or pinning it, and a form that offered the choice would quietly
 * produce data the live path skips.
 */
export interface RateSetCreateRequest {
  base_currency?: string;
  rate_date: string;
  /** Units of each currency per 1 base. Plain-decimal strings. */
  rates: Record<string, string>;
  source?: string;
  source_ref?: string;
  note?: string;
  /** Lock the set immediately so it can never be rewritten. */
  lock?: boolean;
}

/** A project's currency policy as it is sent. */
export interface FxPolicyRequest {
  estimating_currency: string;
  procurement_currency: string;
  reporting_currency: string;
  rate_mode: RateMode;
  /** Required when `rate_mode` is `pinned`. */
  pinned_rate_set_id?: string | null;
  /** How old the backing rates may get before validation warns. 0 to 3650. */
  max_rate_age_days: number;
  note?: string;
}

/** A project's stored currency policy, with its pinned set resolved. */
export interface FxPolicy {
  project_id: string;
  estimating_currency: string;
  procurement_currency: string;
  reporting_currency: string;
  rate_mode: RateMode;
  pinned_rate_set_id: string | null;
  pinned_rate_set: RateSetSummary | null;
  max_rate_age_days: number;
  note: string;
}

/** One validation finding, ready to render as a row under a traffic light. */
export interface FxValidationFinding {
  rule_id: string;
  rule_name: string;
  severity: string;
  category: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

/**
 * Validation report for a project's FX setup.
 *
 * `checked` is load-bearing: the rules stay silent when there is nothing of
 * their kind to look at, so a project with no policy comes back with no errors,
 * no warnings and `checked: 0`. That is an unexamined project, not a clean one.
 */
export interface FxValidation {
  project_id: string;
  /** passed | warnings | errors | info | skipped | unsupported. */
  status: string;
  /** Quality score 0-1; null when nothing was checked. */
  score: number | null;
  checked: number;
  errors: FxValidationFinding[];
  warnings: FxValidationFinding[];
}

/** Result of a manual refresh from the live reference feed. */
export interface RefreshResult {
  updated: number;
  /** ecb when the live feed was used, seed on network fallback. */
  source: string;
  as_of: string | null;
  rate_set_id: string | null;
  network_ok: boolean;
  note: string;
}

/* ── Calls ─────────────────────────────────────────────────────────────── */

const BASE = '/v1/fx';

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue;
    search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : '';
}

/** Feed status: rate source, freshness, register size and reachability. */
export function fetchStatus(): Promise<FxStatus> {
  return apiGet<FxStatus>(`${BASE}/status/`);
}

/** The rate map for a base currency, optionally as it stood on a date. */
export function fetchRates(
  params: { base?: string; onDate?: string; rateSetId?: string } = {},
): Promise<FxRates> {
  return apiGet<FxRates>(
    `${BASE}/rates/${qs({ base: params.base, on_date: params.onDate, rate_set_id: params.rateSetId })}`,
  );
}

/** Convert an amount. Stores nothing. */
export function convert(body: ConvertRequest): Promise<ConvertResult> {
  return apiPost<ConvertResult, ConvertRequest>(`${BASE}/convert/`, body);
}

/**
 * Pull the live feed into the register now.
 *
 * Never fails on a network problem: an unreachable feed comes back with
 * `network_ok: false` and the register left as it was.
 */
export function refreshRates(): Promise<RefreshResult> {
  return apiPost<RefreshResult>(`${BASE}/refresh/`);
}

/** Stored rate sets, newest first. */
export function listRateSets(
  params: { base?: string; source?: string; limit?: number; offset?: number } = {},
): Promise<RateSetListResponse> {
  return apiGet<RateSetListResponse>(
    `${BASE}/rate-sets/${qs({
      base: params.base,
      source: params.source,
      limit: params.limit,
      offset: params.offset,
    })}`,
  );
}

/** One rate set with every quote it carries. */
export function fetchRateSet(rateSetId: string): Promise<RateSetDetail> {
  return apiGet<RateSetDetail>(`${BASE}/rate-sets/${rateSetId}/`);
}

/**
 * Record a hand-entered rate set.
 *
 * Re-recording the same base, date and source replaces the quotes rather than
 * accumulating duplicates, so a corrected entry is a re-post. A locked set is
 * refused with 409.
 */
export function createRateSet(body: RateSetCreateRequest): Promise<RateSetDetail> {
  return apiPost<RateSetDetail, RateSetCreateRequest>(`${BASE}/rate-sets/`, body);
}

/** Lock or unlock a rate set. Locking is what makes a pin worth having. */
export function setRateSetLock(rateSetId: string, locked: boolean): Promise<RateSetDetail> {
  return apiPost<RateSetDetail, { locked: boolean }>(`${BASE}/rate-sets/${rateSetId}/lock/`, { locked });
}

/** Delete an unlocked rate set. A locked set is refused with 409. */
export function deleteRateSet(rateSetId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/rate-sets/${rateSetId}/`);
}

/**
 * A project's currency policy.
 *
 * Throws an ApiError with status 404 when the project has none configured,
 * which is the ordinary state of every project until somebody sets one. The
 * caller distinguishes that from a real failure rather than rendering an error.
 */
export function fetchPolicy(projectId: string): Promise<FxPolicy> {
  return apiGet<FxPolicy>(`${BASE}/policies/${projectId}/`);
}

/** Create or update a project's currency policy. */
export function savePolicy(projectId: string, body: FxPolicyRequest): Promise<FxPolicy> {
  return apiPut<FxPolicy, FxPolicyRequest>(`${BASE}/policies/${projectId}/`, body);
}

/** Remove a project's currency policy, putting it back on the defaults. */
export function deletePolicy(projectId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/policies/${projectId}/`);
}

/** Traffic light over a project's FX setup: coverage, pinning and freshness. */
export function fetchValidation(projectId: string, onDate?: string): Promise<FxValidation> {
  return apiGet<FxValidation>(`${BASE}/policies/${projectId}/validation/${qs({ on_date: onDate })}`);
}
