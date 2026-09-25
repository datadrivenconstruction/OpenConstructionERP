// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * WhatsNewCard — friendly "what's new in vX.Y.Z" release-notes card.
 *
 * Compact single-row variant (audit 2026-05-23, requested: make it one row
 * instead of two, and once the user has closed it, offer it only behind a
 * button):
 *
 *   - One horizontal row: sparkle badge → version headline → short tagline
 *     → 6 chip pills (one per category, icon + label) → tour CTA + close.
 *   - Each chip is a `<button>` that toggles a small inline popover with
 *     the previous bullet content. Hover (desktop) or tap (mobile) opens
 *     it; click outside or another chip closes it.
 *   - Total height ~80–100 px on a 13" laptop. Chips wrap to a second row
 *     only on narrow viewports (sm and below) — acceptable degradation.
 *
 * Dismissal & reopen:
 *
 *   - First visit on a new major.minor → card auto-shown.
 *   - Click X / Dismiss → card hidden, a small "What's new" pill renders
 *     in its place for as long as the dashboard stays open, so a close by
 *     mistake can be undone. `localStorage.oe.last_seen_version` persists
 *     the dismissal for the version (next major.minor bump resets it).
 *   - Next visit after a dismissal → nothing at all. The pill used to stay
 *     on the dashboard for good, which meant the card could never really be
 *     closed; the header's What's new button is the lasting way back to the
 *     release news.
 *
 * Tour wiring is preserved: the "Take a quick tour" affordance dispatches
 * `window.CustomEvent('oe:start-tour')` exactly as before.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Sparkles,
  X,
  ArrowRight,
  Scissors,
  Ruler,
  Mountain,
  Camera,
  Coins,
  GraduationCap,
  type LucideIcon,
} from 'lucide-react';
import { APP_VERSION, isNewerFeatureRelease } from '@/shared/lib/version';

/** localStorage key that records which release the user has acknowledged. */
const LAST_SEEN_KEY = 'oe.last_seen_version';

interface Section {
  /** Stable identifier used for React keys + i18n key suffix. */
  id: string;
  /** lucide icon constructor — rendered with the card's accent treatment. */
  icon: LucideIcon;
  /** Translation key for the chip label (with English fallback). */
  titleKey: string;
  titleDefault: string;
  /** Compact 1–2 word chip label (shown on the pill itself). */
  chipKey: string;
  chipDefault: string;
  /** Short popover bullets (1–3 plain-language sentences). */
  bullets: { key: string; default: string }[];
}

/* ── v11.0.0 release content ────────────────────────────────────────────
   Six chips for the v11.0 wave: the new point cloud review tools take the
   headline (section a scan, measure on it, colour it by height, snapshot a
   view), then onboarding that leads with the cost base, and the start-here
   worked cases now translated into every language. Bullets surface only
   when the chip is expanded. */
const SECTIONS_V1110: Section[] = [
  {
    id: 'pc-section',
    icon: Scissors,
    titleKey: 'whatsnew.v1110.section.title',
    titleDefault: 'Slice a point cloud',
    chipKey: 'whatsnew.v1110.section.chip',
    chipDefault: 'Section a scan',
    bullets: [
      {
        key: 'whatsnew.v1110.section.b1',
        default:
          'Cut a reality-capture scan to a height band and read just that slice.',
      },
      {
        key: 'whatsnew.v1110.section.b2',
        default:
          'Switch the slice to a top-down plan view to work it like a floor plan.',
      },
    ],
  },
  {
    id: 'pc-measure',
    icon: Ruler,
    titleKey: 'whatsnew.v1110.measure.title',
    titleDefault: 'Measure on the cloud',
    chipKey: 'whatsnew.v1110.measure.chip',
    chipDefault: 'Measure points',
    bullets: [
      {
        key: 'whatsnew.v1110.measure.b1',
        default:
          'Measure point to point and read the distance with its horizontal and vertical parts in millimetres.',
      },
      {
        key: 'whatsnew.v1110.measure.b2',
        default:
          'Box off a region with a clip box to isolate part of a scan.',
      },
    ],
  },
  {
    id: 'pc-elevation',
    icon: Mountain,
    titleKey: 'whatsnew.v1110.elevation.title',
    titleDefault: 'Colour points by height',
    chipKey: 'whatsnew.v1110.elevation.chip',
    chipDefault: 'Elevation colours',
    bullets: [
      {
        key: 'whatsnew.v1110.elevation.b1',
        default:
          'Colour the cloud by elevation with a legend from the lowest to the highest point.',
      },
      {
        key: 'whatsnew.v1110.elevation.b2',
        default:
          'Pin a height band to hold the colour range while you look around.',
      },
    ],
  },
  {
    id: 'pc-snapshot',
    icon: Camera,
    titleKey: 'whatsnew.v1110.snapshot.title',
    titleDefault: 'Save the view',
    chipKey: 'whatsnew.v1110.snapshot.chip',
    chipDefault: 'Snapshot',
    bullets: [
      {
        key: 'whatsnew.v1110.snapshot.b1',
        default:
          'Save the current point cloud view as a PNG image in one click.',
      },
    ],
  },
  {
    id: 'onboarding-base',
    icon: Coins,
    titleKey: 'whatsnew.v1110.onboarding.title',
    titleDefault: 'Onboarding leads with the cost base',
    chipKey: 'whatsnew.v1110.onboarding.chip',
    chipDefault: 'Cost base first',
    bullets: [
      {
        key: 'whatsnew.v1110.onboarding.b1',
        default:
          'Choose your national price base first, right at the start of setup.',
      },
      {
        key: 'whatsnew.v1110.onboarding.b2_modules',
        default:
          'The modules switched on follow the company profile you pick, and a profile with its own workspace opens the menu shaped to how you work.',
      },
    ],
  },
  {
    id: 'start-here',
    icon: GraduationCap,
    titleKey: 'whatsnew.v1110.cases.title',
    titleDefault: 'Learn by example',
    chipKey: 'whatsnew.v1110.cases.chip',
    chipDefault: 'Start-here cases',
    bullets: [
      {
        key: 'whatsnew.v1110.cases.b1',
        default:
          'A start-here row on the dashboard opens worked cases you can follow step by step.',
      },
      {
        key: 'whatsnew.v1110.cases.b2',
        default:
          'The full case library is translated into every language.',
      },
    ],
  },
];

export interface WhatsNewCardProps {
  /** When true, ignores localStorage and forces the card to render. Used by
   *  the Settings → "Show release highlights" action and tests. */
  forceShow?: boolean;
  /** Override the persisted version (test seam). */
  versionOverride?: string;
}

type Mode = 'card' | 'pill';

export function WhatsNewCard({ forceShow = false, versionOverride }: WhatsNewCardProps = {}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const version = versionOverride ?? APP_VERSION;
  /** What we render in the slot: full card, just the reopen pill, or nothing. */
  const [mode, setMode] = useState<Mode | null>(null);
  /** Drives the entrance transition for the full card. */
  const [mounted, setMounted] = useState<boolean>(false);
  /** Which chip's popover (if any) is currently expanded. */
  const [openChipId, setOpenChipId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Decide initial visibility. Wrapped in try/catch so a hardened browser
  // without localStorage (Safari private mode, locked-down kiosks) still
  // renders the dashboard rather than crashing the whole tree.
  useEffect(() => {
    let show = forceShow;
    if (!show) {
      try {
        show = isNewerFeatureRelease(version, window.localStorage.getItem(LAST_SEEN_KEY));
      } catch {
        show = false;
      }
    }
    if (show) {
      setMode('card');
      // Trigger the entry animation on the next frame so the card actually
      // slides in instead of appearing pre-positioned.
      const id = window.requestAnimationFrame(() => setMounted(true));
      return () => window.cancelAnimationFrame(id);
    }
    // Already acknowledged (or storage unavailable): nothing. The reopen pill
    // belongs to the visit in which the card was closed, not to every visit
    // after it.
    setMode(null);
    return undefined;
  }, [forceShow, version]);

  // Close the chip popover when clicking outside the card.
  //
  // The expanded chip's detail popover is rendered through a portal to
  // document.body (see ChipWithPopover), so it lives OUTSIDE containerRef.
  // A naive `!root.contains(target)` check therefore treats clicks inside
  // the popover as "outside" and closes it on mousedown — which unmounts
  // the popover before an inner control (e.g. the "Read more" link) can
  // fire its onClick. Guard against that by also ignoring events that
  // originate inside any portaled chip popover. True outside clicks still
  // close the popover with the same mousedown semantics.
  useEffect(() => {
    if (mode !== 'card' || !openChipId) return undefined;
    const onClick = (ev: MouseEvent) => {
      const root = containerRef.current;
      if (!root) return;
      const target = ev.target as HTMLElement | null;
      if (root.contains(target)) return;
      if (target?.closest('[id^="whatsnew-chip-"][id$="-popover"]')) return;
      setOpenChipId(null);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [mode, openChipId]);

  const handleDismiss = useCallback(() => {
    setMounted(false);
    setOpenChipId(null);
    // Persist the version so the next dashboard visit stays quiet.
    try {
      window.localStorage.setItem(LAST_SEEN_KEY, version);
    } catch {
      /* localStorage unavailable — silent */
    }
    // Wait for the leave animation to complete before swapping to the pill.
    window.setTimeout(() => setMode('pill'), 200);
  }, [version]);

  const handleReopen = useCallback(() => {
    setMode('card');
    setOpenChipId(null);
    // Re-trigger the entry animation just like the initial render.
    setMounted(false);
    window.requestAnimationFrame(() => setMounted(true));
  }, []);

  const handleTour = useCallback(() => {
    try {
      window.dispatchEvent(
        new CustomEvent('oe:start-tour', { detail: { from: 'whatsnew' } }),
      );
    } catch {
      /* CustomEvent unsupported — silent */
    }
    handleDismiss();
  }, [handleDismiss]);

  const handleChangelog = useCallback(() => {
    handleDismiss();
    // AboutPage already exposes a `data-changelog-anchor` element that the
    // page's own "Changelog" link scrolls to via #changelog. Use the same
    // hash so the in-app behaviour stays consistent with the rest of the
    // About page.
    navigate('/about#changelog');
  }, [navigate, handleDismiss]);

  const sections = useMemo(() => SECTIONS_V1110, []);

  if (mode === null) return null;

  if (mode === 'pill') {
    return (
      <div className="flex">
        <button
          type="button"
          onClick={handleReopen}
          aria-label={t('whatsnew.reopen', { defaultValue: "What's new" })}
          className={[
            'inline-flex items-center gap-2 rounded-full',
            'border border-sky-400/50 ring-1 ring-sky-500/20',
            'dark:border-sky-500/40 dark:ring-sky-400/15',
            'bg-white/65 dark:bg-slate-900/50 backdrop-blur-md',
            'px-4 py-2 text-[13px] font-medium',
            'text-blue-700 hover:text-blue-800 dark:text-sky-200 dark:hover:text-sky-100',
            'hover:bg-sky-500/10 dark:hover:bg-sky-400/10',
            'hover:ring-sky-500/40 hover:shadow-md hover:shadow-sky-500/20',
            'shadow-sm shadow-sky-500/10 transition-all',
          ].join(' ')}
        >
          <Sparkles size={16} strokeWidth={2.25} />
          <span>
            {t('whatsnew.reopen', { defaultValue: "What's new" })}
          </span>
          <span className="text-blue-600/70 dark:text-sky-300/70">v{version}</span>
        </button>
      </div>
    );
  }

  // mode === 'card'
  return (
    <div
      ref={containerRef}
      role="region"
      aria-label={t('whatsnew.title', {
        defaultValue: "What's new in v{{version}}",
        version,
      })}
      className={[
        'relative overflow-visible rounded-xl border ring-1',
        'border-sky-400/50 ring-sky-500/10',
        'dark:border-sky-500/40 dark:ring-sky-400/10',
        'bg-gradient-to-br from-sky-50/90 via-blue-50/85 to-cyan-50/80',
        'dark:from-sky-950/40 dark:via-blue-950/30 dark:to-cyan-950/20',
        'backdrop-blur-md shadow-md shadow-sky-500/10',
        'transition-all duration-300 ease-out',
        mounted ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-2',
      ].join(' ')}
    >
      <div className="flex flex-wrap items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2.5">
        {/* Sparkle badge */}
        <div className="relative shrink-0">
          <span
            aria-hidden="true"
            className="absolute inset-0 rounded-lg bg-sky-500/30 animate-ping"
          />
          <div className="relative flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-sky-500 to-blue-600 text-white shadow-sm shadow-blue-500/30">
            <Sparkles size={13} strokeWidth={2.5} />
          </div>
        </div>

        {/* Headline + tagline (single line on desktop) */}
        <div className="flex min-w-0 items-baseline gap-2">
          <h2 className="truncate text-[13px] sm:text-sm font-semibold text-blue-900 dark:text-sky-100 leading-tight">
            {t('whatsnew.title', {
              defaultValue: "What's new in v{{version}}",
              version,
            })}
          </h2>
          <span className="hidden md:inline truncate text-[12px] text-blue-700/75 dark:text-sky-300/70">
            {t('whatsnew.tagline', {
              defaultValue: 'Tap a chip for details.',
            })}
          </span>
        </div>

        {/* Chip row — flex-grow pushes the trailing buttons to the right.
         *  Each chip's popover is rendered through a portal (`ChipPopover`
         *  below) because the parent card uses `backdrop-blur-md`, which
         *  creates a stacking context. An absolutely-positioned popover
         *  inside that context cannot escape it via z-index — it always
         *  paints below sibling widgets on the dashboard. Portaling to
         *  document.body removes that constraint. */}
        <div className="flex flex-1 flex-wrap items-center gap-1.5 min-w-0">
          {sections.map((s) => {
            const Icon = s.icon;
            const expanded = openChipId === s.id;
            return (
              <ChipWithPopover
                key={s.id}
                section={s}
                expanded={expanded}
                onToggle={() => setOpenChipId(expanded ? null : s.id)}
                onReadMore={handleChangelog}
                Icon={Icon}
                t={t}
              />
            );
          })}
        </div>

        {/* Trailing actions: tour CTA, changelog link, close */}
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={handleTour}
            className="inline-flex items-center gap-1 rounded-full bg-gradient-to-br from-sky-500 to-blue-600 hover:from-sky-600 hover:to-blue-700 px-2.5 py-1 text-[11px] font-semibold text-white shadow-sm shadow-blue-500/30 ring-1 ring-blue-500/20 transition-all"
          >
            <Sparkles size={11} />
            <span className="hidden sm:inline">
              {t('whatsnew.tour_cta', { defaultValue: 'Take a quick tour' })}
            </span>
            <span className="sm:hidden">
              {t('whatsnew.tour_cta_short', { defaultValue: 'Tour' })}
            </span>
          </button>
          <button
            type="button"
            onClick={handleChangelog}
            className="hidden sm:inline-flex items-center gap-0.5 rounded-full px-2 py-1 text-[11px] font-medium text-blue-700 hover:text-blue-800 dark:text-sky-300 dark:hover:text-sky-200 hover:bg-sky-500/10 dark:hover:bg-sky-400/10 transition-colors"
          >
            {t('whatsnew.changelog_link', {
              defaultValue: 'Full release notes',
            })}
            <ArrowRight size={11} />
          </button>
          <button
            type="button"
            onClick={handleDismiss}
            aria-label={t('whatsnew.dismiss', { defaultValue: 'Dismiss' })}
            className="flex h-7 w-7 items-center justify-center rounded-md text-sky-600/70 hover:text-blue-700 hover:bg-sky-500/10 dark:text-sky-300/70 dark:hover:text-sky-100 dark:hover:bg-sky-400/10 transition-colors"
          >
            <X size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}

export default WhatsNewCard;

/* ── ChipWithPopover ───────────────────────────────────────────────────────
 *  A chip that, when expanded, renders its detail popover through a portal
 *  attached to `document.body`. This is the only way to make the popover
 *  paint above the rest of the dashboard: the WhatsNewCard root uses
 *  `backdrop-blur-md`, and any `filter`-style property creates a CSS
 *  stacking context that traps `position:absolute` descendants — even with
 *  `z-50` they still render below sibling widgets that live outside the
 *  card. A portal escapes that context entirely.
 *
 *  Position is measured from the chip button's `getBoundingClientRect()`
 *  on mount and re-measured on scroll / resize so the popover tracks the
 *  chip if the page moves while it is open.
 */

interface ChipWithPopoverProps {
  section: Section;
  expanded: boolean;
  onToggle: () => void;
  onReadMore: () => void;
  Icon: LucideIcon;
  t: (key: string, options?: { defaultValue: string }) => string;
}

function ChipWithPopover({
  section: s,
  expanded,
  onToggle,
  onReadMore,
  Icon,
  t,
}: ChipWithPopoverProps) {
  const chipRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  // Re-measure the chip's screen position so the portaled popover stays
  // anchored. useLayoutEffect prevents a one-frame flicker at (0,0).
  useLayoutEffect(() => {
    if (!expanded) {
      setPos(null);
      return undefined;
    }
    const measure = () => {
      const el = chipRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      // Default-align under the chip; clamp right edge so a chip near the
      // right viewport edge doesn't push the 400px popover off-screen.
      const POPOVER_WIDTH = 400;
      const MARGIN = 8;
      const maxLeft = window.innerWidth - POPOVER_WIDTH - MARGIN;
      const left = Math.max(MARGIN, Math.min(r.left, maxLeft));
      setPos({ top: r.bottom + 6, left });
    };
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [expanded]);

  // Outside-click handler runs against BOTH the chip and the portaled
  // popover so clicking inside the popover doesn't close it.
  useEffect(() => {
    if (!expanded) return undefined;
    const onMouseDown = (ev: MouseEvent) => {
      const target = ev.target as Node;
      if (chipRef.current?.contains(target)) return;
      if (popoverRef.current?.contains(target)) return;
      onToggle();
    };
    document.addEventListener('mousedown', onMouseDown);
    return () => document.removeEventListener('mousedown', onMouseDown);
  }, [expanded, onToggle]);

  return (
    <>
      <button
        ref={chipRef}
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={`whatsnew-chip-${s.id}-popover`}
        title={t(s.titleKey, { defaultValue: s.titleDefault })}
        className={[
          'inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-medium',
          'ring-1 transition-colors',
          expanded
            ? 'bg-gradient-to-br from-sky-500 to-blue-600 text-white ring-blue-500/40 shadow-sm shadow-blue-500/30'
            : 'bg-white/65 dark:bg-slate-900/45 text-blue-900 dark:text-sky-100 ring-sky-500/25 hover:bg-sky-500/15 dark:hover:bg-sky-400/15',
        ].join(' ')}
      >
        <Icon size={11} strokeWidth={2.25} />
        <span>{t(s.chipKey, { defaultValue: s.chipDefault })}</span>
      </button>
      {expanded && pos
        ? createPortal(
            <div
              ref={popoverRef}
              id={`whatsnew-chip-${s.id}-popover`}
              role="dialog"
              aria-label={t(s.titleKey, { defaultValue: s.titleDefault })}
              style={{
                position: 'fixed',
                top: pos.top,
                left: pos.left,
                width: 400,
                // z-[1000] sits above the sticky AppLayout header (z-30),
                // dashboard widget cards, and any module floating UI we ship.
                // Modal overlays use z-[2000]+ so this still ducks under them.
                zIndex: 1000,
              }}
              className={[
                'rounded-lg border border-sky-300/60 ring-1 ring-sky-500/10',
                'dark:border-sky-700/50 dark:ring-sky-400/10',
                'bg-white/95 dark:bg-slate-900/95 backdrop-blur-md',
                'shadow-lg shadow-sky-500/20 p-3',
              ].join(' ')}
            >
              <h3 className="text-[12px] font-semibold text-blue-900 dark:text-sky-100 leading-snug mb-1.5 line-clamp-4">
                {t(s.titleKey, { defaultValue: s.titleDefault })}
              </h3>
              <ul className="space-y-0.5">
                {s.bullets.map((b) => (
                  <li
                    key={b.key}
                    className="flex items-start gap-1.5 text-xs leading-snug text-blue-900/85 dark:text-sky-100/85"
                  >
                    <span
                      aria-hidden="true"
                      className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-sky-500/70"
                    />
                    <span>{t(b.key, { defaultValue: b.default })}</span>
                  </li>
                ))}
              </ul>
              <button
                type="button"
                onClick={onReadMore}
                className="mt-2 inline-flex items-center gap-0.5 text-[11px] font-medium text-blue-700 hover:text-blue-800 dark:text-sky-300 dark:hover:text-sky-100 transition-colors"
              >
                {t('whatsnew.read_more', { defaultValue: 'Read more' })}
                <ArrowRight size={11} />
              </button>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
