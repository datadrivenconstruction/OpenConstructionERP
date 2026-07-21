// DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// baseStats - the shared "coverage of a cost base" surface used everywhere a
// base is picked or shown. It provides:
//
//   * useBaseStats()      - a React-Query hook over the live base-stats manifest
//                           (GET /api/v1/costs/base-stats), fail-soft to null.
//   * baseStatFor(region) - a pure lookup into the manifest.
//   * formatCount(n)      - a compact count formatter for stat chips.
//   * BaseCoverageStat    - a compact works / resources / priced readout.
//   * WhyThisBase         - a generalised badge / hint / card that explains why
//                           a base is a good (or the recommended) choice, reusing
//                           BaseCoverageStat.
//
// The manifest groups bases into families.global_cwicr / national and gives each
// base its works / resource_lines / unique_resources / avg_resources_per_work /
// priced_pct / coefficient. Everything degrades gracefully when the endpoint is
// not available yet: the hook returns null and every surface falls back to the
// static knowledge in baseRecommendation.

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Boxes, Layers, CircleDollarSign, Sparkles, Info } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { REGION_MAP } from '@/stores/useCostDatabaseStore';
import { CountryFlag } from '@/shared/ui';
import {
  recommendedRegionFor,
  isCoefficientBase,
  isGlobalCwicrBase,
} from './baseRecommendation';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** Per-base resource-depth stats, as served by GET /api/v1/costs/base-stats. */
export interface BaseStat {
  /** Region code, e.g. "USA_USD" or "BR_NATIONAL". */
  region: string;
  /** Distinct works (positions) in the base. */
  works: number;
  /** Total resource lines across all works. */
  resource_lines: number;
  /** Distinct resources referenced by the base. */
  unique_resources: number;
  /** Mean resource lines per work (resource depth). */
  avg_resources_per_work: number;
  /** Share of works that carry a ready unit price (0..1 or 0..100). */
  priced_pct: number;
  /** True for coefficient books (norms only, no ready unit prices). */
  coefficient: boolean;
  /** Optional family tag ("global_cwicr" | "national"). */
  family?: string;
  /** Optional ISO 4217 currency, when the backend supplies it. */
  currency?: string;
}

/** The full base-stats manifest. */
export interface BaseStatsManifest {
  families: {
    global_cwicr: string[];
    national: string[];
  };
  bases: BaseStat[];
  generated_at?: string;
}

export const BASE_STATS_QUERY_KEY = ['costs', 'base-stats'] as const;

/* ── Fetch + normalise ─────────────────────────────────────────────────── */

// Module-level cache so the single-argument baseStatFor(region) still resolves
// after the hook has populated it once. Written only from the query function.
let cachedManifest: BaseStatsManifest | null = null;

function num(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0;
}

function strArr(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((s): s is string => typeof s === 'string') : [];
}

/** Coerce the raw endpoint payload into a well-formed manifest, tolerating a
 *  missing endpoint or partial shape. Returns null when nothing usable. */
function normalizeManifest(input: unknown): BaseStatsManifest | null {
  if (!input || typeof input !== 'object') return null;
  const obj = input as Record<string, unknown>;

  const rawBases = Array.isArray(obj.bases) ? obj.bases : [];
  const bases: BaseStat[] = [];
  for (const b of rawBases) {
    if (!b || typeof b !== 'object') continue;
    const r = b as Record<string, unknown>;
    const region =
      typeof r.region === 'string'
        ? r.region
        : typeof r.id === 'string'
          ? r.id
          : '';
    if (!region) continue;
    bases.push({
      region,
      works: num(r.works),
      resource_lines: num(r.resource_lines),
      unique_resources: num(r.unique_resources),
      avg_resources_per_work: num(r.avg_resources_per_work),
      priced_pct: num(r.priced_pct),
      coefficient: r.coefficient === true,
      family: typeof r.family === 'string' ? r.family : undefined,
      currency: typeof r.currency === 'string' ? r.currency : undefined,
    });
  }

  const fam =
    obj.families && typeof obj.families === 'object'
      ? (obj.families as Record<string, unknown>)
      : {};

  return {
    families: {
      global_cwicr: strArr(fam.global_cwicr),
      national: strArr(fam.national),
    },
    bases,
    generated_at: typeof obj.generated_at === 'string' ? obj.generated_at : undefined,
  };
}

async function fetchBaseStats(): Promise<BaseStatsManifest | null> {
  try {
    const data = await apiGet<unknown>('/v1/costs/base-stats');
    cachedManifest = normalizeManifest(data);
    return cachedManifest;
  } catch {
    // Endpoint not available (yet) or transient error: degrade to static logic.
    return null;
  }
}

/* ── Hook + pure lookup ────────────────────────────────────────────────── */

/**
 * Live base-stats manifest, or ``null`` while loading / when the endpoint is
 * unavailable. Fail-soft: never throws, never spins a retry loop. All consumers
 * (recommendation, coverage chips) fall back to static knowledge when null.
 */
export function useBaseStats(): BaseStatsManifest | null {
  const { data } = useQuery({
    queryKey: BASE_STATS_QUERY_KEY,
    queryFn: fetchBaseStats,
    staleTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  return data ?? cachedManifest;
}

/**
 * Pure lookup of one base's stats. Pass the manifest from {@link useBaseStats}
 * when you have it; otherwise the last-seen cached manifest is used so a
 * single-argument call still resolves once the hook has run somewhere.
 */
export function baseStatFor(
  region: string,
  manifest?: BaseStatsManifest | null,
): BaseStat | undefined {
  const m = manifest ?? cachedManifest;
  if (!m || !Array.isArray(m.bases)) return undefined;
  return m.bases.find((b) => b.region === region);
}

/* ── Formatting ────────────────────────────────────────────────────────── */

/** Compact count for stat chips: grouped below 1,000 ("842"), compact above
 *  ("11.3K", "350K", "1.2M"). */
export function formatCount(n: number | null | undefined): string {
  const v = typeof n === 'number' && Number.isFinite(n) ? n : 0;
  if (v < 1000) return v.toLocaleString();
  try {
    return new Intl.NumberFormat(undefined, {
      notation: 'compact',
      maximumFractionDigits: 1,
    }).format(v);
  } catch {
    return v.toLocaleString();
  }
}

/** Normalise priced_pct (0..1 or 0..100) to a whole-number percentage, or null
 *  when there is nothing meaningful to show. */
function pricedPercent(stat: BaseStat | undefined): number | null {
  if (!stat) return null;
  const raw = stat.priced_pct;
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return null;
  const pct = raw > 1 ? raw : raw * 100;
  if (pct <= 0) return null;
  return Math.min(100, Math.round(pct));
}

/* ── BaseCoverageStat ──────────────────────────────────────────────────── */

/**
 * Compact coverage readout for one base: works, resources, and either the
 * priced share or a "coefficient book" note. Renders nothing when the manifest
 * carries no stats for the region, so it is always safe to drop in.
 */
export function BaseCoverageStat({
  region,
  manifest,
  className,
}: {
  region: string;
  manifest?: BaseStatsManifest | null;
  className?: string;
}) {
  const { t } = useTranslation();
  const stat = baseStatFor(region, manifest);
  if (!stat) return null;

  const resources = stat.unique_resources || stat.resource_lines;
  const pct = pricedPercent(stat);

  return (
    <div
      className={clsx(
        'flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-content-tertiary',
        className,
      )}
    >
      {stat.works > 0 && (
        <span className="inline-flex items-center gap-1">
          <Boxes size={12} className="shrink-0" />
          {formatCount(stat.works)} {t('costs.base_works', { defaultValue: 'works' })}
        </span>
      )}
      {resources > 0 && (
        <span className="inline-flex items-center gap-1">
          <Layers size={12} className="shrink-0" />
          {formatCount(resources)} {t('costs.base_resources', { defaultValue: 'resources' })}
        </span>
      )}
      {stat.coefficient ? (
        <span className="inline-flex items-center gap-1 text-[#b45309]">
          <Info size={12} className="shrink-0" />
          {t('costs.base_needs_prices', { defaultValue: 'norms, add prices' })}
        </span>
      ) : pct != null ? (
        <span className="inline-flex items-center gap-1">
          <CircleDollarSign size={12} className="shrink-0" />
          {pct}% {t('costs.base_priced', { defaultValue: 'priced' })}
        </span>
      ) : null}
    </div>
  );
}

/* ── WhyThisBase ───────────────────────────────────────────────────────── */

type WhyVariant = 'badge' | 'hint' | 'card';

interface WhyThisBaseProps {
  /** The base this surface is about. */
  region: string;
  /** Candidate / loaded bases for context: when provided and this region is the
   *  single best of them, the surface reads as "Recommended". */
  bases?: readonly string[];
  /** badge (self-hiding pill), hint (one-line row), card (bordered block). */
  variant?: WhyVariant;
  /** Optional manifest override; falls back to {@link useBaseStats}. */
  manifest?: BaseStatsManifest | null;
  className?: string;
}

interface WhyReason {
  /** How strongly to treat the base: the single recommended one, a plain
   *  usable priced base, or a coefficient book needing setup. */
  tone: 'recommended' | 'priced' | 'coefficient';
  text: string;
}

function useWhyReason(
  region: string,
  bases: readonly string[] | undefined,
  manifest: BaseStatsManifest | null,
): WhyReason {
  const { t } = useTranslation();
  const info = REGION_MAP[region];
  const currency = info?.currency || baseStatFor(region, manifest)?.currency || '';
  const coeff = isCoefficientBase(region, manifest);
  const global = isGlobalCwicrBase(region, manifest);
  const isTheRecommended =
    !!bases && bases.length > 0 && recommendedRegionFor(bases, { manifest }) === region;

  if (coeff) {
    return {
      tone: 'coefficient',
      text: t('costs.why_coefficient', {
        defaultValue:
          'Official norms without ready prices. Load a resource price sheet to turn it into unit rates.',
      }),
    };
  }
  if (isTheRecommended) {
    return {
      tone: 'recommended',
      text: currency
        ? t('costs.why_recommended_ccy', {
            defaultValue: 'Recommended: the fullest priced catalogue for your setup, in {{currency}}.',
            currency,
          })
        : t('costs.why_recommended', {
            defaultValue: 'Recommended: the fullest priced catalogue for your setup.',
          }),
    };
  }
  if (global) {
    return {
      tone: 'priced',
      text: currency
        ? t('costs.why_global_ccy', {
            defaultValue: 'Part of the CWICR master: 55,000+ works, priced and translated, in {{currency}}.',
            currency,
          })
        : t('costs.why_global', {
            defaultValue: 'Part of the CWICR master: 55,000+ works, priced and translated.',
          }),
    };
  }
  return {
    tone: 'priced',
    text: currency
      ? t('costs.why_national_ccy', {
          defaultValue: 'Authentic official base with local prices, in {{currency}}.',
          currency,
        })
      : t('costs.why_national', {
          defaultValue: 'Authentic official base with local prices.',
        }),
  };
}

function ReasonIcon({ tone, size = 14 }: { tone: WhyReason['tone']; size?: number }) {
  if (tone === 'recommended') return <Sparkles size={size} className="shrink-0" />;
  if (tone === 'coefficient') return <Info size={size} className="shrink-0" />;
  return <Boxes size={size} className="shrink-0" />;
}

/**
 * One reusable "why this base" surface. Reused by onboarding, the setup page and
 * the cost surfaces so the coverage story is told the same way everywhere.
 *
 * - ``badge``: a small self-hiding pill. Renders "Recommended" for the single
 *   best of ``bases``, "Coefficient book" for a norms-only base, else nothing.
 * - ``hint``: a one-line explanatory row with a coverage readout.
 * - ``card``: a bordered block with the base name, the reason and coverage.
 */
export function WhyThisBase({
  region,
  bases,
  variant = 'hint',
  manifest,
  className,
}: WhyThisBaseProps) {
  const { t } = useTranslation();
  const hookManifest = useBaseStats();
  const m = manifest ?? hookManifest;
  const reason = useWhyReason(region, bases, m);
  const info = REGION_MAP[region];

  if (variant === 'badge') {
    if (reason.tone === 'recommended') {
      return (
        <span
          className={clsx(
            'inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-1.5 text-2xs font-medium text-oe-blue-text',
            className,
          )}
        >
          <Sparkles size={10} className="shrink-0" />
          {t('costs.base_recommended', { defaultValue: 'Recommended' })}
        </span>
      );
    }
    if (reason.tone === 'coefficient') {
      return (
        <span
          className={clsx(
            'inline-flex items-center gap-1 rounded-full bg-semantic-warning-bg px-1.5 text-2xs font-medium text-[#b45309]',
            className,
          )}
        >
          <Info size={10} className="shrink-0" />
          {t('costs.base_coefficient_short', { defaultValue: 'Coefficient book' })}
        </span>
      );
    }
    return null;
  }

  if (variant === 'card') {
    return (
      <div
        className={clsx(
          'rounded-2xl border p-4',
          reason.tone === 'coefficient'
            ? 'border-semantic-warning/30 bg-semantic-warning-bg/30'
            : 'border-oe-blue/25 bg-oe-blue-subtle/25',
          className,
        )}
      >
        <div className="flex items-center gap-2">
          {info?.flag && <CountryFlag code={info.flag} size={20} className="shrink-0" />}
          <span className="text-sm font-semibold text-content-primary truncate">
            {info?.name || region}
          </span>
          {reason.tone === 'recommended' && (
            <span className="inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-1.5 text-2xs font-medium text-oe-blue-text">
              <Sparkles size={10} className="shrink-0" />
              {t('costs.base_recommended', { defaultValue: 'Recommended' })}
            </span>
          )}
        </div>
        <p className="mt-1.5 text-xs text-content-secondary leading-relaxed">{reason.text}</p>
        <BaseCoverageStat region={region} manifest={m} className="mt-2" />
      </div>
    );
  }

  // hint (default)
  return (
    <div
      className={clsx(
        'flex items-start gap-2 rounded-xl px-3 py-2',
        reason.tone === 'coefficient'
          ? 'bg-semantic-warning-bg/40'
          : 'bg-oe-blue-subtle/30',
        className,
      )}
    >
      <span
        className={clsx(
          'mt-0.5',
          reason.tone === 'coefficient' ? 'text-[#b45309]' : 'text-oe-blue-text',
        )}
      >
        <ReasonIcon tone={reason.tone} />
      </span>
      <div className="min-w-0">
        <p className="text-xs text-content-secondary">
          {info?.name && (
            <span className="font-semibold text-content-primary">{info.name} </span>
          )}
          {reason.text}
        </p>
        <BaseCoverageStat region={region} manifest={m} className="mt-1" />
      </div>
    </div>
  );
}
