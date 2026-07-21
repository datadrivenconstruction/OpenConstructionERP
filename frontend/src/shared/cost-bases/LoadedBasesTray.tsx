/**
 * Loaded cost-bases tray for the app shell.
 *
 * A compact row of flag chips - one per loaded cost base - that lets an
 * operator scope search across the bases they have installed, right from the
 * header. Each chip carries a small completeness meter (share of works that
 * are priced, or resource depth for coefficient-only bases) so the relative
 * strength of each base is legible at a glance.
 *
 * Behaviour is additive and back-compatible: a single loaded base is today's
 * behaviour, so the whole tray self-hides until there are at least two bases
 * to scope between. Clicking a chip toggles that base into the active scope;
 * the "All" chip clears the scope back to every loaded base.
 *
 * The outer component also owns hydration: on every header mount it fetches
 * the server's loaded-region list once and pushes it into the global store,
 * so scope-aware consumers elsewhere read a populated store even when the
 * tray itself stays hidden.
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Layers } from 'lucide-react';
import clsx from 'clsx';
import { apiGet } from '@/shared/lib/api';
import { CountryFlag } from '@/shared/ui';
import { useCostDatabaseStore, REGION_MAP } from '@/stores/useCostDatabaseStore';
import { useBaseStats, baseStatFor } from '@/features/costs/baseStats';

/**
 * Loose view of a single base's stats.
 *
 * `baseStats.tsx` owns the authoritative shape; the meter reads only the few
 * fields it needs, and we stay decoupled from the exact type (which lands in
 * the same wave) by reading through this local interface. Only the export
 * names `useBaseStats` / `baseStatFor` are load-bearing here.
 */
interface BaseStatLike {
  works?: number;
  priced_pct?: number;
  avg_resources_per_work?: number;
  coefficient?: boolean;
}

/** Resource depth (resources per work) that fills the depth meter fully. */
const DEPTH_FULL = 8;
/** How many chips to render before collapsing the rest into a "+N" badge. */
const MAX_CHIPS = 8;

type Meter = { pct: number; tone: 'priced' | 'depth' };

/**
 * Reduce a base's stats to a single meter value.
 *
 * Priced bases show the share of works that carry a price. Coefficient bases
 * carry no prices by design, so they fall back to a resource-depth signal
 * (resources per work) rendered in a distinct tone.
 */
function meterFor(stat: BaseStatLike | undefined): Meter | null {
  if (!stat) return null;
  const avg = stat.avg_resources_per_work;
  const depth: Meter | null =
    typeof avg === 'number' && Number.isFinite(avg) && avg > 0
      ? { pct: Math.max(8, Math.min(100, (avg / DEPTH_FULL) * 100)), tone: 'depth' }
      : null;
  // A coefficient base has no meaningful priced share - show depth instead.
  if (stat.coefficient) return depth;
  const priced = stat.priced_pct;
  if (typeof priced === 'number' && Number.isFinite(priced)) {
    return { pct: Math.max(0, Math.min(100, priced)), tone: 'priced' };
  }
  return depth;
}

export function LoadedBasesTray() {
  const loadedBases = useCostDatabaseStore((s) => s.loadedBases);
  const setLoadedBases = useCostDatabaseStore((s) => s.setLoadedBases);

  // Hydrate the store once from the server's loaded-region list. Shares the
  // ['costs','regions'] cache key used across the cost pages, so this is a
  // warm read after the first visit. React Query's structural sharing keeps
  // the reference stable while the content is unchanged, so the effect below
  // fires once and never loops.
  const { data: regions } = useQuery({
    queryKey: ['costs', 'regions'],
    queryFn: () => apiGet<string[]>('/v1/costs/regions/'),
    retry: false,
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    if (regions) setLoadedBases(regions);
  }, [regions, setLoadedBases]);

  // Self-hide the whole tray until there are at least two bases to scope
  // between. All hooks above have already run this render, so hiding here
  // never prevents the store from being hydrated.
  if (loadedBases.length <= 1) return null;

  return <LoadedBasesTrayInner bases={loadedBases} />;
}

function LoadedBasesTrayInner({ bases }: { bases: string[] }) {
  const { t } = useTranslation();
  const scope = useCostDatabaseStore((s) => s.scope);
  const toggleScopeBase = useCostDatabaseStore((s) => s.toggleScopeBase);
  const clearScope = useCostDatabaseStore((s) => s.clearScope);

  // Load the base-stats manifest so `baseStatFor` below resolves each chip's
  // meter. Called for its subscription side effect - this inner component
  // only mounts when the tray is visible, so multi-base users are the only
  // ones who trigger the fetch.
  useBaseStats();

  const allActive = scope.length === 0;

  // Keep any in-scope base visible even past the overflow cap: partition the
  // scoped bases to the front, keep the original order for the rest.
  const scoped = bases.filter((b) => scope.includes(b));
  const rest = bases.filter((b) => !scope.includes(b));
  const ordered = [...scoped, ...rest];
  const visible = ordered.slice(0, MAX_CHIPS);
  const overflow = ordered.slice(MAX_CHIPS);
  const overflowTitle = overflow.map((c) => REGION_MAP[c]?.name ?? c).join(', ');

  return (
    <div
      role="group"
      aria-label={t('cost_bases.tray_aria', { defaultValue: 'Scope by cost base' })}
      data-testid="loaded-bases-tray"
      className="hidden xl:flex items-center gap-1"
    >
      {/* Hairline + icon anchor the flag row as one "scope" control rather
          than a loose scatter of flags. */}
      <span className="mr-0.5 h-4 w-px bg-border-light/70" aria-hidden />
      <span
        aria-hidden
        className="flex h-8 w-4 items-center justify-center text-content-quaternary"
      >
        <Layers size={14} strokeWidth={1.75} />
      </span>

      <button
        type="button"
        onClick={clearScope}
        aria-pressed={allActive}
        title={t('cost_bases.all_title', {
          defaultValue: 'Search across every loaded base',
        })}
        className={clsx(
          'h-8 rounded-lg border px-2 text-2xs font-semibold transition-colors',
          allActive
            ? 'border-oe-blue/40 bg-oe-blue-subtle text-oe-blue-text'
            : 'border-border-light text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary',
        )}
      >
        {t('cost_bases.all', { defaultValue: 'All' })}
      </button>

      {visible.map((code) => (
        <BaseChip
          key={code}
          code={code}
          active={scope.includes(code)}
          onToggle={() => toggleScopeBase(code)}
        />
      ))}

      {overflow.length > 0 && (
        <span
          title={overflowTitle}
          className="flex h-8 items-center rounded-lg border border-dashed border-border-light px-1.5 text-2xs font-medium text-content-quaternary"
        >
          +{overflow.length}
        </span>
      )}
    </div>
  );
}

function BaseChip({
  code,
  active,
  onToggle,
}: {
  code: string;
  active: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  const info = REGION_MAP[code];
  const name = info?.name ?? info?.label ?? code;
  // Every REGION_MAP key except the CUSTOM placeholder resolves to a flag via
  // CountryFlag's region-key handling; user catalogs and CUSTOM fall back to a
  // two-letter monogram so the chip is never blank.
  const showFlag = Boolean(info) && code !== 'CUSTOM';

  const stat = baseStatFor(code) as unknown as BaseStatLike | undefined;
  const meter = meterFor(stat);

  let detail = '';
  if (meter?.tone === 'priced') {
    detail = t('cost_bases.chip_priced', {
      defaultValue: '{{pct}}% priced',
      pct: Math.round(meter.pct),
    });
  } else if (meter?.tone === 'depth' && typeof stat?.avg_resources_per_work === 'number') {
    detail = t('cost_bases.chip_depth', {
      defaultValue: '{{n}} resources per work (coefficient base)',
      n: stat.avg_resources_per_work.toFixed(1),
    });
  }
  const title = detail ? `${name} - ${detail}` : name;

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={active}
      aria-label={title}
      title={title}
      className={clsx(
        'relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg border transition-colors',
        active
          ? 'border-oe-blue/40 bg-oe-blue-subtle'
          : 'border-border-light bg-surface-primary/50 hover:bg-surface-secondary',
      )}
    >
      {showFlag ? (
        <CountryFlag code={code} size={16} />
      ) : (
        <span className="text-[10px] font-semibold text-content-secondary">
          {name.slice(0, 2).toUpperCase()}
        </span>
      )}
      {meter && (
        <>
          <span className="absolute inset-x-0 bottom-0 h-[3px] bg-border-light/60" aria-hidden />
          <span
            aria-hidden
            className={clsx(
              'absolute bottom-0 left-0 h-[3px]',
              meter.tone === 'priced' ? 'bg-emerald-500' : 'bg-amber-500',
            )}
            style={{ width: `${meter.pct}%` }}
          />
        </>
      )}
    </button>
  );
}
