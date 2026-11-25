// Design module (ERP side of the design editor link).
/** Types and decisions of the estimate screen: what GET /estimate returns and how it is read honestly. */

export interface BenchmarkSource {
  source_url: string;
  publisher: string;
  published: string;
  price_level_year: number;
  derived: boolean;
  published_basis: string | null;
  vat_included: boolean | null;
}

export interface CostItemSource {
  cost_item_id: string;
  code: string;
  database: string;
  region: string | null;
  version: string | null;
  price_date: string | null;
  currency: string;
  unit: string;
  /** true = the estimate chose it by search; false = a person picked it. */
  auto: boolean;
  score?: number;
  /** Rate taken from an ERP assembly (its total) instead of a cost item. */
  assembly_id?: string;
  name?: string;
  /** Cost Match run/result a person confirmed or overrode before the rate was taken. */
  via?: { kind: 'cost_match'; run_id: string; result_id: string; decision: 'confirmed' | 'overridden'; decision_id: string; confidence: string; tier: string };
}

export interface PositionProvenance {
  /** Model rules: how elements were selected. */
  select?: unknown;
  elements?: number;
  /** Derived rules: the formula, the aggregates it reads (each with its assumption), literal inputs and rates. */
  formula?: string;
  aggregates?: Record<string, { value: string; assumption: string }>;
  inputs?: Record<string, { value: number | string; unit?: string; source?: { url: string; date: string } | null }>;
  rate?: { value: number | string; source?: { url: string; date: string } };
  /** Unit rate taken from an ERP cost item: id, code, database, version and price date when the database has them. */
  cost_item?: CostItemSource;
  benchmark?: { low: string; mid: string; high: string; unit: string } & BenchmarkSource;
  missing?: string;
  /** Stable code behind `missing`: input_missing, rate_missing, benchmark_missing. */
  missing_code?: string;
}

export interface EstimatePosition {
  rule: string;
  kind: 'model' | 'derived' | 'manual';
  position_id: string;
  ordinal: string;
  description: string;
  cost_group: string;
  unit: string;
  quantity: string;
  unit_rate: string;
  total: string;
  model_quantity: string | null;
  override: boolean;
  override_quantity: string | null;
  override_reason: string | null;
  flags: string[];
  elements: number;
  provenance: PositionProvenance;
}

export interface RangeGroup {
  source: 'benchmark' | 'positions' | null;
  low?: string;
  mid?: string;
  high?: string;
  basis?: string;
  benchmark?: BenchmarkSource;
  reason?: string;
}

export interface EstimateRange {
  currency: string | null;
  basis_living_area_m2: string;
  groups: Record<string, RangeGroup>;
  missing_groups: string[];
  total: { low: string; mid: string; high: string; complete: boolean };
  price_level_years: number[];
  not_in_range: string[];
  note: string;
  /** Sources in the data that no range group reads, with reason codes. */
  sources_not_used?: UnusedSource[];
}

export interface UnusedSource {
  source_url: string;
  publisher: string;
  published: string;
  price_level_year: number;
  vat_included: boolean | null;
  /** other_basis | no_range | not_selected */
  reasons: string[];
}

export type EstimateView =
  | { estimate: false }
  | {
      estimate: true;
      boq_id: string;
      revision_id: string | null;
      depth_level: string | null;
      country: string;
      use: string;
      /** Regions of the loaded ERP cost databases that serve the country; empty = none loaded. */
      cost_regions?: string[];
      positions: EstimatePosition[];
      total: string;
      unpriced_positions: string[];
      range: EstimateRange;
      /** null = not checkable (no priced cost base); never read it as "inside". */
      inside_range: boolean | null;
      inside_range_note: string | null;
      /** Stable code of the note: unpriced_or_unsourced | currency_mismatch. */
      inside_range_note_code?: string | null;
      /** Project currency: positions and BOQ totals are in it; the range may be in another. */
      currency?: string | null;
      /** The ERP BOQ totals: direct cost, markups and the grand total with markups. */
      boq?: { direct_cost: string; markups_total: string; grand_total: string; currency: string | null };
    };

export type Estimate = Extract<EstimateView, { estimate: true }>;

export interface EstimateRule {
  id: string;
  kind: string;
  enabled: boolean;
  [key: string]: unknown;
}

export type RangeVerdict = 'inside' | 'outside' | 'unknown';

/** Only an explicit true is "inside"; null and anything else stay "not checkable". */
export function rangeVerdict(e: Pick<Estimate, 'inside_range'>): RangeVerdict {
  if (e.inside_range === true) return 'inside';
  if (e.inside_range === false) return 'outside';
  return 'unknown';
}

/** Where the priced total sits against the range; a total of 0 (nothing priced) is not "below". */
export function totalPlacement(e: Estimate): 'below' | 'above' | 'within' | 'none' {
  const t = Number(e.total);
  if (!Number.isFinite(t) || t === 0 || e.inside_range === null) return 'none';
  if (t < Number(e.range.total.low)) return 'below';
  if (t > Number(e.range.total.high)) return 'above';
  return 'within';
}

export const isUnpriced = (p: EstimatePosition): boolean => p.flags.includes('unpriced') || Number(p.unit_rate) === 0;

/** Override difference (kept minus model). Neutral by design: a smaller manual quantity is not a saving. */
export function overrideDelta(p: EstimatePosition): string | null {
  if (!p.override || p.model_quantity === null || p.override_quantity === null) return null;
  const d = Number(p.override_quantity) - Number(p.model_quantity);
  return Number.isFinite(d) ? String(d) : null;
}

export interface CostGroup {
  /** DIN 276 cost group code, e.g. "330". */
  code: string;
  positions: EstimatePosition[];
  /** Sum of priced positions only; null when nothing in the group has a rate. */
  subtotal: string | null;
  unpriced: number;
}

export function groupByCostGroup(positions: EstimatePosition[]): CostGroup[] {
  const map = new Map<string, EstimatePosition[]>();
  for (const p of positions) map.set(p.cost_group, [...(map.get(p.cost_group) ?? []), p]);
  return [...map.entries()]
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([code, list]) => {
      const priced = list.filter((p) => !isUnpriced(p));
      return {
        code,
        positions: [...list].sort((a, b) => a.ordinal.localeCompare(b.ordinal, undefined, { numeric: true })),
        subtotal: priced.length ? String(priced.reduce((s, p) => s + Number(p.total), 0)) : null,
        unpriced: list.length - priced.length,
      };
    });
}

export interface BenchmarkEntry extends BenchmarkSource {
  /** Benchmark groups the row prices. */
  groups: string[];
}

/** Every distinct benchmark source behind the range, once, with the groups it serves. */
export function benchmarkSources(e: Estimate): BenchmarkEntry[] {
  const byKey = new Map<string, BenchmarkEntry>();
  for (const [g, grp] of Object.entries(e.range.groups)) {
    const b = grp.benchmark;
    if (!b) continue;
    const key = `${b.source_url}|${b.published}`;
    const cur = byKey.get(key);
    if (cur) cur.groups.push(g);
    else byKey.set(key, { ...b, groups: [g] });
  }
  return [...byKey.values()];
}

/** HTTP status of a failed request, read without importing the client (works for any error carrying `status`). */
export function statusOf(err: unknown): number | null {
  const s = (err as { status?: unknown } | null)?.status;
  return typeof s === 'number' ? s : null;
}

export type ErrorKind = 'unauthorized' | 'forbidden' | 'conflict' | 'server' | 'other';

export function errorKind(err: unknown): ErrorKind {
  const s = statusOf(err);
  if (s === 401) return 'unauthorized';
  if (s === 403) return 'forbidden';
  if (s === 409) return 'conflict';
  if (s !== null && s >= 500) return 'server';
  return 'other';
}

/** Only http(s) links are rendered as links; anything else stays text. */
export const safeUrl = (u: string): string | null => (/^https?:\/\//i.test(u) ? u : null);
