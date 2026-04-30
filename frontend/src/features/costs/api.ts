// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { apiPost } from '@/shared/lib/api';

/* ── CWICR abstract-resource variant types ─────────────────────────────── */

/**
 * One concrete price option behind a CWICR rate code.  Imported from the
 * `price_abstract_resource_*` columns of `*_workitems_costs_resources_DDC_CWICR.parquet`.
 *
 * Stored on `CostItem.metadata_['variants']` as a pass-through list — no
 * dedicated table, no Alembic migration. Surfaced in the Cost Database
 * browser (variant detail panel) and the BOQ "Apply position" picker.
 */
export interface CostVariant {
  /** Position in the original bullet-separated list (0-based). */
  index: number;
  /** Variable-part label only (e.g. "C25/30 delivered"). This is what the
   *  picker renders per row — the shared common base is shown once as a
   *  picker header (see ``VariantStats.common_start``). Truncated to 200
   *  chars upstream. */
  label: string;
  /** ``common_start + label`` joined with a space, truncated to 400 chars.
   *  This is what gets stamped onto the BOQ resource row when the variant
   *  is applied — it replaces the position's default description so the
   *  estimator sees the actual chosen material/option, not the abstract
   *  rate-code description. Optional for backward compatibility with
   *  pre-v2.6.30 imports that didn't capture ``common_start``. */
  full_label?: string;
  /** Variant price in the cost item's currency. */
  price: number;
  /** Optional per-unit price (rate normalized by unit). `null` when upstream column missing. */
  price_per_unit: number | null;
  /** Optional grouping key — when the catalog mixes 2+ variant families
   *  (e.g. concrete grade × reinforcement type) the backend stamps a
   *  per-variant ``group`` so the picker can render an accordion instead
   *  of a single flat list. Absent for single-group catalogs (the common
   *  case today), in which case the picker falls back to flat rendering. */
  group?: string;
  /** Localized mirror of `group` — same fallback semantics as
   *  `VariantStats.group_localized`. */
  group_localized?: string;
}

/**
 * Aggregated statistics for the variant set on a single cost item.  Lifted
 * straight from CWICR's `price_abstract_resource_est_price_*` summary columns;
 * `count` is the number of valid `CostVariant` entries we kept;
 * `position_count` is the total number of real estimates that used this rate
 * code (frequency signal across all variants combined).
 *
 * `unit_localized` / `group_localized` are added by the backend translation
 * layer (`backend/app/modules/costs/translations`) when the request carries
 * a `?locale=` query param or `Accept-Language` header that maps to a
 * shipped translation file.  Render with the standard fallback chain:
 * `unit_localized || unit`.
 */
export interface VariantStats {
  min: number;
  max: number;
  mean: number;
  median: number;
  unit: string;
  group: string;
  count: number;
  position_count?: number;
  /** Localized mirror of `unit` — present when the API was called with
   *  a known locale. Falls back to the German source when the locale is
   *  unsupported or the token has no translation. */
  unit_localized?: string;
  /** Localized mirror of `group`. Same fallback semantics as `unit_localized`. */
  group_localized?: string;
  /** Shared base name for the abstract resource (e.g. "Ready-mix concrete").
   *  Rendered once as a picker header so each variant row can show only
   *  the distinguishing variable part. Optional — empty for pre-v2.6.30
   *  imports that didn't capture this column. */
  common_start?: string;
}

/**
 * Frozen copy of the variant choice persisted on a BOQ position so its
 * unit_rate cannot be silently rewritten by a later cost-database re-import.
 * Stamped server-side by `_stamp_variant_snapshot` in
 * `backend/app/modules/boq/service.py`.  Read-only on the client.
 */
export interface VariantSnapshot {
  /** Variant label or "average" / "median" when the user accepted the auto-suggested rate. */
  label: string;
  /** Unit rate as it was at the moment of the choice. */
  rate: number;
  /** ISO 4217 currency captured alongside the rate. */
  currency: string;
  /** UTC ISO-8601 timestamp of the freeze. */
  captured_at: string;
  /** Provenance flag: explicit user pick vs auto-suggested mean / median. */
  source: 'user_pick' | 'default_mean' | 'default_median';
}

/**
 * Default-selection strategy hint persisted on the BOQ position when the user
 * applied an abstract-resource cost item without explicitly opening the
 * picker.  Drives the softer "default · choose to refine" hint in the BOQ
 * row marker (vs the bolder "Variant: foo" label for a deliberate pick).
 */
export type VariantDefault = 'mean' | 'median';

/**
 * The shape of `CostItem.metadata_` as it actually flows from the backend.
 * Numeric cost-breakdown fields (`labor_cost`, ...) ride alongside the
 * optional variant payload.  Kept open via the index signature so module
 * extensions can attach extra keys without a type break.
 */
export interface CostItemMetadata {
  labor_cost?: number;
  equipment_cost?: number;
  material_cost?: number;
  labor_hours?: number;
  workers_per_unit?: number;
  variants?: CostVariant[];
  variant_stats?: VariantStats;
  // Open-ended — module extensions may attach additional keys.
  [key: string]: unknown;
}

/* ── CWICR matcher types (T12) ─────────────────────────────────────────── */

/** A single ranked CWICR match returned by the matcher API. */
export interface CwicrMatchResult {
  cost_item_id: string;
  code: string;
  description: string;
  unit: string;
  unit_rate: number;
  currency: string;
  /** 0..1 — higher is a stronger match. */
  score: number;
  /** Channel that produced the score: 'lexical' | 'semantic' | 'hybrid'. */
  source: string;
  /**
   * Optional variant count when the matched CostItem carries
   * `metadata_.variant_stats.count >= 2`.  Present only when the backend
   * MatchResult schema is extended to include it; absent until then,
   * which makes the variant badge in CwicrMatchPanel a no-op.
   */
  variant_count?: number;
  /** Optional min variant price — used for the badge tooltip. */
  variant_min?: number;
  /** Optional max variant price — used for the badge tooltip. */
  variant_max?: number;
  /**
   * Set by `CwicrMatchPanel` after the user picks a CWICR variant so the
   * parent `onApply` handler can write `metadata.variant` on the BOQ
   * position and append the `(Variant: …)` description suffix.  Absent
   * when the matched cost item has no variants or the user applied
   * directly without going through the picker.
   */
  applied_variant?: {
    label: string;
    price: number;
    index: number;
  };
}

/** Matcher mode — pure-lexical is always available, semantic requires the
 *  backend `[semantic]` extra.  We default to 'lexical' on the frontend so
 *  unconfigured deployments don't surface "fell back to lexical" warnings. */
export type CwicrMatchMode = 'lexical' | 'semantic' | 'hybrid';

export interface CwicrMatchRequest {
  query: string;
  unit?: string;
  lang?: string;
  top_k?: number;
  mode?: CwicrMatchMode;
  region?: string;
}

export interface CwicrMatchFromPositionRequest {
  position_id: string;
  top_k?: number;
  mode?: CwicrMatchMode;
  lang?: string;
  region?: string;
}

/** POST /api/v1/costs/match/ — ranked CWICR matches for a free-form query. */
export async function matchCwicr(
  body: CwicrMatchRequest,
): Promise<CwicrMatchResult[]> {
  return apiPost<CwicrMatchResult[], CwicrMatchRequest>(
    '/v1/costs/match/',
    body,
  );
}

/** POST /api/v1/costs/match-from-position/ — same matcher, resolves the
 *  query from an existing BOQ position.  Returns 404 if the position id
 *  does not exist (the api helper raises). */
export async function matchCwicrFromPosition(
  body: CwicrMatchFromPositionRequest,
): Promise<CwicrMatchResult[]> {
  return apiPost<CwicrMatchResult[], CwicrMatchFromPositionRequest>(
    '/v1/costs/match-from-position/',
    body,
  );
}
