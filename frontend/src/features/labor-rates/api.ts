// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { ApiError, apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { toNum } from '@/shared/lib/money';
import { normalizeDecimalSeparators, parseDecimalInput } from '@/shared/lib/parseDecimal';

/**
 * API client and pure editor helpers for the labor & crew rate build-up.
 *
 * Every monetary value crosses the wire as a Decimal-encoded string (the
 * platform "Decimal-in, Decimal-as-string out" money contract). The editor
 * therefore keeps wage / on-cost / rate inputs as strings so the user's exact
 * entry round-trips and the backend does all the Decimal arithmetic - the
 * frontend never float-maths money.
 */

export type OnCostKind = 'percentage' | 'fixed';

/** A single on-cost component as sent to the backend. */
export interface OnCostInput {
  label: string;
  kind: OnCostKind;
  value: string;
}

/** A single crew trade line as sent to the backend. */
export interface CrewMemberInput {
  trade: string;
  count: number;
  all_in_rate: string;
}

/** Stateless build-up request. */
export interface ComputeRequest {
  base_wage: string;
  currency: string;
  components: OnCostInput[];
  crew: CrewMemberInput[];
}

/** One evaluated on-cost row in the build-up breakdown. */
export interface OnCostLine {
  label: string;
  kind: OnCostKind;
  value: string;
  amount: string;
  subtotal: string;
}

/** One evaluated crew member row. */
export interface CrewMemberLine {
  trade: string;
  count: number;
  all_in_rate: string;
  line_cost: string;
}

/** The blended crew rate result. */
export interface CrewBreakdown {
  currency: string;
  headcount: number;
  total_cost_per_hour: string;
  blended_hourly_rate: string;
  members: CrewMemberLine[];
}

/** The full all-in rate build-up, optionally with a crew blend. */
export interface RateBreakdown {
  base_wage: string;
  currency: string;
  percentage_total: string;
  fixed_total: string;
  all_in_rate: string;
  lines: OnCostLine[];
  crew: CrewBreakdown | null;
}

/** A persisted on-cost component. */
export interface OnCostRow {
  id: string;
  template_id: string;
  label: string;
  kind: OnCostKind;
  value: string;
  sort_order: number;
}

/** A persisted labor rate template with its components and all-in rate. */
export interface LaborRateTemplate {
  id: string;
  owner_id: string | null;
  name: string;
  base_wage: string;
  currency: string;
  description: string;
  components: OnCostRow[];
  all_in_rate: string;
  created_at: string;
  updated_at: string;
}

/** Payload to create or update a template. */
export interface TemplatePayload {
  name: string;
  base_wage: string;
  currency: string;
  description?: string;
  components: OnCostInput[];
}

/** A persisted crew member. */
export interface CrewMemberRow {
  id: string;
  crew_id: string;
  trade: string;
  count: number;
  all_in_rate: string;
  currency: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

/** A saved crew with its blended rate. */
export interface CrewResponse {
  crew_id: string;
  currency: string;
  headcount: number;
  total_cost_per_hour: string;
  blended_hourly_rate: string;
  members: CrewMemberRow[];
}

/** Payload to create or replace a crew's members. */
export interface CrewSavePayload {
  crew_id?: string;
  currency: string;
  members: CrewMemberInput[];
}

// ── Editor row types (carry a client-only React key) ────────────────────────

/** An on-cost row in the editor (with a stable key for React lists). */
export interface OnCostRowInput {
  key: string;
  label: string;
  kind: OnCostKind;
  value: string;
}

/** A crew trade row in the editor (with a stable key for React lists). */
export interface CrewRowInput {
  key: string;
  trade: string;
  count: number;
  all_in_rate: string;
}

let _rowCounter = 0;

/** Generate a process-unique key for a new editor row. */
function nextKey(prefix: string): string {
  _rowCounter += 1;
  return `${prefix}-${_rowCounter}`;
}

/** Build a blank (or seeded) on-cost editor row. */
export function newOnCost(
  label = '',
  kind: OnCostKind = 'percentage',
  value = '',
): OnCostRowInput {
  return { key: nextKey('oc'), label, kind, value };
}

/** Build a blank (or seeded) crew trade editor row. */
export function newCrewMember(trade = '', count = 1, all_in_rate = ''): CrewRowInput {
  return { key: nextKey('cm'), trade, count, all_in_rate };
}

/**
 * Sanitise a money / percentage text input into a Decimal-safe string.
 *
 * The amount is passed through as an exact decimal string so precision is
 * never lost. Blank collapses to `'0'`; anything unparseable does too, so the
 * backend always receives a valid Decimal literal and never NaN.
 *
 * The separator handling is {@link parseDecimalInput}'s, not `Number`'s. This
 * used to test the raw text against a dot-only regexp and fall through to
 * `toNum`, which is `Number` plus a zero guard - so a base hourly wage typed
 * as `30,50` reached the compute request as `'0'` and quietly zeroed every
 * derived rate. `laborRates.test.ts` asserted that zero as correct.
 */
export function normalizeAmount(value: string): string {
  const s = (value ?? '').trim();
  if (s === '') return '0';
  if (parseDecimalInput(s) === null) return '0';
  return normalizeDecimalSeparators(s);
}

/** Clamp a headcount to a non-negative integer. */
export function normalizeCount(count: number): number {
  const n = Math.trunc(Number(count));
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/**
 * Whether a money text input resolves to an amount above zero.
 *
 * Reads the field through {@link normalizeAmount} so it judges the same string
 * the request would carry, rather than the raw text.
 */
export function isPositiveAmount(value: string): boolean {
  const n = Number(normalizeAmount(value));
  return Number.isFinite(n) && n > 0;
}

/** What saving a rate template is gated on. */
export interface TemplateSaveGateInput {
  /** The template name typed into the editor. */
  templateName: string;
  /** The base hourly wage as typed, before normalisation. */
  baseWage: string;
  /** A save or an update is already in flight. */
  pending: boolean;
}

/**
 * Whether the editor may save a rate template (as a new one or over an open one).
 *
 * The base wage has to resolve to a positive amount, which mirrors the `gt=0`
 * the server puts on `base_wage`. A blank wage normalises to `'0'` because the
 * live build-up preview accepts zero, and that string used to reach the
 * template endpoint unchecked and come back as a raw 422 with nothing the user
 * could read. Zero is refused here for the reason the server refuses it: a
 * template that builds up to 0.00 prices labour hours at nothing while every
 * consumer reads it as a finished rate.
 */
export function canSaveTemplate(input: TemplateSaveGateInput): boolean {
  if (input.pending) return false;
  if (input.templateName.trim() === '') return false;
  return isPositiveAmount(input.baseWage);
}

/**
 * Build the compute request from the editor state.
 *
 * On-costs with a blank label and crew lines with a blank trade are dropped
 * (they are empty rows the user has not filled in yet). Amounts are sanitised
 * to Decimal-safe strings and counts to non-negative integers.
 */
export function buildComputeRequest(input: {
  base_wage: string;
  currency: string;
  onCosts: OnCostRowInput[];
  crew: CrewRowInput[];
}): ComputeRequest {
  return {
    base_wage: normalizeAmount(input.base_wage),
    currency: (input.currency ?? '').trim(),
    components: input.onCosts
      .filter((c) => c.label.trim() !== '')
      .map((c) => ({ label: c.label.trim(), kind: c.kind, value: normalizeAmount(c.value) })),
    crew: input.crew
      .filter((m) => m.trade.trim() !== '')
      .map((m) => ({
        trade: m.trade.trim(),
        count: normalizeCount(m.count),
        all_in_rate: normalizeAmount(m.all_in_rate),
      })),
  };
}

const asString = (v: unknown): string => (v === null || v === undefined ? '0' : String(v));

/** Defensively normalise a crew breakdown from the wire. */
function normalizeCrew(raw: CrewBreakdown): CrewBreakdown {
  return {
    currency: raw.currency ?? '',
    headcount: toNum(raw.headcount),
    total_cost_per_hour: asString(raw.total_cost_per_hour),
    blended_hourly_rate: asString(raw.blended_hourly_rate),
    members: (raw.members ?? []).map((m) => ({
      trade: m.trade,
      count: toNum(m.count),
      all_in_rate: asString(m.all_in_rate),
      line_cost: asString(m.line_cost),
    })),
  };
}

/**
 * Defensively normalise a rate breakdown from the wire: money fields stay
 * Decimal strings, integer fields are coerced through {@link toNum}, and the
 * `lines` / `crew` shapes are always defined so the UI never indexes undefined.
 */
export function normalizeRateBreakdown(raw: RateBreakdown): RateBreakdown {
  return {
    base_wage: asString(raw.base_wage),
    currency: raw.currency ?? '',
    percentage_total: asString(raw.percentage_total),
    fixed_total: asString(raw.fixed_total),
    all_in_rate: asString(raw.all_in_rate),
    lines: (raw.lines ?? []).map((l) => ({
      label: l.label,
      kind: l.kind,
      value: asString(l.value),
      amount: asString(l.amount),
      subtotal: asString(l.subtotal),
    })),
    crew: raw.crew ? normalizeCrew(raw.crew) : null,
  };
}

// ── Cost-item publishing (labor-rates -> costs interoperability) ────────────
//
// The all-in labor rate and the blended crew rate can be published as reusable
// COST ITEMS so they flow into the cost catalogue and onward into BOQ /
// assemblies via the existing costs->BOQ path. Every money field stays a
// Decimal-encoded string end to end (the platform money contract): the
// authoritative Decimals the compute endpoint returned are forwarded verbatim,
// so no float arithmetic ever touches a rate on its way to /v1/costs/.

/** One assembly-component line of a published cost item (a rate build-up row). */
export interface CostItemComponentInput {
  name: string;
  type: string;
  unit: string;
  quantity: number;
  /** Decimal-string per the money contract (never a float). */
  unit_rate: string;
  /** Decimal-string per the money contract (never a float). */
  cost: string;
}

/** Payload for ``POST /v1/costs/`` (a subset of the backend ``CostItemCreate``). */
export interface CostItemPayload {
  code: string;
  description: string;
  unit: string;
  /** All-in / blended rate as a Decimal-string (the backend promotes it to Decimal). */
  rate: string;
  currency: string;
  source: string;
  region?: string;
  classification?: Record<string, string>;
  components?: CostItemComponentInput[];
  tags?: string[];
}

// ── Delete refusal (the backend names what still holds a template) ──────────

/** One holder of a template, as counted by the backend's 409 refusal body. */
export interface InUseReference {
  kind: string;
  count: number;
}

/** The stable `detail.code` the backend sends when a template is still held. */
export const TEMPLATE_IN_USE_CODE = 'labor_rate_template_in_use';

/**
 * Read the structured "template still in use" refusal out of a delete error.
 *
 * Deleting a template that a published cost item or a priced assembly still
 * references is refused with 409 rather than cascaded, and the body carries a
 * `detail` object with the stable {@link TEMPLATE_IN_USE_CODE} plus a
 * `references` list of `{kind, count}`. Returning that list lets the caller
 * name the holders in the user's language. Anything else - another status,
 * another code, a shape that is not what we expect - yields `null`, so the
 * caller falls back to the generic error message instead of inventing counts.
 */
export function readInUseRefusal(err: unknown): InUseReference[] | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const detail = (err.body as { detail?: unknown } | undefined)?.detail;
  if (!detail || typeof detail !== 'object') return null;
  const { code, references } = detail as { code?: unknown; references?: unknown };
  if (code !== TEMPLATE_IN_USE_CODE || !Array.isArray(references)) return null;
  return references.filter(
    (r): r is InUseReference =>
      !!r && typeof r === 'object' && typeof (r as { kind?: unknown }).kind === 'string',
  );
}

/** Slim shape of the created cost item we read back for the success toast. */
export interface CostItemCreated {
  id: string;
  code: string;
  description: string;
  unit: string;
  rate: string;
  currency: string;
}

export const laborRatesApi = {
  compute: (req: ComputeRequest) =>
    apiPost<RateBreakdown>('/v1/labor-rates/compute', req).then(normalizeRateBreakdown),
  listTemplates: () => apiGet<LaborRateTemplate[]>('/v1/labor-rates/templates/'),
  getTemplate: (id: string) => apiGet<LaborRateTemplate>(`/v1/labor-rates/templates/${id}`),
  createTemplate: (data: TemplatePayload) =>
    apiPost<LaborRateTemplate>('/v1/labor-rates/templates/', data),
  updateTemplate: (id: string, data: Partial<TemplatePayload>) =>
    apiPatch<LaborRateTemplate>(`/v1/labor-rates/templates/${id}`, data),
  deleteTemplate: (id: string) => apiDelete(`/v1/labor-rates/templates/${id}`),
  saveCrew: (data: CrewSavePayload) => apiPost<CrewResponse>('/v1/labor-rates/crews/', data),
  getCrew: (crewId: string) => apiGet<CrewResponse>(`/v1/labor-rates/crews/${crewId}`),
  deleteCrew: (crewId: string) => apiDelete(`/v1/labor-rates/crews/${crewId}`),
  /**
   * Publish a computed rate as a reusable cost item.
   *
   * POSTs to ``/v1/costs/`` through the shared api client so the rate lands in
   * the cost catalogue and can be applied to a BOQ / assembly like any other
   * cost item. The payload carries only Decimal-string money values.
   */
  saveAsCostItem: (payload: CostItemPayload) =>
    apiPost<CostItemCreated>('/v1/costs/', payload),
};
