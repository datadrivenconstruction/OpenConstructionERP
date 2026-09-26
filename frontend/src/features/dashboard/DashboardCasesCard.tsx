// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// DashboardCasesCard - the "Cases" entry block on the dashboard.
//
// More than a link: it surfaces a gallery of cases the user can jump straight
// into, ranked so that anything half-finished comes first (so you can resume),
// then cases that match the role and company the user picked on the Cases hub,
// then the rest by order. Each tile drops the user directly into that case; the
// header and the browse button go to the full hub.
//
// THE BLOCK IS THE USER'S, NOT OURS. It is registry widget `cases_learn`
// (widgetRegistry.ts), rendered by DashboardPage inside the customizable grid,
// which means it can already be reordered, narrowed and hidden from Customize
// like every other card. That was only reachable from a panel most people
// never open, so the card carries the same two controls itself: WIDTH, which
// is the dashboard's own per-widget span preference, and HIDE, which is the
// dashboard's own hidden set. Neither is a new mechanism and neither is local
// to this card - narrowing here moves the same slider Customize shows, and a
// hidden card comes back from Customize, by the name the registry gives it.
//
// The gallery is sized FROM that width preference rather than beside it. The
// grid's breakpoints are viewport-wide, not container-wide, so a half-width
// card asked for six columns would draw six microscopic tiles on a wide screen:
// the column count, the preview count and the type scale all have to come from
// the same number. They do, in GALLERY_BY_SPAN below.

import { Suspense, lazy, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  GraduationCap,
  ArrowRight,
  PlayCircle,
  Sparkles,
  Minimize2,
  Maximize2,
  EyeOff,
} from 'lucide-react';
import { PLAYBOOKS } from '@/features/cases/playbooks';
import { useCasesStore } from '@/features/cases/useCasesStore';
import { completedCount } from '@/features/cases/progress';
import { tintFor } from '@/features/cases/categories';
import { dealCaseFaces } from '@/features/cases/caseFaces';
import { CaseFacePhoto } from '@/features/cases/CaseFacePhoto';

import { HEX_PORTRAIT_ASPECT, HEX_PORTRAIT_CLIP } from '@/shared/lib/honeycomb';
import { fmtList } from '@/shared/lib/formatters';
import { rolesForPlaybook, ROLE_BY_ID } from '@/features/cases/roles';
import { iconFor } from '@/features/cases/icons';
import { CaseArt } from '@/features/cases/CaseArt';
import { useDashboardLayoutStore } from '@/stores/useDashboardLayoutStore';
import { DASHBOARD_WIDGET_BY_ID } from './widgetRegistry';

// The video half of the card. Lazy, so the video catalogue arrives with this
// card and not with the dashboard's own chunk.
const DashboardVideosStrip = lazy(() => import('@/features/videos/DashboardVideosStrip'));

/** How many video thumbnails each width shows: one row, Start here first. */
const VIDEOS_BY_SPAN: Record<SpanStep, number> = { 2: 2, 3: 3, 4: 4, 6: 4 };

/** This card's id in the dashboard widget registry. Its width and its
 *  visibility are both stored against it, so the id is the whole link between
 *  the controls below and the preference that survives a reload. */
const CASES_WIDGET_ID = 'cases_learn';

/** The four widths the dashboard grid can actually draw. `DASH_SPAN_CLASS` in
 *  DashboardPage maps exactly these; a span outside the set falls back to full
 *  width there, which would leave this card drawing a narrow gallery inside a
 *  wide box. The controls step through this list and write nothing else. */
const SPAN_STEPS = [2, 3, 4, 6] as const;
type SpanStep = (typeof SPAN_STEPS)[number];

interface GalleryShape {
  /** Case tiles to preview. The "all cases" tile is drawn on top of this, so
   *  each count is one short of a whole number of rows.
   *
   *  Every column count in the same `columns` string divides that total, which
   *  used to hold only at span 6. It holds at all four now because the ladders
   *  were rebuilt around it: no breakpoint is left drawing a short last row,
   *  which is what a gallery meant to read as two tidy rows was always for. */
  count: number;
  /** Complete literal Tailwind column classes. NEVER built by concatenation:
   *  the JIT only keeps classes it can see whole, which is the same rule the
   *  comment at the top of features/cases/companyTypes.ts sets out for tints. */
  columns: string;
  /** Portrait size on a tile, as a share of the tile's width. */
  faceClass: string;
  /** Type scale for the case title. */
  titleClass: string;
}

/**
 * How the gallery is drawn at each width. Full width is the default and is
 * meant to read as a real part of the dashboard: seventeen cases plus the way
 * into the rest, NINE across on a wide screen, which is TWO rows.
 *
 * Nine, not the six it drew before, and the block loses about a quarter of its
 * height for it. Height here is not set by a height: a tile is a 16/9 banner
 * over two lines of text that never wrap (both are `truncate`), so the text
 * block is a constant and only the banner moves with the column width. On a
 * 1400px-wide card - stated because the number depends on it - the tile goes
 * from roughly 227px across to 148px, its banner from 128px to 83px, and the
 * two rows from about 366px to 272px. Six MORE cases in a quarter LESS room,
 * which is the trade the width was hiding all along: at six across the tiles
 * were larger than the line art inside them needed.
 *
 * Two rows is the rule at every width, not a number chosen for the full-width
 * card alone. Each count is two rows at the widest column count in its own
 * `columns` string, minus the one cell the "all cases" tile takes. That is what
 * keeps the ladder monotonic: narrowing the card has to show FEWER cases, and a
 * count fixed only at span 6 would have left a card that grew when you shrank
 * it. Spans 4 and 3 land on the same number because they share a `columns`
 * string; only the portrait size and the type scale differ between them.
 *
 * The narrow breakpoints moved up with the wide ones on purpose. Raising only
 * the widest column count would have kept the same tile count on a phone at
 * two across, so the block a laptop shows a third shorter would have grown by
 * half on the device with the least room for it.
 *
 * Six across starts at `md` rather than `sm` for the same reason nine is the
 * ceiling and not twelve. A tile is only ever as tall as it is wide, so the
 * column count that reads well is the one where the drawing still reads: six
 * across a 640px viewport is a 105px tile, narrower than the portrait band and
 * the title need, while at 768 it is 128px. The ladder is bounded by the
 * smallest tile that still shows a picture, not by how many will fit.
 */
const GALLERY_BY_SPAN: Record<SpanStep, GalleryShape> = {
  6: {
    count: 17,
    columns: 'grid-cols-3 md:grid-cols-6 xl:grid-cols-9',
    faceClass: 'w-[26%] max-w-[3rem]',
    titleClass: 'text-xs',
  },
  4: {
    count: 11,
    columns: 'grid-cols-3 sm:grid-cols-4 lg:grid-cols-6',
    faceClass: 'w-[26%] max-w-[2.75rem]',
    titleClass: 'text-xs',
  },
  3: {
    count: 11,
    columns: 'grid-cols-3 sm:grid-cols-4 lg:grid-cols-6',
    faceClass: 'w-[30%] max-w-[2.5rem]',
    titleClass: 'text-xs',
  },
  2: {
    count: 7,
    columns: 'grid-cols-2 sm:grid-cols-4',
    faceClass: 'w-[30%] max-w-[2.5rem]',
    titleClass: 'text-xs',
  },
};

/** The stored span forced onto a width the grid can draw. */
function normaliseSpan(value: number | undefined): SpanStep {
  return SPAN_STEPS.includes(value as SpanStep) ? (value as SpanStep) : 6;
}

export function DashboardCasesCard() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const runs = useCasesStore((s) => s.runs);
  const roles = useCasesStore((s) => s.roles);
  const companyTypes = useCasesStore((s) => s.companyTypes);

  // Width and visibility both come from the dashboard's own layout store: the
  // same values Customize writes, persisted under `oe.dashboard-layout`, so
  // whichever surface the user reaches for, there is one preference behind it.
  const savedSpan = useDashboardLayoutStore((s) => s.spans[CASES_WIDGET_ID]);
  const setSpan = useDashboardLayoutStore((s) => s.setSpan);
  const hide = useDashboardLayoutStore((s) => s.hide);
  const span = normaliseSpan(
    savedSpan ?? DASHBOARD_WIDGET_BY_ID[CASES_WIDGET_ID]?.defaultSpan,
  );
  const shape = GALLERY_BY_SPAN[span];
  const spanIndex = SPAN_STEPS.indexOf(span);
  const narrower = SPAN_STEPS[spanIndex - 1];
  const wider = SPAN_STEPS[spanIndex + 1];

  // Best progress a case reached across any run (unscoped or per sample
  // project), used both to rank and to show a resume hint. Ranked over the
  // whole catalogue and windowed afterwards, so changing the width re-slices
  // the same order instead of re-ranking it.
  const ranked = useMemo(() => {
    const scored = PLAYBOOKS.map((pb) => {
      let best = 0;
      for (const [k, prog] of Object.entries(runs)) {
        if (k === pb.id || k.startsWith(`${pb.id}::`)) {
          best = Math.max(best, completedCount(prog, pb));
        }
      }
      const total = pb.steps.length;
      const inProgress = best > 0 && best < total;
      // Both hub filters hold a list, so count the overlap rather than test a
      // single id: a case that fits all three of someone's roles should outrank
      // one that fits a single role, and a boolean cannot say that.
      const pbRoles = rolesForPlaybook(pb);
      const roleMatches = roles.filter((r) => pbRoles.includes(r)).length;
      const companyMatches = companyTypes.filter((c) =>
        pb.companyTypes.includes(c),
      ).length;
      return { pb, best, total, inProgress, roleMatches, companyMatches };
    });
    scored.sort((a, b) => {
      if (a.inProgress !== b.inProgress) return a.inProgress ? -1 : 1;
      const am = a.roleMatches * 2 + a.companyMatches;
      const bm = b.roleMatches * 2 + b.companyMatches;
      if (am !== bm) return bm - am;
      return a.pb.order - b.pb.order;
    });
    return scored;
  }, [runs, roles, companyTypes]);

  const picks = useMemo(() => ranked.slice(0, shape.count), [ranked, shape.count]);

  // Name every role the user picked, joined the way their language joins a
  // list. Printing only the first would drop the others silently, which is the
  // same thing the hub filters were fixed for.
  const roleLabel = useMemo(() => {
    const names = roles.map((r) =>
      t(ROLE_BY_ID[r]?.labelKey ?? '', { defaultValue: ROLE_BY_ID[r]?.labelDefault ?? '' }),
    );
    // Through the shared helper rather than Intl directly, so this reads
    // `getIntlLocale()` - the app's own language-to-BCP-47 map - instead of the
    // raw i18next tag. The two differ for the languages the map exists to
    // translate, and a list separator chosen from an unmapped tag is the same
    // defect one layer down. `i18n.language` stays in the dependency list: it
    // is still what changes when the reader switches language.
    return fmtList(names, 'prose');
  }, [roles, t, i18n.language]);

  // Frame the preview tiles by what they actually are: something half-finished
  // to resume, a role-tuned pick, or - the default on a fresh workspace - the
  // most popular cases to start from. The ranking in `picks` is unchanged; this
  // only labels it.
  const anyInProgress = picks.some((p) => p.inProgress);
  const framingLabel = anyInProgress
    ? t('cases.dashboard_card.resume_hint', { defaultValue: 'Pick up where you left off' })
    : roles.length > 0
      ? t('cases.dashboard_card.for_role', { defaultValue: 'Picked for you' })
      : t('cases.dashboard_card.popular', { defaultValue: 'Popular starting points' });

  // Dealt over the WHOLE catalogue, which is the contract `dealCaseFaces`
  // documents and what the hub and the case page both do. Dealing over this
  // card's own window instead - which is what it used to do - handed a case a
  // different person here than it wears on the hub, and would have re-cast
  // every tile each time the width changed the size of the window.
  const faces = useMemo(() => dealCaseFaces(PLAYBOOKS), []);

  return (
    <div
      data-testid="dashboard-cases-card"
      className="rounded-xl border border-oe-blue/30 bg-gradient-to-r from-oe-blue/[0.07] via-oe-blue/[0.03] to-transparent p-4 shadow-xs animate-card-in"
      style={{ animationDelay: '120ms' }}
    >
      <div className="flex flex-wrap items-start gap-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue ring-1 ring-inset ring-oe-blue/20">
          <GraduationCap size={20} strokeWidth={1.9} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-content-primary">
              {t('cases.dashboard_card.title', { defaultValue: 'Start here - learn by example' })}
            </p>
            {/* Total library size, so the card advertises the full breadth of
                guided cases even while it only previews part of it. */}
            <span className="inline-flex shrink-0 items-center rounded-full bg-oe-blue/10 px-2 py-0.5 text-2xs font-semibold text-oe-blue ring-1 ring-inset ring-oe-blue/20">
              {t('cases.dashboard_card.total', {
                defaultValue: '{{count}} cases in total',
                count: PLAYBOOKS.length,
              })}
            </span>
          </div>
          <p className="mt-0.5 text-xs leading-relaxed text-content-secondary">
            {roles.length === 1
              ? t('cases.dashboard_card.body_role', {
                  defaultValue: 'Guided playbooks picked for a {{role}}, step by step across the modules.',
                  role: roleLabel,
                })
              : roles.length > 1
                ? t('cases.dashboard_card.body_roles', {
                    defaultValue:
                      'Guided playbooks picked for {{roles}}, step by step across the modules.',
                    roles: roleLabel,
                  })
                : t('cases.dashboard_card.body', {
                    defaultValue:
                      'Follow a guided playbook from a PDF to a priced, validated estimate, step by step across the modules.',
                  })}
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate('/cases')}
          className="group inline-flex shrink-0 items-center gap-2 rounded-lg bg-oe-blue px-4 py-2.5 text-sm font-semibold text-content-inverse shadow-sm transition-all hover:bg-oe-blue-hover hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
        >
          {t('cases.dashboard_card.cta_all', {
            defaultValue: 'Browse all {{count}} cases',
            count: PLAYBOOKS.length,
          })}
          <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
        </button>
        {/* The way out. Narrowing steps through the same four widths Customize
            offers; hiding puts the card in the same hidden set. The hide
            control names its own undo BEFORE it is pressed, because once the
            card is hidden DashboardPage stops rendering it and there is nothing
            left here to offer the way back. */}
        <div className="flex shrink-0 items-center gap-0.5">
          {narrower !== undefined && (
            <button
              type="button"
              onClick={() => setSpan(CASES_WIDGET_ID, narrower)}
              title={t('cases.dashboard_card.smaller', { defaultValue: 'Show this block smaller' })}
              aria-label={t('cases.dashboard_card.smaller', {
                defaultValue: 'Show this block smaller',
              })}
              className="rounded-md p-1.5 text-content-tertiary transition-colors hover:bg-oe-blue/10 hover:text-oe-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <Minimize2 size={14} strokeWidth={2} aria-hidden="true" />
            </button>
          )}
          {wider !== undefined && (
            <button
              type="button"
              onClick={() => setSpan(CASES_WIDGET_ID, wider)}
              title={t('cases.dashboard_card.bigger', { defaultValue: 'Show this block bigger' })}
              aria-label={t('cases.dashboard_card.bigger', {
                defaultValue: 'Show this block bigger',
              })}
              className="rounded-md p-1.5 text-content-tertiary transition-colors hover:bg-oe-blue/10 hover:text-oe-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <Maximize2 size={14} strokeWidth={2} aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            onClick={() => hide(CASES_WIDGET_ID)}
            title={t('cases.dashboard_card.hide_hint', {
              defaultValue: 'Hide this block. You can bring it back from Customize dashboard.',
            })}
            aria-label={t('cases.dashboard_card.hide_hint', {
              defaultValue: 'Hide this block. You can bring it back from Customize dashboard.',
            })}
            className="rounded-md p-1.5 text-content-tertiary transition-colors hover:bg-oe-blue/10 hover:text-oe-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          >
            <EyeOff size={14} strokeWidth={2} aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* Video guides: Start here, then picks for the reader's role and
          country. The fallback holds the row's height so nothing jumps. */}
      <Suspense fallback={<div className="mt-3 h-28" aria-hidden="true" />}>
        <DashboardVideosStrip count={VIDEOS_BY_SPAN[span]} />
      </Suspense>

      {/* Quick-launch: jump straight into a case */}
      {picks.length > 0 && (
        <div className="mt-3">
          {/* Which half this is, then the adaptive eyebrow: resume /
              role-tuned / popular starting points. */}
          <div className="mb-1.5 flex items-center gap-1 text-2xs font-medium text-content-tertiary">
            <span className="font-semibold uppercase tracking-wide text-content-secondary">
              {t('nav.cases', { defaultValue: 'Use cases' })}
            </span>
            <span aria-hidden="true">·</span>
            {anyInProgress ? (
              <PlayCircle size={11} className="text-oe-blue" aria-hidden="true" />
            ) : (
              <Sparkles size={11} className="text-oe-blue" aria-hidden="true" />
            )}
            {framingLabel}
          </div>
          {/* Picture gallery: each case leads with its line-art illustration on
              an always-light tile (the same art the Cases hub uses), so the
              block previews the library visually. How many tiles, how many
              across and how big the type is all come from the card's width. */}
          <div className={clsx('grid gap-2', shape.columns)}>
          {picks.map(({ pb, best, total, inProgress }) => {
            const face = faces.get(pb.id);
            const Icon = iconFor(pb.icon);
            const tint = tintFor(pb.category);
            const title = t(pb.titleKey, { defaultValue: pb.titleDefault });
            return (
              <button
                key={pb.id}
                type="button"
                onClick={() => navigate(`/cases/${pb.id}`)}
                title={title}
                className="group relative isolate flex flex-col overflow-hidden rounded-lg border border-border-light bg-surface-primary text-left shadow-xs transition duration-200 hover:-translate-y-0.5 hover:border-oe-blue/40 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
              >
                {/* Faint discipline wash behind the whole tile. */}
                <span
                  aria-hidden="true"
                  className={clsx('pointer-events-none absolute inset-0 -z-10', tint.softBg)}
                />
                {/* Line-art banner on an always-light tile so the linework reads
                    the same in light and dark theme. */}
                <div className="relative aspect-[16/9] w-full overflow-hidden border-b border-border-light bg-white ring-1 ring-inset ring-slate-900/[0.04]">
                  {/* Nudged off the inline-start edge so the portrait below sits
                      beside the drawing rather than on top of it. */}
                  <CaseArt
                    id={pb.id}
                    category={pb.category}
                    fallbackIcon={Icon}
                    fallbackClass={tint.text}
                    alt={title}
                    className={face ? 'ps-[14%]' : undefined}
                  />
                  {/* The specialist the case is written for, cut to the same
                      honeycomb cell the Cases hub and the marketing site use.
                      Centred on the banner's own axis rather than pinned to its
                      bottom edge: the art is already nudged clear of the
                      inline-start band by `ps-[14%]`, so the portrait has that
                      band to itself, and sitting in the middle of it reads as
                      placed rather than as having fallen into the corner. A
                      hexagon on the baseline also grew a visible gap under its
                      point, because the cell's clip path narrows exactly there.
                      Decorative - the case title below carries the meaning. */}
                  {face && (
                    <span
                      aria-hidden="true"
                      className={clsx(
                        'pointer-events-none absolute top-1/2 start-1 block -translate-y-1/2',
                        shape.faceClass,
                      )}
                    >
                      <span
                        className="block bg-white/90 p-[2px] shadow-sm shadow-slate-900/20"
                        style={{ aspectRatio: HEX_PORTRAIT_ASPECT, clipPath: HEX_PORTRAIT_CLIP }}
                      >
                        <CaseFacePhoto
                          face={face}
                          className="h-full w-full object-cover object-[50%_18%]"
                          style={{ clipPath: HEX_PORTRAIT_CLIP }}
                        />
                      </span>
                    </span>
                  )}
                  {inProgress && (
                    <span
                      className="absolute right-2 top-2 h-2.5 w-2.5 rounded-full bg-oe-blue shadow-sm ring-2 ring-white"
                      title={t('cases.card.in_progress', { defaultValue: 'In progress' })}
                      aria-hidden="true"
                    />
                  )}
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-0.5 px-2.5 py-2">
                  <span
                    className={clsx(
                      'truncate font-semibold leading-snug text-content-primary',
                      shape.titleClass,
                    )}
                  >
                    {title}
                  </span>
                  <span className="mt-auto flex items-center gap-1 text-2xs text-content-tertiary">
                    {inProgress ? (
                      <>
                        <PlayCircle size={10} className="text-oe-blue" aria-hidden="true" />
                        {t('cases.dashboard_card.resume', {
                          defaultValue: 'Resume {{done}}/{{total}}',
                          done: best,
                          total,
                        })}
                      </>
                    ) : (
                      t('cases.card.steps', { defaultValue: '{{count}} steps', count: total })
                    )}
                  </span>
                </div>
              </button>
            );
          })}
          {/* Final tile: a compact call to open the whole library, so the
              gallery always ends on an obvious way to see more cases. */}
          <button
            type="button"
            onClick={() => navigate('/cases')}
            title={t('cases.dashboard_card.cta_all', {
              defaultValue: 'Browse all {{count}} cases',
              count: PLAYBOOKS.length,
            })}
            className="group relative isolate flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-oe-blue/40 bg-oe-blue/[0.05] px-2 py-3 text-center transition duration-200 hover:-translate-y-0.5 hover:border-oe-blue/60 hover:bg-oe-blue/10 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-oe-blue/10 text-oe-blue ring-1 ring-inset ring-oe-blue/20 transition-transform group-hover:scale-105">
              <ArrowRight size={18} strokeWidth={2} aria-hidden="true" />
            </span>
            <span className="text-xs font-semibold leading-snug text-oe-blue-text">
              {t('cases.dashboard_card.more_tile', {
                defaultValue: 'All {{count}} cases',
                count: PLAYBOOKS.length,
              })}
            </span>
          </button>
          </div>
        </div>
      )}
    </div>
  );
}
