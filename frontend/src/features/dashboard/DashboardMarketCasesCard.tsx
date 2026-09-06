// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DashboardMarketCasesCard - the cases written for the reader's own market,
 * with every other market one click away.
 *
 * The dashboard already carried two things about markets and cases and never
 * joined them. `RegionalPackCard` says which market the product is set up
 * for; `DashboardCasesCard` previews the library ranked by role and progress,
 * market-blind. A German estimator saw seventeen tiles of which none was
 * necessarily German, while thirteen German cases sat in the catalogue behind
 * a market row they had to know to look for. This card is the join: the
 * cases for the market the reader works in, named as such, first.
 *
 * WHICH MARKET. Resolved by `resolveHomeMarket` (features/cases/marketCases):
 * the applied regional pack's country when it has cases, else the country the
 * UI language declares, else the nearest market for that language, each read
 * through the same helpers the catalogue orders itself by. The subtitle says
 * which of the three answered, because "your market" is only an honest title
 * for the first two; for the third the card says "closest to your language"
 * and means it. A language that reaches nothing (Japanese, Turkish, ...) gets
 * the shelf ordered by size with the largest market open, under a title that
 * claims nothing about the reader.
 *
 * THE SHELF. Every market with cases, the home market first and the rest by
 * count, as chips that switch the list IN PLACE. This is what makes the card a
 * map of the whole catalogue rather than a window on one corner of it:
 * fifteen markets, each one press away. The pick is view state on purpose. It
 * is not written to the hub's persisted market filter (`oe_cases_region`),
 * because browsing here must not silently narrow the catalogue the reader
 * opens next. Only the explicit "All cases for ..." link hands the market
 * over, and its label names the market it hands over.
 *
 * THE PACK. A case for a market whose pack is on disk and switched off says
 * which pack it needs, in the words the catalogue's own card strip uses
 * (`cases.regional_pack_needed`), so a reader meets one sentence in both
 * places. A market with no pack in this build says nothing here; the
 * catalogue's market panel is where that absence is explained, once, rather
 * than six times over in a grid.
 *
 * LOADING. The card waits for the pack answer before drawing anything and lets
 * the grid show its skeleton meanwhile (its id is deliberately NOT in
 * `WIDGET_NULL_FALLBACK`). Drawing the language's market first and flipping to
 * the pack's a moment later would be a card that changes its mind in front of
 * exactly the readers who did the most to tell the product where they work.
 *
 * SIZE. Like `DashboardCasesCard`, the grid inside is shaped FROM the width
 * preference Customize keeps for this widget, because the dashboard grid's
 * breakpoints are viewport-wide: a third-width card asking for three columns
 * would draw three slivers on a wide screen. Fewer cases in a narrower card,
 * never more.
 */

import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ArrowRight, Check, Package } from 'lucide-react';

import { PLAYBOOKS } from '@/features/cases/playbooks';
import type { Playbook } from '@/features/cases/types';
import { buildCaseNumbers } from '@/features/cases/stages';
import { regionDisplayName } from '@/features/cases/regions';
import {
  casesForMarket,
  countCasesByMarket,
  orderMarkets,
  resolveHomeMarket,
} from '@/features/cases/marketCases';
import { useMarketPackOffers } from '@/features/cases/CasePackStrip';
import { useCasesStore } from '@/features/cases/useCasesStore';
import { tintFor } from '@/features/cases/categories';
import { iconFor } from '@/features/cases/icons';
import { CaseArt } from '@/features/cases/CaseArt';
import { CountryFlag, CountryFlagBackdrop } from '@/shared/ui';
import { usePartnerPack } from '@/shared/hooks/usePartnerPack';
import { packCountryCode } from '@/shared/lib/regionalPack';
import { useDashboardLayoutStore } from '@/stores/useDashboardLayoutStore';
import { DASHBOARD_WIDGET_BY_ID } from './widgetRegistry';

/** This card's id in the dashboard widget registry. */
export const MARKET_CASES_WIDGET_ID = 'cases_market';

/** The four widths the dashboard grid can draw; see `DASH_SPAN_CLASS`. */
const SPAN_STEPS = [2, 3, 4, 6] as const;
type SpanStep = (typeof SPAN_STEPS)[number];

interface GridShape {
  /** Cases drawn before the "all cases for this market" link takes over. */
  limit: number;
  /** Complete literal Tailwind column classes, never concatenated (the JIT
   *  keeps only classes it can see whole). */
  columns: string;
}

/**
 * How many cases, how many across, at each width. The card tiles are
 * horizontal (art beside text) and read down to about 260px wide, which is
 * three across at full and two-thirds width on a wide screen, two at half
 * width, one at a third. Below the `lg` breakpoint every widget is full width
 * whatever its span, so the narrow shapes still allow two across on a tablet.
 */
const SHAPE_BY_SPAN: Record<SpanStep, GridShape> = {
  6: { limit: 6, columns: 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-3' },
  4: { limit: 6, columns: 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-3' },
  3: { limit: 4, columns: 'grid-cols-1 sm:grid-cols-2' },
  2: { limit: 3, columns: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-1' },
};

function normaliseSpan(value: number | undefined): SpanStep {
  return SPAN_STEPS.includes(value as SpanStep) ? (value as SpanStep) : 4;
}

/** The catalogue's own positions, computed once: the order inside a market is
 *  the order the hub shows when it leads with that market. */
const CASE_NUMBERS = buildCaseNumbers(PLAYBOOKS);
const positionOf = (pb: Playbook) => CASE_NUMBERS.get(pb.id) ?? 0;

export function DashboardMarketCasesCard() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const setRegion = useCasesStore((s) => s.setRegion);
  const { data: packData, isLoading: packLoading } = usePartnerPack();

  const savedSpan = useDashboardLayoutStore((s) => s.spans[MARKET_CASES_WIDGET_ID]);
  const shape =
    SHAPE_BY_SPAN[
      normaliseSpan(savedSpan ?? DASHBOARD_WIDGET_BY_ID[MARKET_CASES_WIDGET_ID]?.defaultSpan)
    ];

  const counts = useMemo(() => countCasesByMarket(PLAYBOOKS), []);
  const markets = useMemo(() => [...counts.keys()].sort(), [counts]);

  // `packCountryCode` reports `xx` for a cross-region pack as the pack said
  // it; the resolver treats that as no market, so it is passed through as is.
  const packCountry =
    packData?.active && packData.manifest ? packCountryCode(packData.manifest) : null;
  const resolution = useMemo(
    () => resolveHomeMarket({ language: i18n.language, packCountry, markets }),
    [i18n.language, packCountry, markets],
  );
  const shelf = useMemo(() => orderMarkets(counts, resolution.market), [counts, resolution.market]);

  // The chip the reader pressed, remembered together with the home market it
  // was pressed against. A language or pack change moves the home market and
  // the pick lapses with it, so the card re-leads with the new home rather
  // than staying on a market chosen under the old one.
  const [pick, setPick] = useState<{ home: string | null; market: string } | null>(null);
  const selected =
    pick && pick.home === resolution.market
      ? pick.market
      : (resolution.market ?? shelf[0]?.market ?? null);

  const offers = useMarketPackOffers(markets);
  const cases = useMemo(() => casesForMarket(PLAYBOOKS, selected, positionOf), [selected]);
  const shown = cases.slice(0, shape.limit);

  // The one hand-over to the hub: its persisted market filter is set to what
  // the reader is looking at, then the hub opens narrowed to it.
  const openCatalogue = useCallback(
    (market: string) => {
      setRegion(market);
      navigate('/cases');
    },
    [navigate, setRegion],
  );

  // Skeleton, not an empty card, while the pack answer is in flight: the id
  // is kept out of WIDGET_NULL_FALLBACK for exactly this.
  if (packLoading) return null;

  // No case names a market: a designed state for a catalogue of universal
  // cases, and the card says where the library is rather than vanishing.
  if (!selected || markets.length === 0) {
    return (
      <div
        data-testid="dashboard-market-cases-card"
        data-state="empty"
        className="h-full rounded-xl border border-border-light bg-surface-primary p-5"
      >
        <h3 className="text-sm font-semibold text-content-primary">
          {t('dashboard.market_cases.title_generic', { defaultValue: 'Cases by market' })}
        </h3>
        <p className="mt-1 text-xs leading-relaxed text-content-tertiary">
          {t('dashboard.market_cases.empty', {
            defaultValue: 'No case names a market yet. The whole library is one click away.',
          })}
        </p>
        <button
          type="button"
          onClick={() => navigate('/cases')}
          className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-oe-blue transition-colors hover:text-oe-blue-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
        >
          {t('cases.dashboard_card.cta_all', {
            defaultValue: 'Browse all {{count}} cases',
            count: PLAYBOOKS.length,
          })}
          <ArrowRight size={13} aria-hidden="true" />
        </button>
      </div>
    );
  }

  const marketName = regionDisplayName(selected, i18n.language);
  const selectedCount = counts.get(selected) ?? 0;
  const offer = offers.get(selected);

  // The title claims "your market" only when the pack or the language earned
  // it; the subtitle says which. A nearest-market answer and a no-answer both
  // get the neutral title, and the nearest one says what it is.
  const title =
    resolution.source === 'pack' || resolution.source === 'language'
      ? t('dashboard.market_cases.title', { defaultValue: 'Cases for your market' })
      : t('dashboard.market_cases.title_generic', { defaultValue: 'Cases by market' });
  const sourceLine =
    resolution.source === 'pack'
      ? t('dashboard.market_cases.source_pack', { defaultValue: 'Matched to your regional pack' })
      : resolution.source === 'language'
        ? t('dashboard.market_cases.source_language', {
            defaultValue: 'Matched to the language you use',
          })
        : resolution.source === 'nearest'
          ? t('dashboard.market_cases.source_nearest', {
              defaultValue: 'The closest market to your language',
            })
          : t('cases.region_selector.subtitle', {
              defaultValue: "Cases written for one country's standards, forms and payment law.",
            });
  // Whether the subtitle still describes the market on screen: once the
  // reader presses another chip, "matched to your language" would be a
  // sentence about a market they are no longer looking at.
  const onHomeMarket = selected === resolution.market;

  return (
    <div
      data-testid="dashboard-market-cases-card"
      data-market={selected}
      data-source={onHomeMarket ? (resolution.source ?? 'none') : 'pick'}
      className="relative h-full overflow-hidden rounded-xl border border-border-light bg-surface-primary p-4 shadow-xs animate-card-in"
      style={{ animationDelay: '140ms' }}
    >
      {/* The founder's own visual language for "this surface is scoped to a
          country", as on the catalogue's market row and /costs. This block
          owns the `relative`, the backdrop is its FIRST child, and there is no
          `isolate` here, so fixed modals still win. */}
      <CountryFlagBackdrop code={selected} variant="panel" />

      <div className="relative flex h-full flex-col gap-3">
        {/* ── Market hero: which market, and why this one ─────────────── */}
        <div className="flex flex-wrap items-start gap-3">
          <CountryFlag
            code={selected.toLowerCase()}
            size={44}
            className="mt-0.5 shrink-0 shadow-sm ring-1 ring-inset ring-black/10"
          />
          <div className="min-w-0 flex-1">
            <p className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              {title}
            </p>
            <h3 className="truncate text-base font-semibold tracking-tight text-content-primary">
              {marketName}
            </h3>
            <p className="mt-0.5 text-xs text-content-secondary">
              {onHomeMarket ? sourceLine : t('cases.region_hero.body', {
                defaultValue:
                  "These cases follow this market's own standards, forms and payment rules, so the numbers and the paperwork match what a client there expects.",
              })}
            </p>
          </div>
          {/* The hand-over to the hub, named for the market it hands over. */}
          <button
            type="button"
            onClick={() => openCatalogue(selected)}
            className="group inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-semibold text-content-secondary shadow-xs transition-colors hover:border-oe-blue/40 hover:text-oe-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          >
            {t('dashboard.market_cases.all_for_market', {
              defaultValue: 'All cases for {{market}} ({{count}})',
              market: marketName,
              count: selectedCount,
            })}
            <ArrowRight
              size={13}
              className="transition-transform group-hover:translate-x-0.5"
              aria-hidden="true"
            />
          </button>
        </div>

        {/* ── The cases ────────────────────────────────────────────────── */}
        <div className={clsx('grid gap-2', shape.columns)}>
          {shown.map((pb) => {
            const Icon = iconFor(pb.icon);
            const tint = tintFor(pb.category);
            const caseTitle = t(pb.titleKey, { defaultValue: pb.titleDefault });
            const caseDesc = t(pb.descKey, { defaultValue: pb.descDefault });
            return (
              <button
                key={pb.id}
                type="button"
                data-testid="market-case"
                data-case-id={pb.id}
                data-region={pb.region}
                onClick={() => navigate(`/cases/${pb.id}`)}
                title={caseTitle}
                className="group relative isolate flex overflow-hidden rounded-lg border border-border-light bg-surface-primary text-start shadow-xs transition duration-200 hover:-translate-y-0.5 hover:border-oe-blue/40 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
              >
                {/* Faint discipline wash behind the whole tile, as on the
                    gallery card above this one. */}
                <span
                  aria-hidden="true"
                  className={clsx('pointer-events-none absolute inset-0 -z-10', tint.softBg)}
                />
                {/* The case's line-art scene, on an always-light panel so the
                    linework reads the same in both themes. */}
                <div className="relative w-24 shrink-0 self-stretch overflow-hidden border-e border-border-light bg-white ring-1 ring-inset ring-slate-900/[0.04] sm:w-28">
                  <CaseArt
                    id={pb.id}
                    category={pb.category}
                    fallbackIcon={Icon}
                    fallbackClass={tint.text}
                    alt=""
                  />
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-1 px-3 py-2.5">
                  <span className="line-clamp-2 text-sm font-semibold leading-snug text-content-primary">
                    {caseTitle}
                  </span>
                  <span className="line-clamp-2 text-xs leading-relaxed text-content-secondary">
                    {caseDesc}
                  </span>
                  <span className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-2xs text-content-tertiary">
                    {/* The market chip: says at rest that this case is written
                        for one market's standards. */}
                    <span className="inline-flex items-center gap-1 font-medium text-content-secondary">
                      <CountryFlag code={selected.toLowerCase()} size={14} />
                      {marketName}
                    </span>
                    <span className="tabular-nums">
                      {t('cases.card.steps', { defaultValue: '{{count}} steps', count: pb.steps.length })}
                    </span>
                    {/* What the case needs installed, in the catalogue's own
                        words. A pack that is the applied one is a tick and its
                        name; a market with no pack on disk says nothing. */}
                    {offer && !offer.applied && (
                      <span
                        data-testid="market-case-pack"
                        data-pack-state="install"
                        title={t('cases.regional_pack_setup_hint', {
                          defaultValue:
                            'This case follows the standards of its market. Opens the pack that carries them, where you can switch it on.',
                        })}
                        className="inline-flex items-center gap-1 rounded-full bg-oe-blue/10 px-1.5 py-0.5 font-medium text-oe-blue-text ring-1 ring-inset ring-oe-blue/20"
                      >
                        <Package size={11} aria-hidden="true" />
                        {t('cases.regional_pack_needed', {
                          defaultValue: 'Needs {{name}}',
                          name: offer.name,
                        })}
                      </span>
                    )}
                    {offer?.applied && (
                      <span
                        data-testid="market-case-pack"
                        data-pack-state="installed"
                        title={t('cases.regional_pack_in_use', {
                          defaultValue: 'Regional pack in use: {{name}}',
                          name: offer.name,
                        })}
                        className="inline-flex items-center gap-1 font-medium text-semantic-success"
                      >
                        <Check size={11} aria-hidden="true" />
                        {offer.name}
                      </span>
                    )}
                    <span className="ms-auto inline-flex items-center gap-1 font-semibold text-oe-blue">
                      {t('common.open', { defaultValue: 'Open' })}
                      <ArrowRight
                        size={12}
                        className="transition-transform group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    </span>
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        {/* ── The shelf: every market with cases, home first, one press away ── */}
        <div className="mt-auto border-t border-border-light pt-3">
          <div
            role="group"
            aria-label={t('cases.region_selector.heading', { defaultValue: 'Market' })}
            className="flex flex-wrap gap-1.5"
          >
            {shelf.map(({ market, count }) => {
              const active = market === selected;
              const name = regionDisplayName(market, i18n.language);
              return (
                <button
                  key={market}
                  type="button"
                  data-testid="market-chip"
                  data-market={market}
                  aria-pressed={active}
                  onClick={() => setPick({ home: resolution.market, market })}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-full border py-1 pe-1.5 ps-2 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 motion-reduce:transition-none',
                    active
                      ? 'border-oe-blue bg-oe-blue/10 text-oe-blue shadow-sm'
                      : 'border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue/30 hover:text-content-primary',
                  )}
                >
                  <CountryFlag code={market.toLowerCase()} size={16} className="ring-1 ring-inset ring-black/10" />
                  <span>{name}</span>
                  <span
                    aria-label={t('cases.selector.count', { defaultValue: '{{count}} cases', count })}
                    className={clsx(
                      'rounded-full px-1.5 text-2xs font-semibold tabular-nums',
                      active ? 'bg-oe-blue text-white' : 'bg-surface-secondary text-content-tertiary',
                    )}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
