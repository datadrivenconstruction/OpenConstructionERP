// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Courses and guides": every course, checklist and guide of the Academy that
// the app knows a screen for, filterable by kind, topic, track, country and
// screen. Each card is a plain link that opens the Academy in a new tab.
// Filters live in the URL, so a link from a module screen lands on its list.

import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { GraduationCap, Search, SearchX, X } from 'lucide-react';
import { navGroups } from '@/app/layout/navCatalog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { AcademyItemCard } from './AcademyItemLinks';
import { ITEMS, allTopics, allTracks, filterItems, topicLabel, type ItemFilters } from './academyItems';
import { useVideoContext } from './useVideoContext';
import { useVideoLabels } from './videoLabels';
import { useVideosStore } from './useVideosStore';

const KINDS = ['course', 'checklist', 'guide'] as const;
const KIND_LABEL: Record<(typeof KINDS)[number], [key: string, fallback: string]> = {
  course: ['learn.kind.course', 'Course'],
  checklist: ['learn.kind.checklist', 'Checklist'],
  guide: ['learn.kind.article', 'Guide'],
};

function filtersFromParams(params: URLSearchParams): ItemFilters {
  const kind = params.get('kind');
  return {
    kind: (KINDS as readonly string[]).includes(kind ?? '') ? (kind as ItemFilters['kind']) : null,
    topic: params.get('topic'),
    track: params.get('track'),
    route: params.get('route'),
    query: params.get('q') ?? '',
  };
}

export function CoursesPage() {
  const { t } = useTranslation();
  const labels = useVideoLabels();
  const ctx = useVideoContext();
  const marketChoice = useVideosStore((s) => s.market);
  const setMarket = useVideosStore((s) => s.setMarket);
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => filtersFromParams(params), [params]);

  const patch = useCallback(
    (next: Record<string, string | null>) => {
      setParams(
        (prev) => {
          const out = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(next)) {
            if (v === null || v === '') out.delete(k);
            else out.set(k, v);
          }
          return out;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const reader = useMemo(
    () => ({ language: ctx.language, market: ctx.market, anyMarket: ctx.marketSource === 'any' }),
    [ctx.language, ctx.market, ctx.marketSource],
  );
  const hits = useMemo(() => filterItems(filters, reader), [filters, reader]);
  const topics = useMemo(() => allTopics(), []);
  const tracks = useMemo(() => allTracks(), []);
  const markets = useMemo(() => [...new Set(ITEMS.map((i) => i.market).filter((m): m is string => Boolean(m)))].sort(), []);
  const filtered = Boolean(filters.kind || filters.topic || filters.track || filters.route || filters.query);
  const all = t('common.all', { defaultValue: 'All' });

  const moduleName = (route: string) => {
    for (const group of navGroups) {
      const item = group.items.find((i) => i.to === route);
      if (item) return t(item.labelKey, { defaultValue: item.defaultLabel ?? route });
    }
    return route;
  };
  const clearFilters = () => patch({ kind: null, topic: null, track: null, route: null, q: null });
  const selectCls =
    'max-w-[13rem] cursor-pointer rounded-lg border bg-surface-primary px-2 py-1 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/20';

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4 animate-fade-in" data-testid="courses-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
            <GraduationCap size={16} aria-hidden />
          </span>
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight text-content-primary">
              {t('nav.courses', { defaultValue: 'Courses and guides' })}
            </h1>
            <p className="text-xs text-content-secondary">
              {t('learn.page_subtitle', {
                defaultValue:
                  'Short courses, checklists and guides from OpenConstruction Academy. Opens in your browser.',
              })}
            </p>
          </div>
        </div>
        <div className="relative w-full sm:w-72">
          <Search size={15} className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-content-tertiary" aria-hidden />
          <input
            type="search"
            value={filters.query}
            onChange={(e) => patch({ q: e.target.value })}
            placeholder={t('common.search', { defaultValue: 'Search' })}
            aria-label={t('common.search', { defaultValue: 'Search' })}
            data-testid="courses-search"
            className="w-full rounded-xl border border-border-light bg-surface-secondary/50 py-2 ps-9 pe-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue/50 focus:bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
          />
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <div role="group" aria-label={t('nav.courses', { defaultValue: 'Courses and guides' })} className="flex flex-wrap gap-1.5">
          {[null, ...KINDS].map((kind) => {
            const active = filters.kind === kind;
            return (
              <button
                key={kind ?? 'all'}
                type="button"
                aria-pressed={active}
                onClick={() => patch({ kind })}
                data-testid={`courses-kind-${kind ?? 'all'}`}
                className={clsx(
                  'rounded-full border px-3 py-1 font-medium transition-colors motion-reduce:transition-none focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                  active
                    ? 'border-oe-blue/50 bg-oe-blue/10 text-oe-blue'
                    : 'border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue',
                )}
              >
                {kind ? t(KIND_LABEL[kind][0], { defaultValue: KIND_LABEL[kind][1] }) : all}
              </button>
            );
          })}
        </div>
        <label className="inline-flex items-center gap-1.5">
          <span className="text-content-tertiary">{t('learn.filter.topic', { defaultValue: 'Topic' })}</span>
          <select
            value={filters.topic ?? ''}
            onChange={(e) => patch({ topic: e.target.value || null })}
            data-testid="courses-filter-topic"
            className={clsx(selectCls, filters.topic ? 'border-oe-blue/50' : 'border-border-light')}
          >
            <option value="">{all}</option>
            {topics.map((topic) => (
              <option key={topic} value={topic}>
                {topicLabel(topic)}
              </option>
            ))}
          </select>
        </label>
        <label className="inline-flex items-center gap-1.5">
          <span className="text-content-tertiary">{t('learn.filter.track', { defaultValue: 'Track' })}</span>
          <select
            value={filters.track ?? ''}
            onChange={(e) => patch({ track: e.target.value || null })}
            data-testid="courses-filter-track"
            className={clsx(selectCls, filters.track ? 'border-oe-blue/50' : 'border-border-light')}
          >
            <option value="">{all}</option>
            {tracks.map((track) => (
              <option key={track} value={track}>
                {track}
              </option>
            ))}
          </select>
        </label>
        <label className="inline-flex items-center gap-1.5">
          <span className="text-content-tertiary">{t('videos.country', { defaultValue: 'Country' })}</span>
          <select
            value={marketChoice}
            onChange={(e) => setMarket(e.target.value)}
            data-testid="courses-market-select"
            className={clsx(selectCls, 'border-border-light')}
          >
            <option value="auto">
              {ctx.marketSource && ctx.marketSource !== 'chosen' && ctx.marketSource !== 'any' && ctx.market
                ? labels.country(ctx.market)
                : t('videos.market_auto', { defaultValue: 'Automatic' })}
            </option>
            <option value="any">{t('videos.market_any', { defaultValue: 'Any country' })}</option>
            {markets.map((m) => (
              <option key={m} value={m}>
                {labels.country(m)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {filters.route && (
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-content-secondary">
          <span
            data-testid="courses-route-chip"
            className="inline-flex items-center gap-1 rounded-full border border-oe-blue/40 bg-oe-blue/[0.06] py-0.5 ps-2.5 pe-1 font-medium text-oe-blue"
          >
            {t('learn.filter.this_screen', {
              defaultValue: 'This screen only: {{module}}',
              module: moduleName(filters.route),
            })}
            <button
              type="button"
              onClick={() => patch({ route: null })}
              aria-label={t('common.clear', { defaultValue: 'Clear' })}
              className="rounded-full p-0.5 hover:bg-oe-blue/15"
            >
              <X size={11} aria-hidden />
            </button>
          </span>
        </p>
      )}

      {hits.length === 0 ? (
        <EmptyState
          icon={<SearchX size={24} aria-hidden />}
          title={t('learn.empty_title', { defaultValue: 'Nothing matches these filters' })}
          action={filtered ? { label: t('common.clear_filters', { defaultValue: 'Clear filters' }), onClick: clearFilters } : undefined}
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="courses-grid">
          {hits.map((item) => (
            <li key={item.id} className="flex">
              <div className="flex w-full flex-col [&>a]:h-full">
                <AcademyItemCard item={item} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
