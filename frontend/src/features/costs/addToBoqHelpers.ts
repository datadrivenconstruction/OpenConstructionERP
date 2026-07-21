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
  const resourcesTotal = resources.reduce((s, r) => s + (Number(r.total) || 0), 0);
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

/* ── Reprice-in-place (cross-base) ─────────────────────────────────────── */

/**
 * Body for ``PATCH /v1/boq/positions/{id}`` that re-applies the SAME code's
 * rate sourced from a different loaded base. It reuses the exact same
 * ``buildBoqPositionDraft`` builder the add-to-BOQ flow uses, so the position
 * goes back through the server-side variant-snapshot re-freeze
 * (``_stamp_variant_snapshot`` / ``_stamp_resource_variant_snapshots`` in
 * ``boq/service.py``) with no duplicated freeze logic here.
 *
 * Money contract: ``unit_rate`` rides the wire as a Decimal-as-string and is
 * NEVER converted. When the new base is denominated in another currency the
 * foreign figure lands verbatim; the currency is surfaced on the stamp
 * (``metadata.currency`` / ``cost_item_currency``) so the BOQ FX rollup can
 * convert for display via the project's fx_rates instead of treating it as
 * base.
 */
export interface RepricePayload {
  /** New unit rate as a Decimal string (not converted). */
  unit_rate: string;
  /** Rebuilt position metadata carrying the refreshed provenance stamp. */
  metadata: Record<string, unknown>;
  /** New base's CostItem id (top-level so the server re-links + validates). */
  cost_item_id: string;
  source: 'cost_database';
}

/**
 * Non-monetary breadcrumb written onto the position metadata when it is
 * repriced from another base. The authoritative provenance is
 * ``cost_item_region`` / ``currency`` (set by ``buildBoqPositionDraft``);
 * this only lets the UI show "repriced from X" without a second lookup and
 * is never read by any cost rollup.
 */
export interface RepriceProvenance {
  from_region: string | null;
  from_currency: string | null;
  to_region: string | null;
  to_currency: string;
  at: string;
}

/**
 * Build the PATCH body that reprices a BOQ position to the same code's rate
 * from ``targetItem`` (fetched full from the new base). Pure: no network.
 *
 * @param targetItem     Full cost item pulled from the NEW base (same code).
 * @param targetCurrency Resolved ISO 4217 code for the new base.
 * @param synthLabels    Localized labels for the cost-summary synth fallback.
 * @param opts           Current base/currency for the breadcrumb, and the
 *                       existing position metadata to merge over so a reprice
 *                       does not wipe position-specific keys.
 */
export function buildRepricePayload(
  targetItem: FullCostItem,
  targetCurrency: string,
  synthLabels: SynthLabels,
  opts?: {
    fromRegion?: string | null;
    fromCurrency?: string | null;
    existingMetadata?: Record<string, unknown>;
  },
): RepricePayload {
  const { unitRate, metadata } = buildBoqPositionDraft(targetItem, targetCurrency, synthLabels);
  const toCurrency = (targetCurrency || '').trim().toUpperCase();

  // Tag every resource line with the base it now comes from, so a later
  // "save as assembly" remembers each component's source base. The
  // position-level stamp (cost_item_region) is already set by
  // buildBoqPositionDraft; this mirrors it per resource.
  const resources = metadata.resources;
  if (Array.isArray(resources)) {
    for (const r of resources) {
      if (r && typeof r === 'object') {
        (r as Record<string, unknown>).source_base = targetItem.region ?? null;
      }
    }
  }

  const provenance: RepriceProvenance = {
    from_region: opts?.fromRegion ?? null,
    from_currency: (opts?.fromCurrency ?? '').trim().toUpperCase() || null,
    to_region: targetItem.region ?? null,
    to_currency: toCurrency,
    at: new Date().toISOString(),
  };
  metadata.repriced_from = provenance;

  // Merge over the existing position metadata so a reprice keeps
  // position-specific keys (quantity links like ``bim_qty_source`` /
  // ``pdf_measurement_source``, notes, validation) that must survive a rate
  // swap, while the cost fields ``buildBoqPositionDraft`` re-owns are dropped
  // from the carry-over so no stale data from the previous base lingers. The
  // stale ``variant_snapshot`` is dropped too so the server re-freezes cleanly
  // against the new rate/currency.
  let finalMeta = metadata;
  const existing = opts?.existingMetadata;
  if (existing && typeof existing === 'object') {
    const managed = new Set<string>([
      'resources',
      'cost_breakdown',
      'resource_count',
      'variant',
      'variant_default',
      'variant_snapshot',
      'cost_item_variants',
      'cost_item_variant_stats',
      'cost_item_variant_count',
      'cost_item_variant_mean',
      'cost_item_variant_min',
      'cost_item_variant_max',
      'repriced_from',
    ]);
    const preserved: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(existing)) {
      if (!managed.has(k)) preserved[k] = v;
    }
    finalMeta = { ...preserved, ...metadata };
  }

  return {
    unit_rate: String(unitRate),
    metadata: finalMeta,
    cost_item_id: targetItem.id,
    source: 'cost_database',
  };
}

/* ── Cross-base assembly ───────────────────────────────────────────────── */

/** Assembly resource kinds accepted by the assemblies API. Declared locally
 *  so this pure helper stays decoupled from the assemblies feature module;
 *  the literals are identical to ``ResourceType`` in
 *  ``@/features/assemblies/api`` so a draft is structurally assignable to a
 *  ``CreateComponentData``. */
export type AssemblyResourceType =
  | 'material'
  | 'labor'
  | 'equipment'
  | 'operator'
  | 'subcontractor'
  | 'overhead';

/** Map a loose BOQ resource ``type`` (which also allows 'electricity' /
 *  'other') onto a valid assembly resource kind; unknowns fall to material. */
function normalizeAssemblyResourceType(raw: unknown): AssemblyResourceType {
  const s = String(raw ?? '').trim().toLowerCase();
  if (
    s === 'labor' ||
    s === 'equipment' ||
    s === 'operator' ||
    s === 'subcontractor' ||
    s === 'overhead'
  ) {
    return s;
  }
  return 'material';
}

/**
 * One assembly component derived from a cross-base pick, shaped to match the
 * assemblies ``CreateComponentData`` contract. The source base and its
 * currency ride in ``metadata`` (``source_base`` / ``source_currency``) so a
 * cross-base assembly remembers where each line's rate came from. Currencies
 * are never blended into a single stored figure: each component keeps its own
 * ``source_currency`` and the caller must refuse to persist a multi-currency
 * pick under one assembly currency.
 */
export interface CrossBaseComponentDraft {
  description: string;
  resource_type: AssemblyResourceType;
  factor: number;
  quantity: number;
  unit: string;
  unit_cost: number;
  metadata: Record<string, unknown>;
}

/** Map one persisted BOQ resource line (``metadata.resources[i]``) to a
 *  cross-base assembly component, carrying the resource's source base. When a
 *  line has no per-line ``source_base`` (never repriced individually) the
 *  position-level fallback base/currency is used. */
export function crossBaseComponentFromResource(
  resource: Record<string, unknown>,
  fallbackBase: string | null,
  fallbackCurrency: string,
): CrossBaseComponentDraft {
  const sourceBase =
    typeof resource.source_base === 'string' && resource.source_base
      ? resource.source_base
      : fallbackBase;
  const sourceCurrency = (
    (typeof resource.currency === 'string' && resource.currency
      ? resource.currency
      : fallbackCurrency) || ''
  )
    .trim()
    .toUpperCase();
  const qty = typeof resource.quantity === 'number' && resource.quantity > 0 ? resource.quantity : 1;
  const rate = typeof resource.unit_rate === 'number' ? resource.unit_rate : 0;
  const unit = typeof resource.unit === 'string' && resource.unit ? resource.unit : 'pcs';
  const name = String(resource.name ?? resource.code ?? '').trim();
  return {
    description: name,
    resource_type: normalizeAssemblyResourceType(resource.type),
    factor: 1,
    quantity: qty,
    unit,
    unit_cost: rate,
    metadata: { source_base: sourceBase, source_currency: sourceCurrency },
  };
}

/** The full result of turning a position's cross-base pick into assembly
 *  components: the components (each tagged with its source base) plus the
 *  currency guard used to block a blended (multi-currency) save. */
export interface CrossBaseAssemblyDraft {
  components: CrossBaseComponentDraft[];
  /** Distinct source currencies across the components (upper-cased). */
  currencies: string[];
  /** True when the pick spans more than one currency: it must NOT be stored
   *  as one assembly (that would blend currencies into the total). */
  blended: boolean;
}

/**
 * Build the cross-base assembly draft from a position's persisted metadata.
 * Reads ``metadata.resources[]``; each resource becomes a component that
 * remembers its ``source_base``. Returns an empty component list when the
 * position carries no resource breakdown (the caller then synthesises a
 * single line from the position itself).
 */
export function buildCrossBaseAssemblyDraft(
  positionMetadata: Record<string, unknown> | undefined,
  fallbackBase: string | null,
  fallbackCurrency: string,
): CrossBaseAssemblyDraft {
  const raw = positionMetadata?.resources;
  const list = Array.isArray(raw) ? raw : [];
  const components = list
    .filter((r): r is Record<string, unknown> => !!r && typeof r === 'object')
    .map((r) => crossBaseComponentFromResource(r, fallbackBase, fallbackCurrency));
  const currencies = Array.from(
    new Set(
      components
        .map((c) => String(c.metadata.source_currency ?? '').trim().toUpperCase())
        .filter(Boolean),
    ),
  );
  return { components, currencies, blended: currencies.length > 1 };
}
