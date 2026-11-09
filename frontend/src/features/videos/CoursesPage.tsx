// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Courses and guides": every course, checklist and guide of the Academy that
// the app knows a screen for, filterable by type, price, country, length,
// topic, track and screen. Each card is a plain link that opens the Academy in
// a new tab. Filters live in the URL, so a link from a module screen lands on
// its list.

import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Search, SearchX, SlidersHorizontal, X } from 'lucide-react';
import { navGroups } from '@/app/layout/navCatalog';
import { CountryFlag } from '@/shared/ui/CountryFlag';
import { EmptyState } from '@/shared/ui/EmptyState';
import { PageHeader } from '@/shared/ui/PageHeader';
import { AcademyItemCard } from './AcademyItemLinks';
import {
  DURATION_KEYS,
  ITEMS,
  UNIVERSAL,
  allTopics,
  allTracks,
  facetCounts,
  filterItems,
  topicLabel,
  type DurationBucket,
  type FilterDimension,
  type ItemFilters,
  type ItemSort,
} from './academyItems';
import { useVideoContext } from './useVideoContext';
import { useVideoLabels } from './videoLabels';

const KINDS = ['course', 'checklist', 'guide'] as const;
const KIND_LABEL: Record<(typeof KINDS)[number], [key: string, fallback: string]> = {
  course: ['learn.kind.course', 'Course'],
  checklist: ['learn.kind.checklist', 'Checklist'],
  guide: ['learn.kind.article', 'Guide'],
};
const ACCESS = ['free', 'paid'] as const;
const ACCESS_LABEL: Record<(typeof ACCESS)[number], [key: string, fallback: string]> = {
  free: ['learn.access.free', 'Free'],
  paid: ['learn.access.paid', 'Paid training'],
};
const LENGTH_LABEL: Record<DurationBucket, [key: string, fallback: string]> = {
  short: ['learn.length.short', 'Up to 3 h'],
  medium: ['learn.length.medium', '3 to 4 h'],
  long: ['learn.length.long', 'Over 4 h'],
};
const SORTS: readonly ItemSort[] = ['recommended', 'shortest', 'az'];
const SORT_LABEL: Record<ItemSort, [key: string, fallback: string]> = {
  recommended: ['learn.sort.recommended', 'Recommended'],
  shortest: ['learn.sort.shortest', 'Shortest first'],
  az: ['learn.sort.az', 'A to Z'],
};
const DIMENSIONS: FilterDimension[] = ['kind', 'access', 'country', 'topic', 'track', 'duration'];
const PARAM: Record<FilterDimension, string> = {
  kind: 'kind',
  access: 'access',
  country: 'country',
  topic: 'topic',
  track: 'track',
  duration: 'time',
};

function pick<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return allowed.includes(value as T) ? (value as T) : null;
}

function filtersFromParams(params: URLSearchParams): ItemFilters {
  return {
    kind: pick(params.get('kind'), KINDS),
    topic: params.get('topic'),
    track: params.get('track'),
    route: params.get('route'),
    query: params.get('q') ?? '',
    access: pick(params.get('access'), ACCESS),
    country: params.get('country'),
    duration: pick(params.get('time'), DURATION_KEYS),
    sort: pick(params.get('sort'), SORTS) ?? 'recommended',
  };
}

function Chip({
  active,
  onClick,
  testId,
  count,
  children,
}: {
  active: boolean;
  onClick: () => void;
  testId: string;
  count?: number;
  children: ReactNode;
}) {
  const empty = count === 0 && !active;
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={empty}
      onClick={onClick}
      data-testid={testId}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium transition-colors motion-reduce:transition-none focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
        active
          ? 'border-oe-blue/50 bg-oe-blue/10 text-oe-blue'
          : 'border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue',
        empty && 'cursor-not-allowed opacity-45 hover:border-border-light hover:text-content-secondary',
      )}
    >
      {children}
      {count !== undefined && <span className="tabular-nums text-content-tertiary">{count}</span>}
    </button>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 sm:flex-nowrap sm:items-start">
      <span className="w-full shrink-0 pt-1 text-content-tertiary sm:w-20">{label}</span>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">{children}</div>
    </div>
  );
}

interface ActiveChip {
  dim: FilterDimension | 'q';
  node: ReactNode;
  text: string;
  clear: () => void;
}

export function CoursesPage() {
  const { t } = useTranslation();
  const labels = useVideoLabels();
  const ctx = useVideoContext();
  const [params, setParams] = useSearchParams();
  const [panelOpen, setPanelOpen] = useState(false);
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

  // Every country's material is listed; the reader's own market only ranks first.
  const reader = useMemo(
    () => ({ language: ctx.language, market: ctx.market, anyMarket: true }),
    [ctx.language, ctx.market],
  );
  const hits = useMemo(() => filterItems(filters, reader), [filters, reader]);
  const facets = useMemo(
    () => Object.fromEntries(DIMENSIONS.map((d) => [d, facetCounts(d, filters, reader)])) as Record<FilterDimension, Map<string, number>>,
    [filters, reader],
  );
  const topics = useMemo(() => allTopics(), []);
  const tracks = useMemo(() => allTracks(), []);
  // Most material first, so the reader sees which country has most.
  const countries = useMemo(() => {
    const own = new Map<string, number>();
    for (const i of ITEMS) {
      const c = i.country ?? i.market;
      if (c) own.set(c, (own.get(c) ?? 0) + 1);
    }
    return [...own.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([m]) => m);
  }, []);

  const count = (dim: FilterDimension, value: string) => facets[dim].get(value) ?? 0;
  const all = t('common.all', { defaultValue: 'All' });
  const label = (pair: [string, string]) => t(pair[0], { defaultValue: pair[1] });
  const countryLabel = (m: string) =>
    m === UNIVERSAL ? t('learn.filter.universal', { defaultValue: 'Universal' }) : labels.country(m);
  const set = (dim: FilterDimension, value: string | null) => patch({ [PARAM[dim]]: value });

  const active: ActiveChip[] = [];
  const addActive = (dim: FilterDimension, text: string, flag?: string) =>
    active.push({
      dim,
      text,
      node: (
        <>
          {flag && <CountryFlag code={flag} size={14} />}
          {text}
        </>
      ),
      clear: () => set(dim, null),
    });
  if (filters.kind) addActive('kind', label(KIND_LABEL[filters.kind as (typeof KINDS)[number]]));
  if (filters.access) addActive('access', label(ACCESS_LABEL[filters.access]));
  if (filters.country) {
    addActive('country', countryLabel(filters.country), filters.country === UNIVERSAL ? undefined : filters.country);
  }
  if (filters.duration) addActive('duration', label(LENGTH_LABEL[filters.duration]));
  if (filters.topic) addActive('topic', topicLabel(filters.topic));
  if (filters.track) addActive('track', filters.track);
  const typed = filters.query.trim();
  if (typed) active.push({ dim: 'q', text: typed, node: `“${typed}”`, clear: () => patch({ q: null }) });

  const filtered = active.length > 0 || Boolean(filters.route);
  const panelCount = active.filter((a) => a.dim !== 'q').length;

  const moduleName = (route: string) => {
    for (const group of navGroups) {
      const item = group.items.find((i) => i.to === route);
      if (item) return t(item.labelKey, { defaultValue: item.defaultLabel ?? route });
    }
    return route;
  };
  const clearFilters = () =>
    patch({ kind: null, topic: null, track: null, route: null, q: null, access: null, country: null, time: null, sort: null });
  const selectCls =
    'max-w-full cursor-pointer rounded-lg border bg-surface-primary px-2 py-1 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/20';

  return (
    <div className="space-y-5 animate-fade-in" data-testid="courses-page">
      <PageHeader
        srTitle={t('nav.courses', { defaultValue: 'Courses and guides' })}
        subtitle={t('learn.page_subtitle', {
          defaultValue:
            'Short courses, checklists and guides from OpenConstruction Academy. Opens in your browser.',
        })}
        actions={
          <div className="flex w-full items-center gap-2 sm:w-auto">
            <div className="relative min-w-0 flex-1 sm:w-72 sm:flex-none">
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
            <button
              type="button"
              aria-expanded={panelOpen}
              aria-controls="courses-filter-panel"
              onClick={() => setPanelOpen((v) => !v)}
              data-testid="courses-filters-toggle"
              className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-border-light bg-surface-primary px-3 py-2 text-sm font-medium text-content-secondary hover:border-oe-blue/40 md:hidden"
            >
              <SlidersHorizontal size={15} aria-hidden />
              {t('learn.filters', { defaultValue: 'Filters' })}
              {panelCount > 0 && <span className="rounded-full bg-oe-blue px-1.5 text-2xs text-white">{panelCount}</span>}
            </button>
          </div>
        }
      />

      <div
        id="courses-filter-panel"
        data-testid="courses-filter-panel"
        className={clsx(
          'space-y-2.5 rounded-xl border border-border-light bg-surface-elevated p-3 text-xs md:block',
          !panelOpen && 'hidden',
        )}
      >
        <Row label={t('learn.filter.type', { defaultValue: 'Type' })}>
          <Chip
            active={!filters.kind}
            onClick={() => set('kind', null)}
            testId="courses-kind-all"
            count={[...facets.kind.values()].reduce((a, b) => a + b, 0)}
          >
            {all}
          </Chip>
          {KINDS.map((kind) => (
            <Chip
              key={kind}
              active={filters.kind === kind}
              onClick={() => set('kind', kind)}
              testId={`courses-kind-${kind}`}
              count={count('kind', kind)}
            >
              {label(KIND_LABEL[kind])}
            </Chip>
          ))}
        </Row>
        <Row label={t('learn.filter.price', { defaultValue: 'Price' })}>
          <Chip
            active={!filters.access}
            onClick={() => set('access', null)}
            testId="courses-access-all"
            count={[...facets.access.values()].reduce((a, b) => a + b, 0)}
          >
            {all}
          </Chip>
          {ACCESS.map((a) => (
            <Chip
              key={a}
              active={filters.access === a}
              onClick={() => set('access', a)}
              testId={`courses-access-${a}`}
              count={count('access', a)}
            >
              {label(ACCESS_LABEL[a])}
            </Chip>
          ))}
        </Row>
        <Row label={t('videos.country', { defaultValue: 'Country' })}>
          <Chip
            active={!filters.country}
            onClick={() => set('country', null)}
            testId="courses-country-all"
            count={[...facets.country.values()].reduce((a, b) => a + b, 0)}
          >
            {t('learn.filter.all_countries', { defaultValue: 'All countries' })}
          </Chip>
          {countries.map((m) => (
            <Chip
              key={m}
              active={filters.country === m}
              onClick={() => set('country', m)}
              testId={`courses-country-${m}`}
              count={count('country', m)}
            >
              <CountryFlag code={m} size={16} />
              {countryLabel(m)}
            </Chip>
          ))}
          <Chip
            active={filters.country === UNIVERSAL}
            onClick={() => set('country', UNIVERSAL)}
            testId="courses-country-none"
            count={count('country', UNIVERSAL)}
          >
            {countryLabel(UNIVERSAL)}
          </Chip>
        </Row>
        <Row label={t('learn.filter.length', { defaultValue: 'Length' })}>
          <Chip active={!filters.duration} onClick={() => set('duration', null)} testId="courses-time-all">
            {all}
          </Chip>
          {DURATION_KEYS.map((d) => (
            <Chip
              key={d}
              active={filters.duration === d}
              onClick={() => set('duration', d)}
              testId={`courses-time-${d}`}
              count={count('duration', d)}
            >
              {label(LENGTH_LABEL[d])}
            </Chip>
          ))}
        </Row>
        <Row label={t('learn.filter.topic', { defaultValue: 'Topic' })}>
          <select
            value={filters.topic ?? ''}
            onChange={(e) => set('topic', e.target.value || null)}
            aria-label={t('learn.filter.topic', { defaultValue: 'Topic' })}
            data-testid="courses-filter-topic"
            className={clsx(selectCls, filters.topic ? 'border-oe-blue/50' : 'border-border-light')}
          >
            <option value="">{all}</option>
            {topics
              .filter((topic) => count('topic', topic) > 0 || topic === filters.topic)
              .map((topic) => (
                <option key={topic} value={topic}>
                  {topicLabel(topic)} ({count('topic', topic)})
                </option>
              ))}
          </select>
          <span className="ms-2 text-content-tertiary">{t('learn.filter.track', { defaultValue: 'Track' })}</span>
          <select
            value={filters.track ?? ''}
            onChange={(e) => set('track', e.target.value || null)}
            aria-label={t('learn.filter.track', { defaultValue: 'Track' })}
            data-testid="courses-filter-track"
            className={clsx(selectCls, filters.track ? 'border-oe-blue/50' : 'border-border-light')}
          >
            <option value="">{all}</option>
            {tracks
              .filter((track) => count('track', track) > 0 || track === filters.track)
              .map((track) => (
                <option key={track} value={track}>
                  {track} ({count('track', track)})
                </option>
              ))}
          </select>
        </Row>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
        <p className="font-medium text-content-primary" aria-live="polite" data-testid="courses-count">
          {t('learn.results', {
            count: hits.length,
            defaultValue_one: '{{count}} result',
            defaultValue_other: '{{count}} results',
          })}
        </p>
        {active.map((a) => (
          <span
            key={a.dim}
            data-testid={`courses-active-${a.dim}`}
            className="inline-flex items-center gap-1.5 rounded-full border border-oe-blue/40 bg-oe-blue/[0.06] py-0.5 ps-2.5 pe-1 font-medium text-oe-blue"
          >
            {a.node}
            <button
              type="button"
              onClick={a.clear}
              aria-label={t('learn.filter.remove', { defaultValue: 'Remove filter: {{filter}}', filter: a.text })}
              className="rounded-full p-0.5 hover:bg-oe-blue/15"
            >
              <X size={11} aria-hidden />
            </button>
          </span>
        ))}
        {filtered && hits.length > 0 && (
          <button type="button" onClick={clearFilters} data-testid="courses-clear" className="font-medium text-oe-blue hover:underline">
            {t('common.clear_filters', { defaultValue: 'Clear filters' })}
          </button>
        )}
        <label className="ms-auto inline-flex items-center gap-1.5">
          <span className="text-content-tertiary">{t('learn.sort.label', { defaultValue: 'Sort' })}</span>
          <select
            value={filters.sort ?? 'recommended'}
            onChange={(e) => patch({ sort: e.target.value === 'recommended' ? null : e.target.value })}
            data-testid="courses-sort"
            className={clsx(selectCls, 'border-border-light')}
          >
            {SORTS.map((s) => (
              <option key={s} value={s}>
                {label(SORT_LABEL[s])}
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
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="courses-grid">
          {hits.map((item) => (
            <li key={item.id} className="flex">
              <div className="flex w-full flex-col [&>a]:h-full">
                <AcademyItemCard item={item} media countryName={item.country ?? item.market ? labels.country((item.country ?? item.market)!) : undefined} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
