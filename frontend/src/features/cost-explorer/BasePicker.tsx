// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The price-base picker used by every Cost Explorer tab that can narrow a
// search to one base.
//
// It replaced a plain <select> that listed nothing but the raw base ids
// ("DE_BERLIN", "TR_ISTANBUL"). Those ids answer none of the questions someone
// choosing between bases actually has: which market does it price, in what
// currency, how big is it, which norm system is it built on. Every one of those
// facts was already published by the backend registry and simply never reached
// this screen. So each base now announces itself, and "all bases" names the
// bases it covers instead of leaving the reader to guess how many there are.
//
// Price vintage is deliberately absent. `oe_costs_item.price_as_of` exists but
// nothing on the CWICR import path writes it, so a "prices from" line would
// read "unknown" on every row of a normal install and would teach the reader
// that this panel prints decoration. When the importer records a price date,
// this is the place to show it.

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Check, ChevronDown, Globe2, Layers } from 'lucide-react';
import { Link } from 'react-router-dom';
import { CountryFlag } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { fmtList, formatNumber } from '@/shared/lib/formatters';
import { useBaseCatalog } from '@/features/costs/baseCatalog';
import { listRegions } from './api';
import { describeBases, type LoadedBase } from './baseInfo';

interface RegionStat {
  region: string;
  count: number;
}

/** React Query hook for the loaded base ids (the values search accepts). */
export function useRegions() {
  return useQuery({
    queryKey: ['cost-explorer', 'regions'],
    queryFn: listRegions,
    staleTime: 5 * 60_000,
  });
}

/** Live row count per base. Shared cache key with the other pages that read it. */
function useRegionCounts() {
  return useQuery({
    queryKey: ['costs', 'region-stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats/').catch(() => [] as RegionStat[]),
    staleTime: 5 * 60_000,
  });
}

/** Every loaded base, decorated with everything the registry knows about it. */
export function useLoadedBases(): { bases: LoadedBase[]; isLoading: boolean } {
  const regions = useRegions();
  const catalog = useBaseCatalog();
  const counts = useRegionCounts();

  const countMap = useMemo(() => {
    const m: Record<string, number> = {};
    for (const s of counts.data ?? []) m[s.region] = s.count;
    return m;
  }, [counts.data]);

  const bases = useMemo(
    () => describeBases(regions.data, catalog.data, countMap),
    [regions.data, catalog.data, countMap],
  );

  return { bases, isLoading: regions.isLoading };
}

export interface BaseSelectProps {
  /** The selected base id, or '' for "all bases". */
  value: string;
  onChange: (region: string) => void;
  /** Label for the "no filter" option; defaults to "All bases". */
  allLabel?: string;
  id?: string;
}

/**
 * A base picker that says what each base is.
 *
 * Collapsed it shows the chosen base's flag, market and currency; opened it
 * lists every loaded base with its id, currency, size and norm system, plus an
 * "all bases" row that names the bases it searches. Selecting stays on the
 * page - nobody has to visit the cost database to find out what they own.
 */
export function BaseSelect({ value, onChange, allLabel, id }: BaseSelectProps) {
  const { t } = useTranslation();
  const { bases, isLoading } = useLoadedBases();
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  // Close on an outside click or Escape. Escape returns focus to the trigger so
  // keyboard users are not dropped at the top of the document.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const selected = bases.find((b) => b.region === value) ?? null;
  const everything = allLabel ?? t('costExplorer.region.all', { defaultValue: 'All bases' });

  function pick(region: string) {
    onChange(region);
    setOpen(false);
    buttonRef.current?.focus();
  }

  return (
    <div className="relative" ref={boxRef}>
      <button
        id={id}
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t('costExplorer.base.change', { defaultValue: 'Choose the price base to search' })}
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-border bg-surface-primary px-3 text-left text-sm text-content-primary hover:border-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
      >
        {selected ? (
          <CountryFlag code={selected.flag} size={16} />
        ) : (
          <Globe2 className="h-4 w-4 shrink-0 text-content-tertiary" aria-hidden />
        )}
        <span className="min-w-0 flex-1 truncate">
          {selected ? selected.market : everything}
          {selected?.currency ? (
            <span className="text-content-tertiary"> · {selected.currency}</span>
          ) : null}
        </span>
        {!selected && bases.length > 0 && (
          <span className="shrink-0 rounded-full bg-surface-tertiary px-1.5 text-2xs font-semibold tabular-nums text-content-secondary">
            {bases.length}
          </span>
        )}
        <ChevronDown className="h-4 w-4 shrink-0 text-content-tertiary" aria-hidden />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={t('costExplorer.base.change', { defaultValue: 'Choose the price base to search' })}
          className="absolute right-0 z-30 mt-1 max-h-96 w-[min(24rem,calc(100vw-2rem))] overflow-y-auto rounded-lg border border-border bg-surface-primary p-1 shadow-lg"
        >
          <BaseRow
            selected={value === ''}
            onPick={() => pick('')}
            icon={<Globe2 className="h-4 w-4 text-content-tertiary" aria-hidden />}
            title={everything}
            // No market list on this row: the rows underneath already are that
            // list, and the scope note under the filters names the bases when
            // the picker is shut, which is when the reader cannot see them.
            lines={[
              t('costExplorer.base.allDesc', {
                defaultValue: 'Every base you have loaded is searched together.',
              }),
            ]}
          />

          {bases.length > 0 && <div className="my-1 border-t border-border-light" />}

          {bases.map((b) => (
            <BaseRow
              key={b.region}
              selected={value === b.region}
              onPick={() => pick(b.region)}
              icon={<CountryFlag code={b.flag} size={16} />}
              title={b.city ? `${b.market} · ${b.city}` : b.market}
              lines={[
                [
                  b.region,
                  b.currency,
                  // `n` carries the already-grouped figure rather than i18next's
                  // `count`: a cost base never holds one row, so the plural
                  // machinery would buy nothing, and passing the raw number
                  // would print it ungrouped in every locale.
                  b.positions === null
                    ? ''
                    : t('costExplorer.base.positions', {
                        defaultValue: '{{n}} positions',
                        n: formatNumber(b.positions),
                      }),
                ]
                  .filter(Boolean)
                  .join('  ·  '),
                b.known
                  ? b.normSystem
                  : t('costExplorer.base.custom', { defaultValue: 'Imported base, not in the catalogue' }),
              ]}
            />
          ))}

          {bases.length === 0 && (
            <div className="px-3 py-4 text-xs text-content-tertiary">
              {isLoading ? (
                t('costExplorer.base.loading', { defaultValue: 'Reading the loaded bases...' })
              ) : (
                <>
                  {t('costExplorer.base.none', { defaultValue: 'No cost base is loaded yet.' })}{' '}
                  <Link to="/costs" className="font-medium text-oe-blue-text hover:underline">
                    {t('costExplorer.base.noneAction', { defaultValue: 'Load one in the cost database' })}
                  </Link>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** One row of the picker: an icon, a title, and up to two muted detail lines. */
function BaseRow({
  selected,
  onPick,
  icon,
  title,
  lines,
}: {
  selected: boolean;
  onPick: () => void;
  icon: ReactNode;
  title: string;
  lines: string[];
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={onPick}
      className={`flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-surface-secondary focus:bg-surface-secondary focus:outline-none ${
        selected ? 'bg-surface-secondary' : ''
      }`}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-content-primary">{title}</span>
        {lines.filter(Boolean).map((line) => (
          <span key={line} className="mt-0.5 block truncate text-2xs text-content-tertiary">
            {line}
          </span>
        ))}
      </span>
      {selected && <Check className="mt-0.5 h-4 w-4 shrink-0 text-oe-blue" aria-hidden />}
    </button>
  );
}

/**
 * A one-line summary of what the current selection searches, for panels that
 * want the state readable without opening the picker. Renders nothing until the
 * bases are known, so it never flashes a wrong count.
 */
export function BaseScopeNote({ value }: { value: string }) {
  const { t } = useTranslation();
  const { bases } = useLoadedBases();
  if (bases.length === 0) return null;

  const selected = bases.find((b) => b.region === value);
  if (selected) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-content-tertiary">
        <Layers className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {t('costExplorer.base.scopeOne', {
          defaultValue: 'Searching {{market}} only.',
          market: selected.market,
        })}
      </p>
    );
  }
  return (
    <p className="flex items-center gap-1.5 text-xs text-content-tertiary">
      <Layers className="h-3.5 w-3.5 shrink-0" aria-hidden />
      {t('costExplorer.base.scopeAll', {
        defaultValue: 'Searching every loaded base: {{list}}.',
        list: fmtList(bases.map((b) => b.market)),
      })}
    </p>
  );
}
