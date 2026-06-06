// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// addToBoqHelpers — pure, side-effect-free builder for the BOQ-position
// ``metadata`` blob produced when the user adds a cost item from the Cost
// Database browser (/costs) into a BOQ / estimate.
//
// Why this exists: the /costs list runs in ``?lite=1`` mode, so the rows it
// holds carry ``components: []`` and a trimmed ``metadata_`` (no
// ``variants`` array). Adding such a lite row to a BOQ used to drop every
// resource and the variant reference. The fix is to fetch the FULL cost
// item (``GET /v1/costs/{id}``) before building the payload and run it
// through this helper, which mirrors the canonical full-fidelity pattern
// already used by the BOQ "From Database" modal (see
// ``frontend/src/features/boq/BOQModals.tsx``):
//
//   * every cost-item component becomes a ``metadata.resources[]`` entry;
//   * variant-bearing components auto-default to the MEAN rate and carry
//     their ``available_variants`` / ``available_variant_stats`` so the BOQ
//     row's per-resource re-pick pill works without a second fetch;
//   * a top-level abstract-resource variant set (when not already mirrored
//     on a component) is appended as one synthetic resource line at the mean
//     rate, with ``variant_default = 'mean'`` and the variant catalog cached
//     on ``metadata`` so the inline picker can re-open;
//   * the position ``unit_rate`` equals the sum of resource totals when
//     resources exist, otherwise the catalog rate.
//
// The backend (``_stamp_variant_snapshot`` / ``_stamp_resource_variant_snapshots``
// in ``boq/service.py``) freezes a ``variant_snapshot`` on the position and
// on every variant-bearing resource from this metadata, so the chosen rate
// cannot be silently rewritten by a later cost-database re-import.

import type { CostItemMetadata, CostVariant, VariantStats } from './api';

/* ── Full cost item shape (as returned by GET /v1/costs/{id}) ──────────── */

/** One component / resource line of a full cost item. Variant-bearing
 *  abstract-resource components additionally carry ``available_variants`` +
 *  ``available_variant_stats`` (CWICR v2.6.30+). */
export interface FullCostComponent {
  name: string;
  code?: string;
  unit?: string;
  unit_localized?: string;
  quantity?: number;
  unit_rate?: number;
  cost?: number;
  type?: string;
  available_variants?: CostVariant[];
  available_variant_stats?: VariantStats;
}

/** Full cost item with components and the variant payload present (no
 *  ``lite`` trimming). */
export interface FullCostItem {
  id: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
  currency: string;
  region: string | null;
  classification: Record<string, string>;
  components: FullCostComponent[];
  metadata_: CostItemMetadata;
  source: string;
}

/** A BOQ position resource line as persisted under ``metadata.resources``. */
export interface BoqResource {
  name: string;
  code: string;
  type: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
  currency: string;
  variant?: { label: string; price: number; index: number };
  variant_default?: 'mean' | 'median';
  available_variants?: CostVariant[];
  available_variant_stats?: VariantStats;
}

/** Result of building a BOQ position from a full cost item. */
export interface BoqPositionDraft {
  /** Position ``unit_rate`` (sum of resource totals, else catalog rate). */
  unitRate: number;
  /** The full ``metadata`` blob to POST as ``metadata`` on the position. */
  metadata: Record<string, unknown>;
}

/* ── Helpers ──────────────────────────────────────────────────────────── */

/** Localized labels for the coarse 3-line synth fallback (labor / material /
 *  equipment) used only when a cost item carries cost-summary numbers but no
 *  component breakdown at all. */
export interface SynthLabels {
  labor: string;
  material: string;
  equipment: string;
}

/** Pick the mean rate for a variant set, falling back to median then to the
 *  first variant's price. Never returns NaN. */
function meanRateOf(stats: VariantStats, variants: CostVariant[]): number {
  if (stats.mean > 0) return stats.mean;
  if (stats.median > 0) return stats.median;
  return variants[0]?.price ?? 0;
}

/** Compose the display name for an auto-defaulted variant resource: the
 *  abstract resource's common base when present, else the component name. */
function defaultResourceName(stats: VariantStats, fallback: string): string {
  const cs = (stats.common_start || '').trim();
  return cs || fallback;
}

/* ── Builder ──────────────────────────────────────────────────────────── */

/**
 * Build the BOQ-position ``metadata`` + ``unit_rate`` for a single full cost
 * item. Pure: no network, no mutation of the input.
 *
 * @param item        Full cost item (components + variants present).
 * @param itemCurrency Resolved ISO 4217 currency for this item (caller passes
 *                     the catalog/region-resolved code; may be "").
 * @param synthLabels Localized fallback labels for the cost-summary synth.
 */
export function buildBoqPositionDraft(
  item: FullCostItem,
  itemCurrency: string,
  synthLabels: SynthLabels,
): BoqPositionDraft {
  const currency = (itemCurrency || '').trim().toUpperCase();
  const meta = item.metadata_ ?? {};
  const topVariants = meta.variants;
  const topStats = meta.variant_stats;

  // ── Step 1: components → resources (mirror BOQModals) ──────────────────
  // Track the first component index per dedupe key (resource_code, or the
  // first-variant label fallback) so two component rows pointing at the same
  // abstract-resource catalog only carry one set of available_variants (the
  // rest are plain rate lines) — matching the BOQ "From Database" behaviour.
  const variantPrimaryIdx = new Map<string, number>();
  const resources: BoqResource[] = (item.components || []).map((c, i) => {
    const compVariants = c.available_variants;
    const compStats = c.available_variant_stats;
    const hasCompVariants =
      Array.isArray(compVariants) && compVariants.length >= 2 && compStats != null;

    const qty = c.quantity ?? 1;

    if (!hasCompVariants) {
      const rate = c.unit_rate ?? 0;
      return {
        name: c.name,
        code: c.code || '',
        type: c.type || 'other',
        unit: c.unit || 'pcs',
        quantity: qty,
        unit_rate: rate,
        total: c.cost ?? qty * rate,
        currency,
      };
    }

    const code = (c.code || '').trim();
    const dedupeKey = code || (compVariants![0]?.label ?? `__c${i}`);
    const primaryIdx = variantPrimaryIdx.get(dedupeKey) ?? i;
    if (!variantPrimaryIdx.has(dedupeKey)) {
      variantPrimaryIdx.set(dedupeKey, i);
    }
    const isPrimary = primaryIdx === i;

    // Auto-default to the mean rate — the costs-page add flow has no
    // interactive picker. The user refines later via the BOQ row's
    // per-resource re-pick pill (powered by available_variants below).
    const rate = meanRateOf(compStats!, compVariants!);
    return {
      name: c.name,
      code: c.code || '',
      type: c.type || 'other',
      unit: c.unit || 'pcs',
      quantity: qty,
      unit_rate: rate,
      total: qty * rate,
      currency,
      variant_default: 'mean' as const,
      ...(isPrimary
        ? { available_variants: compVariants, available_variant_stats: compStats }
        : {}),
    };
  });

  // ── Step 2: top-level abstract-resource variant set ───────────────────
  // Many CWICR rates carry the abstract resource as BOTH metadata.variants
  // AND components[0] with an identical catalog. When that happens the
  // component already carries the rate — appending a synthetic top-level
  // line would double-count. Detect the mirror by comparing variant labels.
  const topMeta: Record<string, unknown> = {};
  let topMirroredOnComponent = false;
  if (topVariants && topVariants.length >= 2) {
    const topHash = topVariants.map((v) => (v.label || '').trim()).join('|');
    for (const c of item.components || []) {
      if (Array.isArray(c.available_variants) && c.available_variants.length >= 2) {
        const compHash = c.available_variants.map((v) => (v.label || '').trim()).join('|');
        if (compHash === topHash) {
          topMirroredOnComponent = true;
          break;
        }
      }
    }
  }

  if (topVariants && topVariants.length >= 2 && topStats && !topMirroredOnComponent) {
    const rate = meanRateOf(topStats, topVariants);
    resources.push({
      name: defaultResourceName(topStats, item.description || item.code),
      code: item.code,
      type: 'material',
      unit: item.unit || 'pcs',
      quantity: 1,
      unit_rate: rate,
      total: rate,
      currency,
      variant_default: 'mean',
      available_variants: topVariants,
      available_variant_stats: topStats,
    });
    topMeta.variant_default = 'mean';
    // Cache the variant catalog on the position so the inline picker on the
    // BOQ row can re-open without a refetch (BOQModals does the same).
    topMeta.cost_item_variants = topVariants;
    topMeta.cost_item_variant_stats = topStats;
    topMeta.cost_item_variant_count = topStats.count;
    topMeta.cost_item_variant_mean = topStats.mean;
    topMeta.cost_item_variant_min = topStats.min;
    topMeta.cost_item_variant_max = topStats.max;
  }

  // ── Step 3: coarse synth fallback ─────────────────────────────────────
  // Only when the item has NO components and NO variant set, but does carry
  // cost-summary numbers, synthesize labor/material/equipment lines so the
  // position still shows a breakdown.
  if (resources.length === 0) {
    const m = meta;
    const synth: BoqResource[] = [];
    if (typeof m.labor_cost === 'number' && m.labor_cost > 0) {
      synth.push({
        name: synthLabels.labor,
        code: '',
        type: 'labor',
        unit: item.unit,
        quantity: 1,
        unit_rate: m.labor_cost,
        total: m.labor_cost,
        currency,
      });
    }
    if (typeof m.material_cost === 'number' && m.material_cost > 0) {
      synth.push({
        name: synthLabels.material,
        code: '',
        type: 'material',
        unit: item.unit,
        quantity: 1,
        unit_rate: m.material_cost,
        total: m.material_cost,
        currency,
      });
    }
    if (typeof m.equipment_cost === 'number' && m.equipment_cost > 0) {
      synth.push({
        name: synthLabels.equipment,
        code: '',
        type: 'equipment',
        unit: item.unit,
        quantity: 1,
        unit_rate: m.equipment_cost,
        total: m.equipment_cost,
        currency,
      });
    }
    for (const s of synth) resources.push(s);
  }

  // ── Step 4: position unit_rate + cost breakdown summary ────────────────
  const resourcesTotal = resources.reduce((s, r) => s + (r.total ?? 0), 0);
  const unitRate = resources.length > 0 ? resourcesTotal : item.rate ?? 0;

  const metadata: Record<string, unknown> = {
    cost_item_id: item.id,
    cost_item_code: item.code,
    cost_item_region: item.region,
    ...(currency ? { currency, cost_item_currency: currency } : {}),
    // Pass through any extra metadata keys the item carried (scope_of_work,
    // cost-summary numbers, ...) WITHOUT clobbering the variant cache we set
    // below. The heavy ``variants`` array is intentionally not duplicated at
    // the top level — it rides on the resource entries instead.
    ...(() => {
      const passthrough: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(meta)) {
        if (k === 'variants') continue;
        passthrough[k] = v;
      }
      return passthrough;
    })(),
    ...topMeta,
    ...(resources.length > 0 ? { resources } : {}),
  };

  if (resources.length > 0) {
    const byType: Record<string, number> = {};
    for (const r of resources) {
      byType[r.type] = (byType[r.type] ?? 0) + (r.total ?? 0);
    }
    metadata.cost_breakdown = byType;
    metadata.resource_count = resources.length;
  }

  return { unitRate, metadata };
}
