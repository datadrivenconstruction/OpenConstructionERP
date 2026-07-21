// DDC-CWICR-OE: DataDrivenConstruction * OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PriceSpreadBand - a compact, purely-visual price-spread strip drawn BEHIND
// a BOQ line's unit rate in the estimate grid. It answers, at a glance, "is
// this rate cheap or dear versus the same code in the other loaded cost
// bases?" without opening anything.
//
// The spread (min / p25 / median / p75 / max) is derived from the SAME
// ``price_intelligence.by_region`` shape the rest of the multi-base wave
// exposes for a cost code: a per-region price list. This module owns the pure
// maths (``computeSpread``), the row/response normalisers, an optional
// on-demand fetch hook (``usePriceByRegion``, used only when the row does not
// already carry the data), and the tiny presentational band.
//
// Hard rules honoured here:
//   * Currencies are NEVER blended. ``computeSpread`` only ever aggregates
//     rates that share ONE currency (the caller passes the line's own
//     currency, or the modal currency is used). Rates in other currencies are
//     dropped from the maths, so a EUR line is only ever compared to a EUR
//     spread.
//   * Money stays Decimal-as-string on the wire. ``Number(...)`` conversions
//     here are for on-screen spread geometry ONLY and are never written back
//     to a BOQ value.
//   * Coefficient / price-less rows carry no real unit money, so they are
//     excluded from the spread.
//   * The band self-hides (returns ``null``) whenever there is no real spread
//     (fewer than two distinct priced bases, or a degenerate min == max).

import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** One entry of ``price_intelligence.by_region`` for a single cost code: the
 *  price of that code in one region / base. Fields are intentionally loose so
 *  the several upstream shapes (enriched-position payload, cost-search rows)
 *  all normalise onto it. */
export interface ByRegionEntry {
  /** Region / base key, e.g. ``DE_BERLIN`` or ``TR_NATIONAL``. */
  region: string;
  /** Unit rate in ``currency``; ``null`` for coefficient / price-less bases. */
  unit_rate: number | null;
  /** ISO 4217 currency of ``unit_rate`` (may be absent on legacy rows). */
  currency?: string | null;
  /** True when the base prices this code as a labour/plant coefficient rather
   *  than a money unit rate (e.g. VN / ID coefficient bases). */
  coefficient?: boolean;
  /** True when the base carries the work item but no unit price at all. */
  priceless?: boolean;
  /** Optional provenance of the row (``cwicr`` / ``custom`` / ...). */
  source?: string;
}

/** A resolved five-number price spread, all in ONE ``currency``. */
export interface PriceSpread {
  min: number;
  p25: number;
  median: number;
  p75: number;
  max: number;
  /** Number of distinct priced bases the spread was computed from (>= 2). */
  count: number;
  /** The single ISO 4217 currency every number above is expressed in. */
  currency: string;
}

/* ── Pure maths ────────────────────────────────────────────────────────── */

/** Linear-interpolation percentile over a pre-sorted ascending list (pct in
 *  0..100). Matches numpy's "linear" method and the backend ``_percentile`` in
 *  ``costs/service.py`` so the grid band and any server-side benchmark agree. */
function percentile(sorted: number[], pct: number): number {
  const n = sorted.length;
  if (n === 0) return Number.NaN;
  if (n === 1) return sorted[0];
  const rank = (pct / 100) * (n - 1);
  const lo = Math.floor(rank);
  const hi = Math.ceil(rank);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo);
}

/** A ``by_region`` entry contributes to the money spread only when it is a
 *  real, positive, finite unit rate (not a coefficient / price-less row). */
function isPricedEntry(e: ByRegionEntry): boolean {
  if (e.coefficient === true || e.priceless === true) return false;
  const r = Number(e.unit_rate);
  return Number.isFinite(r) && r > 0;
}

function normCurrency(c: string | null | undefined): string {
  return (c || '').trim().toUpperCase();
}

/** Most-common currency among the priced entries (deterministic tie-break by
 *  currency code). Used when the caller does not pin a currency. */
function modalCurrency(priced: ByRegionEntry[]): string {
  const counts = new Map<string, number>();
  for (const e of priced) {
    const c = normCurrency(e.currency);
    if (!c) continue;
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  let best = '';
  let bestN = -1;
  for (const [c, n] of counts) {
    if (n > bestN || (n === bestN && c < best)) {
      best = c;
      bestN = n;
    }
  }
  return best;
}

/**
 * Compute a five-number price spread from a ``by_region`` list, within a
 * SINGLE currency (never blended).
 *
 * @param entries Raw per-region price entries.
 * @param opts.currency Pin the spread to this currency (the BOQ line's own
 *   currency). When omitted the modal currency across priced entries is used.
 * @returns The spread, or ``null`` when there is no meaningful spread: fewer
 *   than two distinct priced bases in the chosen currency, or a degenerate
 *   ``min == max``. A ``null`` return is the signal to render nothing.
 */
export function computeSpread(
  entries: ByRegionEntry[] | null | undefined,
  opts: { currency?: string | null } = {},
): PriceSpread | null {
  if (!entries || entries.length === 0) return null;
  const priced = entries.filter(isPricedEntry);
  if (priced.length < 2) return null;

  const pinned = normCurrency(opts.currency);
  const currency = pinned || modalCurrency(priced);
  if (!currency) return null;

  // One rate per region, in the chosen currency only. Deduping by region keeps
  // a base that appears twice (e.g. a city + national row) from skewing the
  // distribution.
  const perRegion = new Map<string, number>();
  for (const e of priced) {
    if (normCurrency(e.currency) !== currency) continue;
    const key = (e.region || '').trim().toUpperCase();
    if (!key || perRegion.has(key)) continue;
    perRegion.set(key, Number(e.unit_rate));
  }

  const values = [...perRegion.values()].filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
  if (values.length < 2) return null;

  const min = values[0];
  const max = values[values.length - 1];
  if (!(max > min)) return null; // all identical -> no spread to show

  return {
    min,
    p25: percentile(values, 25),
    median: percentile(values, 50),
    p75: percentile(values, 75),
    max,
    count: values.length,
    currency,
  };
}

/* ── Normalisers ───────────────────────────────────────────────────────── */

function toEntry(o: unknown, fallbackRegion?: string): ByRegionEntry | null {
  if (o == null) return null;
  if (typeof o === 'number' || typeof o === 'string') {
    // Dict form ``{ "DE_BERLIN": 320 }`` collapses to a bare rate.
    const region = (fallbackRegion || '').trim();
    if (!region) return null;
    const r = Number(o);
    return { region, unit_rate: Number.isFinite(r) ? r : null };
  }
  if (typeof o !== 'object') return null;
  const rec = o as Record<string, unknown>;
  const region = String(rec.region ?? rec.region_code ?? fallbackRegion ?? '').trim();
  if (!region) return null;
  const rateRaw = rec.unit_rate ?? rec.rate ?? rec.median ?? rec.price ?? rec.value;
  const r = rateRaw == null ? Number.NaN : Number(rateRaw);
  const currency = (rec.currency ?? rec.currency_code ?? null) as string | null;
  return {
    region,
    unit_rate: Number.isFinite(r) ? r : null,
    currency,
    coefficient: rec.coefficient === true || rec.is_coefficient === true,
    priceless: rec.priceless === true || rec.is_priceless === true,
    source: typeof rec.source === 'string' ? rec.source : undefined,
  };
}

/** Normalise a raw ``by_region`` value (array of entries, or a
 *  ``{ region: entry|rate }`` dict) into ``ByRegionEntry[]``. */
export function normalizeByRegion(value: unknown): ByRegionEntry[] {
  if (!value) return [];
  let raw: Array<ByRegionEntry | null>;
  if (Array.isArray(value)) {
    raw = value.map((v) => toEntry(v));
  } else if (typeof value === 'object') {
    raw = Object.entries(value as Record<string, unknown>).map(([region, v]) => toEntry(v, region));
  } else {
    raw = [];
  }
  return raw.filter((e): e is ByRegionEntry => e != null);
}

/** Read an inline ``price_intelligence.by_region`` off a BOQ grid row, if the
 *  enriched-position payload carries one (checked on both the row and its
 *  ``metadata`` bag). Returns ``[]`` when absent - the caller then decides
 *  whether to fetch. */
export function resolveInlineByRegion(data: Record<string, unknown> | null | undefined): ByRegionEntry[] {
  if (!data || typeof data !== 'object') return [];
  const meta = (data.metadata ?? {}) as Record<string, unknown>;
  const pi = (data.price_intelligence ?? meta.price_intelligence) as unknown;
  if (!pi || typeof pi !== 'object') return [];
  return normalizeByRegion((pi as Record<string, unknown>).by_region);
}

/** Pull the item array out of the several cost-search response envelopes. */
function extractItems(resp: unknown): Record<string, unknown>[] {
  if (Array.isArray(resp)) return resp as Record<string, unknown>[];
  if (resp && typeof resp === 'object') {
    const r = resp as Record<string, unknown>;
    const arr = r.items ?? r.results ?? r.data;
    if (Array.isArray(arr)) return arr as Record<string, unknown>[];
  }
  return [];
}

/** Build ``ByRegionEntry[]`` from a cost-search response, keeping only rows
 *  whose code EXACTLY matches ``code`` (the ``name`` filter is a substring, so
 *  super-string codes must be dropped) and one row per region. */
export function byRegionFromCostSearch(resp: unknown, code: string): ByRegionEntry[] {
  const wanted = code.trim().toLowerCase();
  const seen = new Set<string>();
  const out: ByRegionEntry[] = [];
  for (const it of extractItems(resp)) {
    if (String(it.code ?? '').trim().toLowerCase() !== wanted) continue;
    const region = String(it.region ?? '').trim();
    if (!region || seen.has(region.toUpperCase())) continue;
    seen.add(region.toUpperCase());
    const r = it.rate == null ? Number.NaN : Number(it.rate);
    out.push({
      region,
      unit_rate: Number.isFinite(r) ? r : null,
      currency: (it.currency ?? null) as string | null,
      source: typeof it.source === 'string' ? it.source : undefined,
    });
  }
  return out;
}

/* ── On-demand fetch hook ──────────────────────────────────────────────── */

/**
 * Fetch the per-region price list for a single cost ``code`` from the cost
 * table (``GET /v1/costs/``), grouping the same code across every loaded base.
 * Used as the fallback source when a grid row does not already carry an inline
 * ``price_intelligence.by_region``.
 *
 * Deduped and cached by react-query, so many grid cells asking for the same
 * code share one request. Disabled (no network) unless ``enabled`` is set -
 * callers gate it on multi-base mode so single-base estimates behave exactly
 * as before.
 */
export function usePriceByRegion(
  code: string | undefined,
  opts: { enabled?: boolean } = {},
): { entries: ByRegionEntry[]; isLoading: boolean; isError: boolean } {
  const enabled = (opts.enabled ?? true) && !!code;
  const query = useQuery({
    queryKey: ['boq-where-priced', code],
    enabled,
    staleTime: 5 * 60 * 1000,
    retry: false,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set('name', code as string); // code-only substring filter
      params.set('limit', '300');
      params.set('fuzzy', 'false');
      const resp = await apiGet<unknown>(`/v1/costs/?${params.toString()}`);
      return byRegionFromCostSearch(resp, code as string);
    },
  });
  return {
    entries: query.data ?? [],
    isLoading: enabled && query.isLoading,
    isError: query.isError,
  };
}

/* ── Presentational band ───────────────────────────────────────────────── */

export interface PriceSpreadBandProps {
  /** The resolved spread (all one currency). */
  spread: PriceSpread;
  /** This line's own unit rate, to place a "you are here" marker. */
  value?: number | null;
  /** Extra classes merged onto the absolutely-positioned strip. */
  className?: string;
}

/**
 * A ~3px tall strip meant to sit BEHIND the unit-rate number. The parent must
 * be ``position: relative``. Purely decorative (``aria-hidden`` +
 * ``pointer-events-none``); the human-readable spread numbers ride on the
 * cell's ``title`` tooltip so the strip never intercepts the edit click.
 *
 * Geometry: a faint full-range track (min..max), a stronger inter-quartile box
 * (p25..p75), a median tick, and a marker at ``value`` tinted green below the
 * median / amber above it.
 */
export function PriceSpreadBand({ spread, value, className = '' }: PriceSpreadBandProps) {
  const { min, max, p25, p75, median } = spread;
  if (!(max > min)) return null;

  const pct = (x: number) => Math.max(0, Math.min(100, ((x - min) / (max - min)) * 100));
  const iqrLeft = pct(p25);
  const iqrRight = pct(p75);
  const medianLeft = pct(median);
  const hasValue = typeof value === 'number' && Number.isFinite(value);
  const valueLeft = hasValue ? pct(value as number) : null;
  const valueBelow = hasValue ? (value as number) <= median : true;

  return (
    <span
      aria-hidden
      className={`pointer-events-none absolute left-1.5 right-1.5 bottom-[3px] h-[3px] ${className}`}
    >
      {/* Full-range track */}
      <span className="absolute inset-y-0 left-0 right-0 rounded-full bg-slate-300/50 dark:bg-slate-600/50" />
      {/* Inter-quartile box */}
      <span
        className="absolute inset-y-0 rounded-full bg-oe-blue/30 dark:bg-oe-blue/40"
        style={{ left: `${iqrLeft}%`, right: `${100 - iqrRight}%` }}
      />
      {/* Median tick */}
      <span className="absolute inset-y-0 w-px bg-oe-blue/80" style={{ left: `${medianLeft}%` }} />
      {/* "You are here" marker */}
      {valueLeft != null && (
        <span
          className={`absolute -top-px -bottom-px w-[1.5px] rounded-full ${
            valueBelow
              ? 'bg-emerald-500/80 dark:bg-emerald-400/80'
              : 'bg-amber-500/80 dark:bg-amber-400/80'
          }`}
          style={{ left: `calc(${valueLeft}% - 0.75px)` }}
        />
      )}
    </span>
  );
}
