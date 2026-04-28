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
  /** Human label (e.g. "ready-mix delivered"). Truncated to 200 chars upstream. */
  label: string;
  /** Variant price in the cost item's currency. */
  price: number;
  /** Optional per-unit price (rate normalized by unit). `null` when upstream column missing. */
  price_per_unit: number | null;
}

/**
 * Aggregated statistics for the variant set on a single cost item.  Lifted
 * straight from CWICR's `price_abstract_resource_est_price_*` summary columns;
 * `count` is the number of valid `CostVariant` entries we kept;
 * `position_count` is the total number of real estimates that used this rate
 * code (frequency signal across all variants combined).
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
}

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
