// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One reusable browser for the whole CWICR cost-base catalog. Every base family
// - the flagship Global CWICR base (GESN / FER / TER, 30 market/language
// variants) and each authentic national base alike - is presented the same way:
// a single clickable country row that expands to reveal its importable variants,
// each with the real work-item count. China is listed first, the Global CWICR
// (GESN / FER / TER) base second, then the rest, and there is no separate
// grouping heading. The same component renders on the import page, the
// database-setup page and onboarding so the three surfaces never drift. It is
// presentational: the parent owns the load logic and passes it in via onLoad, so
// each page keeps its own progress, toasts and retry.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronDown, Download, Loader2, RotateCcw, Search } from 'lucide-react';
import { CountryFlag, CountryFlagBackdrop } from '@/shared/ui';
import type { BaseCatalog, BaseFamily, BaseVariant } from './baseCatalog';
import { canReturnHome, effectiveActiveMarkets, languageName, variantMatches } from './baseCatalog';
import { DEPTH_BANDS, baseDepthLevel } from './baseDepth';
import { getNumberLocale } from '@/stores/usePreferencesStore';

// Founder-requested family order for the base picker: China first, then the
// flagship Global CWICR base (GESN / FER / TER) second, then every other family
// in its original catalog order. Keeps the picker uniform - the GESN / FER / TER
// base is just another country row, never a special block.
const FAMILY_ORDER_PRIORITY: Record<string, number> = { china: 0, global: 1 };

// The card action buttons. These were duplicated string literals, and the two
// primaries had already drifted apart: the market one grew a shadow, an inset
// hairline, a real hover and an active nudge, while the plain load button - the
// one most people press - was left on `transition-colors hover:bg-oe-blue/90`.
// Naming them once is what stops that happening again.
// The focus ring is white rather than the usual oe-blue on the primaries: the
// inset hairline below makes every ring on this button inset too, and an
// oe-blue ring inset into an oe-blue button is invisible.
const ACTION_PRIMARY_CLASS =
  'flex w-full items-center justify-center gap-1.5 rounded-lg bg-oe-blue px-2.5 py-1.5 ' +
  'text-xs font-semibold text-white shadow-sm ring-1 ring-inset ring-white/15 ' +
  'transition-all duration-fast ease-oe ' +
  'hover:bg-oe-blue-hover hover:shadow-md active:translate-y-px active:bg-oe-blue-active ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white ' +
  'disabled:opacity-50 disabled:shadow-none';

// Secondary card action. The two callers differ only in how they read when
// disabled, so that part stays at the call site.
const ACTION_SECONDARY_CLASS =
  'w-full rounded-lg border border-border-light bg-surface-elevated px-2.5 py-1.5 ' +
  'text-xs font-medium text-content-secondary shadow-xs ' +
  'transition-all duration-fast ease-oe ' +
  'hover:border-border hover:bg-surface-secondary hover:shadow-sm active:translate-y-px ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue';

function orderFamilies(families: BaseFamily[]): BaseFamily[] {
  return families
    .map((family, index) => ({ family, index }))
    .sort(
      (a, b) =>
        (FAMILY_ORDER_PRIORITY[a.family.key] ?? 2) -
          (FAMILY_ORDER_PRIORITY[b.family.key] ?? 2) || a.index - b.index,
    )
    .map((entry) => entry.family);
}

interface BaseCatalogBrowserProps {
  /** The catalog payload from useBaseCatalog(). */
  catalog: BaseCatalog;
  /** Authoritative set of currently-loaded region ids (fresher than the API
   *  snapshot after a just-completed load). Falls back to variant.loaded. */
  loadedRegions?: Set<string>;
  /** Region id currently importing (spinner + disables the others). */
  loadingRegion?: string | null;
  /** Region id currently marked active (blue accent). */
  activeRegion?: string | null;
  /** 'load' shows a Load button per card; 'select' turns cards into a picker. */
  mode?: 'load' | 'select';
  /** Selected region id in 'select' mode. */
  selectedRegion?: string | null;
  /** Load a base (mode='load'). Parent runs load-cwicr + toasts + state. */
  onLoad?: (variant: BaseVariant) => void;
  /** Pick a base (mode='select'). */
  onSelect?: (variant: BaseVariant) => void;
  /** Make a loaded base the active one (global family's set-active-database). */
  onSetActive?: (region: string) => void;
  /** National market card selected: load the base + reprice into that market,
   *  or switch the active market when already loaded. Without it, 'load' mode
   *  hides the market cards: loading one as a plain base would install the
   *  home language instead of the card's. */
  onReprice?: (variant: BaseVariant) => void;
  /** This browser's cached market token per base_region (e.g.
   *  { ZH_CHINA: 'GB_LONDON_en' }). The server's stored state in
   *  `catalog.base_states` wins wherever it knows one; this fills in only for a
   *  base the server knows nothing about. */
  activeMarkets?: Record<string, string>;
  /** Bring a national base back from a market to its own prices, currency and
   *  language. Without it the home card offers no way back. */
  onRestoreHome?: (variant: BaseVariant) => void;
  /** Seconds elapsed on the in-flight import, for the spinner label. */
  elapsedSeconds?: number;
  className?: string;
}

// Grouping follows the number format the reader picked, which starts out as the
// one their language implies: a reader on ?lang=de gets 55.719 even when their
// browser is set to English, and a reader who chose another format gets that.
function positionsLabel(n: number): string {
  return n.toLocaleString(getNumberLocale());
}

/**
 * How thoroughly the base is worked out, as filled segments.
 *
 * The bar is decorative on its own, so the level and the count it comes from
 * are both in the title: a reader who wonders what four segments mean gets the
 * answer without leaving the row. `aria-hidden` on the segments and a plain
 * text label for assistive tech, because five divs read as nothing.
 */
function DepthMeter({ positions }: { positions: number }) {
  const { t } = useTranslation();
  const level = baseDepthLevel(positions);
  const label = t('costs.base_depth_hint', {
    defaultValue: 'Catalogue depth {{level}} of {{total}}: {{positions}} work items',
    level,
    total: DEPTH_BANDS,
    positions: positionsLabel(positions),
  });

  return (
    <div className="flex flex-col items-end gap-1" title={label}>
      <div className="flex items-center gap-[3px]" role="img" aria-label={label}>
        {Array.from({ length: DEPTH_BANDS }, (_, i) => (
          <span
            key={i}
            aria-hidden
            className={`h-3 w-[5px] rounded-[2px] transition-colors duration-normal ease-oe ${
              i < level ? 'bg-oe-blue' : 'bg-border-light'
            }`}
          />
        ))}
      </div>
      <span className="text-[10px] font-medium uppercase tracking-wide text-content-quaternary">
        {t('costs.base_depth', { defaultValue: 'Depth' })}
      </span>
    </div>
  );
}

interface CardProps {
  variant: BaseVariant;
  title: string;
  /** Small chip under the title: norm system (national) or language (global). */
  chip: string;
  loaded: boolean;
  loading: boolean;
  active: boolean;
  selected: boolean;
  disabled: boolean;
  mode: 'load' | 'select';
  onLoad?: (variant: BaseVariant) => void;
  onSelect?: (variant: BaseVariant) => void;
  onSetActive?: (region: string) => void;
  /** National market variant: load the base + reprice into this market (or,
   *  when already loaded, switch the active market). Distinct from onSetActive,
   *  which stays for the global family's set-active-database. */
  onReprice?: (variant: BaseVariant) => void;
  /** Home card of a base priced into a market: offer the way back. */
  onRestoreHome?: (variant: BaseVariant) => void;
  /** Home card of a base whose last market switch has not finished. */
  unfinishedSwitch?: boolean;
  elapsedSeconds?: number;
}

function BaseVariantCard({
  variant,
  title,
  chip,
  loaded,
  loading,
  active,
  selected,
  disabled,
  mode,
  onLoad,
  onSelect,
  onSetActive,
  onReprice,
  onRestoreHome,
  unfinishedSwitch = false,
  elapsedSeconds,
}: CardProps) {
  const { t, i18n } = useTranslation();
  const shownPositions = loaded && variant.loaded_positions > 0 ? variant.loaded_positions : variant.positions;
  // A national market card (reprice target). Only treat it as one when a
  // reprice handler is wired (the import page); on surfaces without it, market
  // variants fall back to the standard "load this base" action below.
  const isMarket = variant.market_catalog !== '' && !!onReprice;

  const border = selected
    ? 'border-oe-blue/60 bg-oe-blue-subtle/25 ring-1 ring-oe-blue/30'
    : loaded
      ? active
        ? 'border-oe-blue/40 bg-oe-blue-subtle/20'
        : 'border-semantic-success/30 bg-semantic-success-bg/40'
      : loading
        ? 'border-oe-blue/40 bg-oe-blue-subtle/30'
        : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary';

  const clickable = mode === 'select' && !disabled;

  return (
    <div
      className={`relative flex flex-col rounded-xl border p-3 transition-all duration-normal ease-oe ${border} ${
        disabled && !loading ? 'pointer-events-none opacity-40' : ''
      } ${clickable ? 'cursor-pointer' : ''}`}
      onClick={clickable ? () => onSelect?.(variant) : undefined}
      data-testid="base-variant-card"
    >
      {/* Header: flag + title + top-right status badge */}
      <div className="flex items-start gap-2.5">
        <CountryFlag code={variant.flag} size={30} className="mt-0.5 shrink-0 rounded shadow-xs border border-black/5" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-content-primary" title={title}>
            {title}
          </div>
          <div className="truncate text-xs text-content-tertiary">
            {variant.city !== 'National' ? `${variant.city} · ` : ''}
            {chip}
          </div>
        </div>
        {loaded && (
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
              active ? 'bg-oe-blue/15 text-oe-blue' : 'bg-semantic-success/15 text-semantic-success'
            }`}
          >
            {active
              ? t('costs.base_active', { defaultValue: 'Active' })
              : t('costs.base_loaded', { defaultValue: 'Loaded' })}
          </span>
        )}
        {!loaded && variant.bundled && (
          <span className="shrink-0 rounded-full bg-surface-secondary px-2 py-0.5 text-[10px] font-medium text-content-tertiary">
            {t('costs.base_included', { defaultValue: 'Included' })}
          </span>
        )}
      </div>

      {/* The card's language is a promise about the text. Where no published
          file holds the base in it (Turkiye has no English text), say which
          language the work items will really be in. */}
      {variant.text_lang_code && variant.text_lang_code !== variant.lang_code && (
        <div className="mt-1.5 text-[11px] font-medium text-semantic-warning" data-testid="base-text-lang-note">
          {t('costs.base_text_only_in', {
            defaultValue: 'Work items in {{language}} only',
            language: languageName(variant.text_lang_code, i18n.language),
          })}
        </div>
      )}

      {unfinishedSwitch && (
        <div className="mt-1.5 text-[11px] font-medium text-semantic-warning" data-testid="base-switch-unfinished">
          {t('costs.base_market_unfinished', {
            defaultValue: 'A market switch of this base has not finished',
          })}
        </div>
      )}

      {/* Count + currency + coefficient marker */}
      <div className="mt-2.5 flex items-end justify-between gap-2">
        <div>
          <div className="text-lg font-bold leading-none tabular-nums text-content-primary">
            {positionsLabel(shownPositions)}
          </div>
          <div className="text-[11px] text-content-tertiary">
            {t('costs.base_positions', { defaultValue: 'positions' })}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="rounded bg-surface-secondary px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-content-secondary">
            {variant.currency}
          </span>
          {variant.coefficient && (
            <span className="text-[10px] text-content-quaternary">
              {t('costs.base_coefficient', { defaultValue: 'coefficient base' })}
            </span>
          )}
        </div>
      </div>

      {/* Action */}
      {mode === 'load' && (
        <div className="mt-3">
          {isMarket ? (
            // National market card: not loaded -> load + price into; loaded but
            // not the active market -> switch; loaded + active -> a badge.
            loading ? (
              <div className="flex w-full items-center justify-center gap-2 rounded-lg bg-oe-blue/10 px-2.5 py-1.5 text-xs font-medium text-oe-blue">
                <Loader2 size={13} className="animate-spin" />
                {t('costs.base_loading', { defaultValue: 'Loading' })}
                {typeof elapsedSeconds === 'number' && elapsedSeconds > 0 ? ` ${elapsedSeconds}s` : ''}
              </div>
            ) : loaded && active ? (
              <div className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-oe-blue/10 px-2.5 py-1.5 text-xs font-semibold text-oe-blue">
                <Check size={13} />
                {t('costs.base_market_active', { defaultValue: 'Active market' })}
              </div>
            ) : loaded ? (
              <button
                type="button"
                disabled={disabled}
                onClick={() => onReprice?.(variant)}
                className={`${ACTION_SECONDARY_CLASS} disabled:opacity-50`}
              >
                {t('costs.base_market_switch', { defaultValue: 'Switch to {{market}}', market: variant.market })}
              </button>
            ) : (
              <button
                type="button"
                disabled={disabled}
                onClick={() => onReprice?.(variant)}
                className={ACTION_PRIMARY_CLASS}
              >
                <Download size={13} />
                {t('costs.base_market_load', { defaultValue: 'Price into {{market}}', market: variant.market })}
              </button>
            )
          ) : loaded ? (
            <button
              type="button"
              disabled={active}
              onClick={() => onSetActive?.(variant.region)}
              className={`${ACTION_SECONDARY_CLASS} disabled:cursor-default disabled:opacity-60 disabled:shadow-none disabled:hover:translate-y-0`}
            >
              {active
                ? t('costs.base_is_active', { defaultValue: 'Active database' })
                : t('costs.base_set_active', { defaultValue: 'Set as active' })}
            </button>
          ) : loading ? (
            <div className="flex w-full items-center justify-center gap-2 rounded-lg bg-oe-blue/10 px-2.5 py-1.5 text-xs font-medium text-oe-blue">
              <Loader2 size={13} className="animate-spin" />
              {t('costs.base_loading', { defaultValue: 'Loading' })}
              {typeof elapsedSeconds === 'number' && elapsedSeconds > 0 ? ` ${elapsedSeconds}s` : ''}
            </div>
          ) : (
            <button
              type="button"
              disabled={disabled}
              onClick={() => onLoad?.(variant)}
              className={ACTION_PRIMARY_CLASS}
            >
              <Download size={13} />
              {variant.bundled
                ? t('costs.base_load', { defaultValue: 'Load' })
                : t('costs.base_download', { defaultValue: 'Download' })}
            </button>
          )}
          {/* The way back from a market. Only on the home card of a base the
              server (or, where it knows nothing, this browser) has in a market. */}
          {!isMarket && loaded && onRestoreHome && (
            <button
              type="button"
              disabled={disabled || loading}
              onClick={() => onRestoreHome(variant)}
              title={t('costs.base_restore_home_hint', {
                defaultValue: 'Put this base back on its own prices, currency and language',
              })}
              className={`mt-1.5 flex items-center justify-center gap-1.5 ${ACTION_SECONDARY_CLASS} disabled:opacity-50`}
              data-testid="base-restore-home"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
              {t('costs.base_restore_home', { defaultValue: 'Return to home market' })}
            </button>
          )}
        </div>
      )}

      {mode === 'select' && selected && (
        <div className="mt-3 flex items-center justify-center gap-1.5 rounded-lg bg-oe-blue/10 px-2.5 py-1.5 text-xs font-semibold text-oe-blue">
          <Check size={13} />
          {t('costs.base_selected', { defaultValue: 'Selected' })}
        </div>
      )}
    </div>
  );
}

export function BaseCatalogBrowser({
  catalog,
  loadedRegions,
  loadingRegion = null,
  activeRegion = null,
  mode = 'load',
  selectedRegion = null,
  onLoad,
  onSelect,
  onSetActive,
  onReprice,
  activeMarkets,
  onRestoreHome,
  elapsedSeconds,
  className = '',
}: BaseCatalogBrowserProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');

  // A national market card promises a market AND a language, and only a
  // surface that runs the market load can keep that promise. In 'load' mode
  // without onReprice the card used to fall back to a plain Load button that
  // installed the home base in the home language, so it is not offered there.
  // In 'select' mode the parent owns what the pick loads.
  const offersMarkets = mode === 'select' || !!onReprice;

  // Loaded is a property of the BASE, not the card: every card of a base shares
  // its base_region, so once the base is loaded all its market cards read as
  // loaded (the active one is distinguished separately).
  const isLoaded = (v: BaseVariant) => (loadedRegions ? loadedRegions.has(v.base_region) : v.loaded);
  const anyLoading = loadingRegion !== null;

  // Which market each base is in: the server's stored state where it has one,
  // this browser's cache only where it does not. Every surface that renders the
  // browser gets the same answer, whatever it passes in.
  const markets = useMemo(() => effectiveActiveMarkets(catalog, activeMarkets), [catalog, activeMarkets]);

  // Bases that have market cards at all, so only their home card can offer a
  // way back from a market.
  const marketBases = useMemo(
    () =>
      new Set(
        catalog.families.flatMap((f) => f.variants.filter((v) => v.market_catalog !== '').map((v) => v.base_region)),
      ),
    [catalog.families],
  );

  // Whether a card is the active choice. A national market card is active when
  // its base is loaded and its market_catalog is the active market for that
  // base; a home/global card is active via the set-active-database mechanism.
  const isActive = (v: BaseVariant) =>
    v.market_catalog !== ''
      ? isLoaded(v) && (markets[v.base_region] ?? '') === v.market_catalog
      : activeRegion === v.variant_id;

  const offersReturnHome = (v: BaseVariant) =>
    v.market_catalog === '' &&
    marketBases.has(v.base_region) &&
    isLoaded(v) &&
    canReturnHome(v.base_region, catalog, activeMarkets);

  // China first, the Global CWICR (GESN / FER / TER) base second, then the rest.
  const orderedFamilies = useMemo(() => orderFamilies(catalog.families), [catalog.families]);

  // Per-family expand/collapse - every country uses the same interaction: click
  // the header to reveal its importable variants. The first family (China)
  // starts open so the pattern is immediately discoverable.
  const [openFamilies, setOpenFamilies] = useState<Set<string>>(
    () => new Set(orderedFamilies.slice(0, 1).map((f) => f.key)),
  );
  const toggleFamily = (key: string) =>
    setOpenFamilies((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const searching = query.trim() !== '';

  // Filter each family's variants by the query; drop families with no match.
  const familyRows = useMemo(
    () =>
      orderedFamilies
        .map((family) => ({
          family,
          variants: family.variants.filter(
            (v) => variantMatches(v, family, query) && (offersMarkets || v.market_catalog === ''),
          ),
        }))
        .filter((row) => row.variants.length > 0),
    [orderedFamilies, query, offersMarkets],
  );

  // Count DISTINCT loaded bases: every card of a base shares its base_region, so
  // a naive per-card count would report a loaded base as its full market count.
  const loadedTotal = new Set(
    catalog.families.flatMap((f) => f.variants.filter((v) => isLoaded(v)).map((v) => v.base_region)),
  ).size;
  // Total work-item positions across every base family (#20). Each family's
  // representative count summed, floored to thousands and shown as "120,000+".
  const totalPositions = catalog.families.reduce((acc, f) => acc + f.positions, 0);
  const positionsRounded = Math.floor(totalPositions / 1000) * 1000;
  const noResults = familyRows.length === 0;

  const renderCard = (variant: BaseVariant, title: string, chip: string) => (
    <BaseVariantCard
      key={variant.variant_id}
      variant={variant}
      title={title}
      chip={chip}
      loaded={isLoaded(variant)}
      loading={loadingRegion === variant.variant_id}
      active={isActive(variant)}
      selected={selectedRegion === variant.variant_id}
      disabled={anyLoading && loadingRegion !== variant.variant_id}
      mode={mode}
      onLoad={onLoad}
      onSelect={onSelect}
      onSetActive={onSetActive}
      onReprice={onReprice}
      onRestoreHome={onRestoreHome && offersReturnHome(variant) ? onRestoreHome : undefined}
      unfinishedSwitch={
        variant.market_catalog === '' && catalog.base_states?.[variant.base_region]?.market_state === 'switching'
      }
      elapsedSeconds={elapsedSeconds}
    />
  );

  return (
    <div className={className}>
      {/* Search + summary */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search size={15} className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-content-quaternary" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('costs.base_search_placeholder', {
              defaultValue: 'Search country, city, currency, language or norm...',
            })}
            className="w-full rounded-lg border border-transparent bg-surface-secondary/70 py-2 ps-9 pe-3 text-sm text-content-primary placeholder:text-content-quaternary focus:border-oe-blue/40 focus:bg-surface-secondary focus:outline-none"
          />
        </div>
        <span className="shrink-0 text-xs text-content-tertiary tabular-nums">
          {t('costs.base_summary', {
            defaultValue: '{{families}} base families · {{bases}} cost bases · {{loaded}} loaded',
            families: catalog.total_families,
            bases: catalog.total_bases,
            loaded: loadedTotal,
          })}
          {' · '}
          {t('costs.base_summary_positions', {
            defaultValue: '{{positions}}+ positions',
            positions: positionsRounded.toLocaleString(getNumberLocale()),
          })}
        </span>
      </div>

      {noResults && (
        <div className="py-10 text-center text-sm text-content-tertiary">
          {t('costs.base_no_results', { defaultValue: 'No cost bases match "{{q}}"', q: query })}
        </div>
      )}

      {/* Uniform country picker: every base family - the Global CWICR base
          (GESN / FER / TER) included - is one clickable country row. Click a
          row to reveal that country's importable market/language variants. No
          family is a special block and there is no separate grouping heading;
          China is first, the Global CWICR (GESN / FER / TER) base second, then
          the rest. */}
      <div className="space-y-3">
        {familyRows.map(({ family, variants }) => {
          // Every family badges with its own origin flag; the Russia base
          // (GESN / FER / TER norm lineage) carries the Russian flag from its
          // backend origin_flag.
          const flagCode = family.origin_flag;
          const loadedInFamily = new Set(
            variants.filter((v) => isLoaded(v)).map((v) => v.base_region),
          ).size;
          const multiMarket = family.market_count > 1;
          // Which card of this family is the current choice, if any. Shown as a
          // chip in the header so the state survives collapsing.
          const activeVariant = variants.find((v) => isActive(v));
          // A codeless base: it prices through a resource sheet rather than by
          // resource code. A real difference between families, so it is said in
          // the header rather than folded into the depth meter.
          const coefficient = variants.some((v) => v.coefficient);
          // When a family stays open regardless of the toggle.
          //
          // `isActive` used to be one of these, and it made the row that mattered
          // most the one row that could not be closed: once a base was loaded and
          // a market active, every click on the header was overridden on the next
          // render and the chevron just twitched. The active market is now a chip
          // in the header instead, which is what the force-open was really for.
          // `selectedRegion` is kept only in 'select' mode, where the catalog is a
          // picker and hiding the user's own selection would be the same mistake.
          const open =
            searching ||
            openFamilies.has(family.key) ||
            variants.some((v) => v.variant_id === loadingRegion) ||
            (mode === 'select' && variants.some((v) => v.variant_id === selectedRegion));
          return (
            <section key={family.key}>
              <button
                type="button"
                aria-expanded={open}
                onClick={() => toggleFamily(family.key)}
                className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left shadow-xs transition-all duration-normal ease-oe hover:shadow-sm ${
                  open
                    ? 'border-border bg-surface-elevated'
                    : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary'
                }`}
              >
                <CountryFlag
                  code={flagCode}
                  size={38}
                  className="shrink-0 rounded-md shadow-xs border border-black/5"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-content-primary">{family.name}</span>
                    <span className="rounded bg-surface-secondary px-1.5 py-0.5 text-[10px] font-medium text-content-secondary">
                      {family.norm_system}
                    </span>
                    {multiMarket && (
                      <span className="rounded bg-oe-blue/10 px-1.5 py-0.5 text-[10px] font-medium text-oe-blue">
                        {t('costs.base_family_markets', {
                          defaultValue: '{{count}} markets',
                          count: family.market_count,
                        })}
                      </span>
                    )}
                    {coefficient && (
                      <span
                        className="rounded bg-surface-secondary px-1.5 py-0.5 text-[10px] font-medium text-content-tertiary"
                        title={t('costs.base_coefficient_hint', {
                          defaultValue: 'Priced through a resource price sheet rather than by resource code',
                        })}
                      >
                        {t('costs.base_coefficient', { defaultValue: 'coefficient base' })}
                      </span>
                    )}
                    {loadedInFamily > 0 && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-semantic-success/15 px-1.5 py-0.5 text-[10px] font-semibold text-semantic-success">
                        <Check size={10} />
                        {t('costs.base_family_loaded_count', {
                          defaultValue: '{{count}} loaded',
                          count: loadedInFamily,
                        })}
                      </span>
                    )}
                    {activeVariant && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-oe-blue/15 px-1.5 py-0.5 text-[10px] font-semibold text-oe-blue">
                        <Check size={10} />
                        {t('costs.base_family_active', {
                          defaultValue: 'Active: {{market}}',
                          market: activeVariant.market,
                        })}
                      </span>
                    )}
                  </div>
                  <div className="truncate text-xs text-content-tertiary">{family.description}</div>
                </div>
                <div className="hidden shrink-0 text-right sm:block">
                  <div className="text-sm font-bold tabular-nums text-content-primary">
                    {positionsLabel(family.positions)}
                  </div>
                  <div className="text-[11px] text-content-tertiary">
                    {t('costs.base_positions', { defaultValue: 'positions' })}
                  </div>
                </div>
                <div className="hidden shrink-0 sm:block">
                  <DepthMeter positions={family.positions} />
                </div>
                <ChevronDown
                  size={18}
                  className={`shrink-0 text-content-tertiary transition-transform duration-normal ease-oe ${
                    open ? '' : '-rotate-90'
                  }`}
                />
              </button>
              {open && (
                // The country wash sits behind the cards so an expanded family
                // reads as one country's shelf rather than as a loose grid.
                //
                // `relative` here is deliberate and safe: nothing inside this
                // block opens an overlay - the cards only call handlers the page
                // owns, and the page renders its modals outside this component -
                // so the per-family positioning context cannot trap a fixed z-50
                // dialog the way a page-level `isolate` would
                // (modal_relative_isolate_trap). The grid takes `relative` of its
                // own so it paints above the absolutely-positioned backdrop.
                <div className="relative mt-2.5 overflow-hidden rounded-xl border border-border-light/70 bg-surface-secondary/30 p-2.5">
                  <CountryFlagBackdrop code={flagCode} variant="panel" />
                  <div className="relative grid grid-cols-1 gap-2.5 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                    {variants.map((v) => renderCard(v, v.market, v.language))}
                  </div>
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
