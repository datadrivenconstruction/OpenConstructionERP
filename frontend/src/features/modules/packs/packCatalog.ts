// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The pure half of the packs catalogue: what a pack is on the wire, the facts
 * the page filters and groups on, and the filter state that lives in the URL.
 *
 * Nothing here renders or fetches. The page computes one `PackEntry` per pack
 * once per data change, and every keystroke after that only walks those
 * entries, so a catalogue of a few hundred packs filters without re-deriving
 * country names or collating strings on each pass.
 */

import type { PackType } from '@/shared/hooks/usePartnerPack';
import {
  packCountryCode,
  packMarketBand,
  PACK_MARKET_BANDS,
  type PackMarketBand,
} from '@/shared/lib/regionalPack';

/* ── Wire types ─────────────────────────────────────────────────────────── */

export interface PackBranding {
  primary_color: string;
  accent_color: string | null;
  has_logo: boolean;
  has_favicon: boolean;
  powered_by_text: string;
}

/** One pack as ``GET /v1/partner-pack/installed`` returns it. */
export interface PackManifest {
  slug: string;
  /** Pack type under the Packs umbrella. Older backends omit it; the page
   *  falls back to ``partner`` (the historical type). */
  type?: PackType;
  partner_name: string;
  partner_url: string | null;
  pack_version: string;
  description: string;
  default_locale: string;
  additional_locales: string[];
  cwicr_regions: string[];
  default_currency: string;
  default_tax_template: string | null;
  default_methodology?: string | null;
  validation_rule_packs: string[];
  validation_rule_sets?: string[];
  demo_template_ids?: string[];
  default_modules: string[];
  hidden_modules: string[];
  branding: PackBranding;
  has_onboarding_script: boolean;
  metadata: Record<string, unknown>;
}

export interface PartnerPacksResponse {
  active_slug: string | null;
  installed: PackManifest[];
}

/** Pack type with a safe fallback to ``partner`` for manifests that predate it. */
export function packTypeOf(pack: Pick<PackManifest, 'type'>): PackType {
  return pack.type ?? 'partner';
}

export function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === 'string');
}

/* ── Standards ──────────────────────────────────────────────────────────── */

/**
 * Short names of the classification and exchange standards a pack can carry,
 * keyed by the ids manifests use in ``validation_rule_sets`` and
 * ``metadata.classification_standard``. These are the standards' own names and
 * are not translated. An id missing here is a rule set that is not a standard
 * (``project_governance``, ``permits``) and stays off the card.
 */
export const STANDARD_LABELS: Readonly<Record<string, string>> = {
  din276: 'DIN 276',
  gaeb: 'GAEB',
  nrm: 'NRM',
  masterformat: 'MasterFormat',
  uniformat: 'UniFormat',
  onorm: 'ÖNORM',
  sinapi: 'SINAPI',
  nbr: 'NBR',
  gbt50500: 'GB/T 50500',
  dpgf: 'DPGF',
  untec: 'UNTEC',
  cpwd: 'CPWD',
  sekisan: 'Sekisan',
  gesn: 'GESN',
  bc3: 'FIEBDC BC3',
  birimfiyat: 'Birim Fiyat',
  sfb_ccs: 'SfB / CCS',
  tetelrend: 'Tételrend',
  voci: 'Voci',
  kbim: 'KBIM',
  nlsfb: 'NL-SfB',
  ns3451: 'NS 3451',
  knr: 'KNR',
  bsab: 'BSAB',
  bkp: 'BKP',
};

/** The recognised standards of a pack, classification first, without repeats. */
export function packStandards(pack: Pick<PackManifest, 'metadata' | 'validation_rule_sets'>): string[] {
  const ids: string[] = [];
  const cls = pack.metadata?.classification_standard;
  if (typeof cls === 'string') ids.push(cls.toLowerCase());
  for (const id of pack.validation_rule_sets ?? []) ids.push(id.toLowerCase());
  const out: string[] = [];
  for (const id of ids) {
    const label = STANDARD_LABELS[id];
    if (label && !out.includes(label)) out.push(label);
  }
  return out;
}

/** Base language codes a pack ships, default first, without repeats. */
export function packLanguages(pack: Pick<PackManifest, 'default_locale' | 'additional_locales'>): string[] {
  const out: string[] = [];
  for (const tag of [pack.default_locale, ...(pack.additional_locales ?? [])]) {
    const base = (tag ?? '').split(/[-_]/)[0]?.trim().toLowerCase();
    if (base && !out.includes(base)) out.push(base);
  }
  return out;
}

/* ── Filter state (URL) ─────────────────────────────────────────────────── */

export const PACK_TYPES = ['country', 'industry', 'partner', 'showcase'] as const satisfies readonly PackType[];

/** The market bands a reader can filter on: every band except `home`, which
 *  depends on the browser's guess and so is a sort hint, not a place. */
export const PACK_REGIONS = PACK_MARKET_BANDS.filter(
  (b): b is Exclude<PackMarketBand, 'home'> => b !== 'home',
);
export type PackRegion = Exclude<PackMarketBand, 'home'>;

export const PACK_STATUSES = ['active', 'available'] as const;
export type PackStatus = (typeof PACK_STATUSES)[number];

export const PACK_SORTS = ['recommended', 'name', 'region'] as const;
export type PackSort = (typeof PACK_SORTS)[number];

export interface PackFilters {
  q: string;
  types: PackType[];
  /** The company-type chip. Company types are presets, not installed packs,
   *  so they sit beside ``types`` rather than in it. */
  company: boolean;
  region: PackRegion | null;
  lang: string | null;
  status: PackStatus | null;
  sort: PackSort;
}

export const EMPTY_PACK_FILTERS: PackFilters = {
  q: '',
  types: [],
  company: false,
  region: null,
  lang: null,
  status: null,
  sort: 'recommended',
};

/** The value the company-type chip writes into the ``type`` query key. */
export const COMPANY_PACK_TYPE = 'company';

/** Query keys this catalogue owns. Anything else in the URL (``tab`` on the
 *  Modules page) is left alone. */
export const PACK_FILTER_PARAMS = ['q', 'type', 'region', 'lang', 'status', 'sort'] as const;

function oneOf<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

/** Read the filters from a query string. Unknown values are dropped rather
 *  than trusted, so a hand-edited or stale link degrades to "no filter". */
export function parsePackFilters(params: URLSearchParams): PackFilters {
  const raw = (params.get('type') ?? '').split(',').map((s) => s.trim());
  const types = raw.filter((s): s is PackType => (PACK_TYPES as readonly string[]).includes(s));
  const lang = (params.get('lang') ?? '').trim().toLowerCase();
  return {
    q: params.get('q') ?? '',
    types: PACK_TYPES.filter((t) => types.includes(t)),
    company: raw.includes(COMPANY_PACK_TYPE),
    region: oneOf(params.get('region'), PACK_REGIONS),
    lang: /^[a-z]{2,3}$/.test(lang) ? lang : null,
    status: oneOf(params.get('status'), PACK_STATUSES),
    sort: oneOf(params.get('sort'), PACK_SORTS) ?? 'recommended',
  };
}

/** A copy of ``params`` carrying ``filters``; defaults are omitted so the
 *  plain page keeps a plain URL. */
export function writePackFilters(params: URLSearchParams, filters: PackFilters): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of PACK_FILTER_PARAMS) next.delete(key);
  if (filters.q) next.set('q', filters.q);
  const types: string[] = PACK_TYPES.filter((t) => filters.types.includes(t));
  if (filters.company) types.push(COMPANY_PACK_TYPE);
  if (types.length) next.set('type', types.join(','));
  if (filters.region) next.set('region', filters.region);
  if (filters.lang) next.set('lang', filters.lang);
  if (filters.status) next.set('status', filters.status);
  if (filters.sort !== 'recommended') next.set('sort', filters.sort);
  return next;
}

/** Whether anything narrows the list. Sort reorders and does not count. */
export function hasActivePackFilters(filters: PackFilters): boolean {
  return Boolean(
    filters.q.trim() || filters.types.length || filters.company || filters.region || filters.lang || filters.status,
  );
}

/* ── Entries ────────────────────────────────────────────────────────────── */

/** Everything the page filters, groups and draws, worked out once per pack. */
export interface PackEntry {
  pack: PackManifest;
  slug: string;
  /** The name the card renders (translated when a locale has it). */
  name: string;
  type: PackType;
  /** Lower-case ISO 3166-1 alpha-2, or null for a pack with no single market. */
  country: string | null;
  countryName: string | null;
  region: PackRegion;
  /** The band including `home`, for the recommended order. */
  band: PackMarketBand;
  languages: string[];
  standards: string[];
  /** Modules the pack switches on; null means it leaves every module on. */
  moduleCount: number | null;
  demoCount: number;
  /** Lower-cased, accent-folded text the search runs over. */
  haystack: string;
}

export interface PackEntryOptions {
  nameOf: (pack: PackManifest) => string;
  summaryOf?: (pack: PackManifest) => string;
  countryNameOf?: (iso: string) => string | null;
  languageNameOf?: (code: string) => string | null;
  homeCountry?: string | null;
}

/** Lower case with accents folded, so "Osterreich" finds "Österreich". */
export function foldText(text: string): string {
  return text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
}

export function buildPackEntries(packs: readonly PackManifest[], options: PackEntryOptions): PackEntry[] {
  const { nameOf, summaryOf, countryNameOf, languageNameOf, homeCountry = null } = options;
  return packs.map((pack) => {
    const code = packCountryCode(pack);
    const country = code && code !== 'xx' ? code : null;
    const countryName = country ? countryNameOf?.(country) ?? null : null;
    const band = packMarketBand(pack, homeCountry);
    const region = packMarketBand(pack, null) as PackRegion;
    const languages = packLanguages(pack);
    const standards = packStandards(pack);
    const name = nameOf(pack);
    const parts = [
      name,
      pack.partner_name,
      pack.slug,
      country ?? '',
      countryName ?? '',
      typeof pack.metadata?.country_name_en === 'string' ? pack.metadata.country_name_en : '',
      pack.default_currency,
      ...languages,
      ...languages.map((l) => languageNameOf?.(l) ?? ''),
      ...standards,
      ...asStringArray(pack.metadata?.regulator_refs),
      ...pack.validation_rule_packs,
      summaryOf?.(pack) ?? pack.description,
    ];
    return {
      pack,
      slug: pack.slug,
      name,
      type: packTypeOf(pack),
      country,
      countryName,
      region,
      band,
      languages,
      standards,
      moduleCount: pack.default_modules.length > 0 ? pack.default_modules.length : null,
      demoCount: pack.demo_template_ids?.length ?? 0,
      haystack: foldText(parts.filter(Boolean).join(' \u0001 ')),
    };
  });
}

/* ── Filtering ──────────────────────────────────────────────────────────── */

type Facet = 'type' | 'region' | 'lang' | 'status';

function matches(entry: PackEntry, filters: PackFilters, activeSlug: string | null, skip?: Facet): boolean {
  // Only the company chip chosen means no installed pack is wanted.
  if (skip !== 'type' && (filters.types.length || filters.company) && !filters.types.includes(entry.type)) return false;
  if (skip !== 'region' && filters.region && entry.region !== filters.region) return false;
  if (skip !== 'lang' && filters.lang && !entry.languages.includes(filters.lang)) return false;
  if (skip !== 'status' && filters.status) {
    const isActive = entry.slug === activeSlug;
    if (filters.status === 'active' ? !isActive : isActive) return false;
  }
  const q = foldText(filters.q.trim());
  if (q) {
    for (const token of q.split(/\s+/)) if (!entry.haystack.includes(token)) return false;
  }
  return true;
}

export function filterPackEntries(
  entries: readonly PackEntry[],
  filters: PackFilters,
  activeSlug: string | null,
): PackEntry[] {
  return entries.filter((e) => matches(e, filters, activeSlug));
}

export interface PackFacetCounts {
  types: Record<PackType, number>;
  regions: Record<PackRegion, number>;
  langs: Map<string, number>;
  status: Record<PackStatus, number>;
}

/**
 * How many packs each filter value would show, given every OTHER filter.
 *
 * Counting a facet against itself would make every unchosen chip read 0 the
 * moment one is chosen, which tells the reader nothing about what switching
 * would find.
 */
export function packFacetCounts(
  entries: readonly PackEntry[],
  filters: PackFilters,
  activeSlug: string | null,
): PackFacetCounts {
  const types = { country: 0, industry: 0, partner: 0, showcase: 0 } as Record<PackType, number>;
  const regions = Object.fromEntries(PACK_REGIONS.map((r) => [r, 0])) as Record<PackRegion, number>;
  const langs = new Map<string, number>();
  const status: Record<PackStatus, number> = { active: 0, available: 0 };
  for (const e of entries) {
    if (matches(e, filters, activeSlug, 'type')) types[e.type] += 1;
    if (matches(e, filters, activeSlug, 'region')) regions[e.region] += 1;
    if (matches(e, filters, activeSlug, 'lang')) for (const l of e.languages) langs.set(l, (langs.get(l) ?? 0) + 1);
    if (matches(e, filters, activeSlug, 'status')) status[e.slug === activeSlug ? 'active' : 'available'] += 1;
  }
  return { types, regions, langs, status };
}

/** A company type as the catalogue filters it: its preset key and the folded
 *  text the search runs on. */
export interface CompanyPackEntry {
  key: string;
  haystack: string;
}

/**
 * Whether a company type passes the filters. It has no market and no language
 * of its own, so a region or language filter leaves it out; ``skip`` works as
 * in the pack facet counts.
 */
export function companyPackMatches(
  entry: CompanyPackEntry,
  filters: PackFilters,
  activeKey: string | null,
  skip?: Facet,
): boolean {
  if (skip !== 'type' && filters.types.length && !filters.company) return false;
  if ((skip !== 'region' && filters.region) || (skip !== 'lang' && filters.lang)) return false;
  if (skip !== 'status' && filters.status) {
    const isActive = entry.key === activeKey;
    if (filters.status === 'active' ? !isActive : isActive) return false;
  }
  const q = foldText(filters.q.trim());
  if (q) {
    for (const token of q.split(/\s+/)) if (!entry.haystack.includes(token)) return false;
  }
  return true;
}

/* ── Grouping ───────────────────────────────────────────────────────────── */

export interface PackGroup {
  /** A band, or `all` for the flat A-Z list. Also the section's anchor id. */
  id: PackMarketBand | 'all';
  entries: PackEntry[];
}

/**
 * The sections the page draws, in order, with empty ones dropped.
 *
 * `recommended` is the reader's own market first, then the bands by market
 * size; `region` is the same bands without the guess, each sorted by country;
 * `name` is one flat A-Z list, because a heading per letter over forty cards
 * is navigation nobody asked for.
 */
export function groupPackEntries(entries: readonly PackEntry[], sort: PackSort, locale?: string): PackGroup[] {
  const collator = new Intl.Collator(locale, { sensitivity: 'base', numeric: true });
  const byName = (a: PackEntry, b: PackEntry) => collator.compare(a.name, b.name);
  if (sort === 'name') {
    return entries.length ? [{ id: 'all', entries: [...entries].sort(byName) }] : [];
  }
  if (sort === 'region') {
    const byCountry = (a: PackEntry, b: PackEntry) =>
      collator.compare(a.countryName ?? '￿', b.countryName ?? '￿') || byName(a, b);
    return PACK_REGIONS.map((id) => ({
      id,
      entries: entries.filter((e) => e.region === id).sort(byCountry),
    })).filter((g) => g.entries.length > 0);
  }
  return PACK_MARKET_BANDS.map((id) => ({
    id,
    entries: entries.filter((e) => e.band === id).sort(byName),
  })).filter((g) => g.entries.length > 0);
}

/** Anchor id of a section on the page. */
export function packSectionId(id: PackGroup['id']): string {
  return `packs-section-${id}`;
}
