// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Courses, checklists and guides of the Academy site: which ones fit a screen
// and a reader, which URL to open, and how an item is described. Pure
// functions over the generated list, so the popover, the hub and the command
// palette rank and link the same way. Imports the catalogue, so only lazy
// chunks may import this file.

import type { AcademyItem, AcademyItemKind } from './academyTypes';
import { ACADEMY_ITEMS } from './academyItems.generated';
import { fuzzyScore } from '@/shared/lib/actions/fuzzy';
import { fold } from './academy';

export const ITEMS: AcademyItem[] = ACADEMY_ITEMS;

const KIND_RANK: Record<AcademyItemKind, number> = { course: 0, lesson: 1, checklist: 2, article: 3 };

export interface ItemReader {
  /** Interface language tag as i18next reports it, e.g. `pt-BR`. */
  language: string;
  /** Reader's market, ISO alpha-2, or null. */
  market: string | null;
  /** The reader chose "any country": market-bound items are shown too. */
  anyMarket?: boolean;
}

export function baseLanguage(tag: string): string {
  return (tag.split(/[-_]/)[0] || 'en').toLowerCase();
}

/** The Academy URL in the reader's language: full tag first (`pt-BR`), then its
 *  base (`pt`), else the English canonical address. */
export function academyUrlFor(item: AcademyItem, language: string): string {
  const tag = language.replace('_', '-');
  const parts = tag.split('-');
  const full = parts.length > 1 ? `${parts[0]!.toLowerCase()}-${parts[1]!.toUpperCase()}` : tag.toLowerCase();
  const prefix = [full, baseLanguage(tag)].find((c) => item.languages.includes(c));
  if (!prefix || prefix === 'en') return item.url;
  const url = new URL(item.url);
  return `${url.origin}/${prefix}${url.pathname}`;
}

/** The language the reader will read at the other end: the item's own for a
 *  course or checklist, the page language for a guide that the site translates. */
export function readingLanguage(item: AcademyItem, language: string): string {
  if (item.kind !== 'article') return item.contentLanguage;
  const url = academyUrlFor(item, language);
  const path = new URL(url).pathname.split('/')[1] ?? '';
  return item.languages.includes(path) ? path : 'en';
}

/** Whether the item's content language differs from the interface language. */
export function inOtherLanguage(item: AcademyItem, language: string): string | null {
  const content = readingLanguage(item, language);
  return baseLanguage(content) === baseLanguage(language) ? null : content;
}

/** An item bound to a market is shown only to a reader of that market. */
export function visibleInMarket(item: AcademyItem, reader: Pick<ItemReader, 'market' | 'anyMarket'>): boolean {
  if (!item.market || reader.anyMarket) return true;
  return item.market === reader.market;
}

function score(item: AcademyItem, reader: ItemReader): [number, number, number, number] {
  return [
    baseLanguage(item.contentLanguage) === baseLanguage(reader.language) ? 0 : 1,
    reader.market && item.market === reader.market ? 0 : 1,
    KIND_RANK[item.kind],
    item.access === 'free' ? 0 : 1,
  ];
}

/** Best fit first: language, market, kind, then free before paid; catalogue order breaks ties. */
export function rankItems(items: readonly AcademyItem[], reader: ItemReader): AcademyItem[] {
  return items
    .map((item, index) => ({ item, index, s: score(item, reader) }))
    .sort((a, b) => {
      for (let i = 0; i < a.s.length; i += 1) if (a.s[i] !== b.s[i]) return a.s[i]! - b.s[i]!;
      return a.index - b.index;
    })
    .map((x) => x.item);
}

export function itemsForRoute(route: string, items: readonly AcademyItem[] = ITEMS): AcademyItem[] {
  const base = route.split('?')[0] ?? route;
  return items.filter((i) => i.routes.includes(base));
}

/** What the popover lists: at most `limit` rows, at most one of them paid. */
export function itemsForScreen(
  route: string,
  reader: ItemReader,
  limit = 3,
  items: readonly AcademyItem[] = ITEMS,
): AcademyItem[] {
  const picked: AcademyItem[] = [];
  let paid = 0;
  for (const item of rankItems(itemsForRoute(route, items).filter((i) => visibleInMarket(i, reader)), reader)) {
    if (picked.length >= limit) break;
    if (item.access === 'paid') {
      if (paid >= 1) continue;
      paid += 1;
    }
    picked.push(item);
  }
  return picked;
}

/** How many items the route has for this reader in all, for the "All courses" link. */
export function itemTotalForRoute(route: string, reader: ItemReader, items: readonly AcademyItem[] = ITEMS): number {
  return itemsForRoute(route, items).filter((i) => visibleInMarket(i, reader)).length;
}

/** A topic slug as a label: "boq-exchange" becomes "Boq exchange". */
export function topicLabel(topic: string): string {
  const spaced = topic.replace(/-/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function itemTopics(item: AcademyItem): string[] {
  return item.topics.map(topicLabel);
}

export function allTopics(items: readonly AcademyItem[] = ITEMS): string[] {
  return [...new Set(items.flatMap((i) => i.topics))].sort((a, b) => a.localeCompare(b));
}

export function allTracks(items: readonly AcademyItem[] = ITEMS): string[] {
  return [...new Set(items.map((i) => i.track).filter((t): t is string => Boolean(t)))].sort();
}

/** Length buckets in minutes; the data holds courses of 2.5 to 5 h and guides without a length. */
export const DURATION_BUCKETS = {
  short: { max: 180 },
  medium: { min: 180, max: 240 },
  long: { min: 240 },
} as const;
export type DurationBucket = keyof typeof DURATION_BUCKETS;
export const DURATION_KEYS = Object.keys(DURATION_BUCKETS) as DurationBucket[];

/** Country filter value for items that belong to no country. */
export const UNIVERSAL = 'none';

export type ItemSort = 'recommended' | 'shortest' | 'az';
export type FilterDimension = 'kind' | 'access' | 'country' | 'topic' | 'track' | 'duration';

export interface ItemFilters {
  kind: AcademyItemKind | 'guide' | null;
  topic: string | null;
  track: string | null;
  route: string | null;
  query: string;
  access?: 'free' | 'paid' | null;
  /** ISO market, or `UNIVERSAL` for items without one. */
  country?: string | null;
  duration?: DurationBucket | null;
  sort?: ItemSort;
}

export function durationBucket(minutes: number | undefined): DurationBucket | null {
  if (!minutes) return null;
  if (minutes <= DURATION_BUCKETS.short.max) return 'short';
  return minutes <= DURATION_BUCKETS.medium.max ? 'medium' : 'long';
}

/** The facet value of an item: what a chip of that dimension would select. */
export function facetValues(item: AcademyItem, dim: FilterDimension): string[] {
  switch (dim) {
    case 'kind':
      return [item.kind === 'article' ? 'guide' : item.kind];
    case 'access':
      return [item.access];
    case 'country':
      return [item.country ?? item.market ?? UNIVERSAL];
    case 'topic':
      return item.topics;
    case 'track':
      return item.track ? [item.track] : [];
    case 'duration': {
      const b = durationBucket(item.durationMin);
      return b ? [b] : [];
    }
  }
}

function matches(i: AcademyItem, filters: ItemFilters, skip: FilterDimension | null, q: string): boolean {
  const want: Record<FilterDimension, string | null | undefined> = {
    kind: filters.kind,
    access: filters.access,
    country: filters.country,
    topic: filters.topic,
    track: filters.track,
    duration: filters.duration,
  };
  for (const dim of Object.keys(want) as FilterDimension[]) {
    if (dim === skip || !want[dim]) continue;
    if (!facetValues(i, dim).includes(want[dim]!)) return false;
  }
  if (filters.route && !i.routes.includes(filters.route)) return false;
  return !q || fold([i.title, ...itemTopics(i), i.track ?? ''].join(' ')).includes(q);
}

/** Filtered and sorted. The default order, "recommended", puts content in the reader's language
 *  first, then the reader's own market, then catalogue order, so free and paid interleave. */
export function filterItems(
  filters: ItemFilters,
  reader: ItemReader,
  items: readonly AcademyItem[] = ITEMS,
): AcademyItem[] {
  const q = fold(filters.query.trim());
  const hits = items.filter((i) => visibleInMarket(i, reader) && matches(i, filters, null, q));
  const own = (i: AcademyItem) => (baseLanguage(i.contentLanguage) === baseLanguage(reader.language) ? 0 : 1);
  const home = (i: AcademyItem) => (reader.market && (i.country ?? i.market) === reader.market ? 0 : 1);
  const indexed = hits.map((item, index) => ({ item, index }));
  const sort = filters.sort ?? 'recommended';
  if (sort === 'az') {
    const collator = new Intl.Collator(reader.language || 'en', { sensitivity: 'base', numeric: true });
    indexed.sort((a, b) => collator.compare(a.item.title, b.item.title) || a.index - b.index);
  } else if (sort === 'shortest') {
    const len = (i: AcademyItem) => i.durationMin ?? Number.POSITIVE_INFINITY;
    indexed.sort((a, b) => len(a.item) - len(b.item) || a.index - b.index);
  } else {
    indexed.sort((a, b) => own(a.item) - own(b.item) || home(a.item) - home(b.item) || a.index - b.index);
  }
  return indexed.map((x) => x.item);
}

/** How many items each chip of one dimension would show: every other filter applies, this one does not. */
export function facetCounts(
  dim: FilterDimension,
  filters: ItemFilters,
  reader: ItemReader,
  items: readonly AcademyItem[] = ITEMS,
): Map<string, number> {
  const q = fold(filters.query.trim());
  const counts = new Map<string, number>();
  for (const i of items) {
    if (!visibleInMarket(i, reader) || !matches(i, filters, dim, q)) continue;
    for (const v of facetValues(i, dim)) counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  return counts;
}

/** Duration as "35 min" or "4.5 h" in the reader's number format. */
export function formatItemDuration(minutes: number, language: string): string {
  try {
    if (minutes < 60) {
      return new Intl.NumberFormat(language, { style: 'unit', unit: 'minute', unitDisplay: 'short' }).format(minutes);
    }
    return new Intl.NumberFormat(language, {
      style: 'unit',
      unit: 'hour',
      unitDisplay: 'short',
      maximumFractionDigits: 1,
    }).format(minutes / 60);
  } catch {
    return minutes < 60 ? `${minutes} min` : `${Math.round(minutes / 6) / 10} h`;
  }
}

/** A language's name in the reader's own language, from the browser. */
export function languageName(code: string, language: string): string {
  try {
    return new Intl.DisplayNames([language, 'en'], { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}

const PALETTE_ROWS = 3;

/** Command palette rows for a typed query: title, topics or track must match. */
export function paletteItems(
  query: string,
  reader: ItemReader,
  locale: string,
  items: readonly AcademyItem[] = ITEMS,
): AcademyItem[] {
  if (query.trim().length < 2) return [];
  const matching = items.filter(
    (i) => visibleInMarket(i, reader) && fuzzyScore(query, [i.title, ...itemTopics(i), i.track ?? ''], locale) >= 0.6,
  );
  return rankItems(matching, reader).slice(0, PALETTE_ROWS);
}
