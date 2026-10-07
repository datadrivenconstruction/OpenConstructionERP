// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  Route as RouteIcon,
  X,
  ChevronDown,
  ArrowRight,
  Sparkles,
  MapPin,
  GraduationCap,
  type LucideIcon,
} from 'lucide-react';
import {
  JOURNEY_ARCS,
  JOURNEY_PHASES,
  JOURNEY_ALWAYS_ON,
  resolveJourneyPhaseKey,
  journeyRouteCandidate,
  type JourneyArcKey,
  type JourneyModule,
} from './projectJourneyData';
import { useModuleStore } from '@/stores/useModuleStore';
import type { Playbook } from '@/features/cases/types';

// The case registry eagerly bundles ~85 playbook data files, so it is loaded
// LAZILY (dynamic import when the panel opens) to keep it out of the always-on
// app-shell chunk that hosts this top-bar control. Once loaded, it tells the
// map which guided cases touch each module route.
type CaseModuleIndex = typeof import('@/features/cases/playbookModules');

// Journey chips for plugin-backed routes must hide when their module is
// disabled, exactly as the Sidebar does. Otherwise the chip is a dead link:
// Pipelines is a default-disabled plugin module with no hardcoded route, so
// clicking it would fall through to the catch-all and 404. Routes absent from
// this map are plain app routes and are always shown.
const CHIP_MODULE_ID: Record<string, string> = {
  '/pipelines': 'pipelines',
  '/collaboration': 'collaboration',
  '/benchmarks': 'cost-benchmark',
  '/sustainability': 'sustainability',
};

/**
 * ProjectJourney - a whole-platform lifecycle map opened from the top bar.
 *
 * The header shows a compact pill naming the phase the current screen belongs
 * to ("Quantify", "Estimate", ...), so the top bar is a constant orientation
 * device. Clicking it opens the full map: three arcs, eleven numbered phases
 * in the order they happen, every major module placed on the line, and an
 * "always on" band for the cross-cutting helpers. The current phase is
 * highlighted, and every module is a link, so the map doubles as navigation.
 */

// Per-arc accent. The CURRENT phase always uses the brand blue ring so "you
// are here" is unmistakable regardless of which arc it sits in.
const ARC_ACCENT: Record<
  JourneyArcKey,
  { dot: string; text: string; bar: string; wash: string; glyph: string }
> = {
  // ``wash`` is the gradient start tint behind a phase card (kept extremely
  // low so it reads as a hint of colour, never a fill); ``glyph`` tints the
  // faint phase-icon watermark. Together they give each stage a quiet, themed
  // backdrop without touching text contrast. Plan = blue, procure = violet,
  // deliver = emerald, so the three arcs read as three colour families.
  plan: {
    dot: 'bg-oe-blue',
    text: 'text-oe-blue',
    bar: 'bg-oe-blue',
    wash: 'from-oe-blue/[0.08]',
    glyph: 'text-oe-blue',
  },
  procure: {
    dot: 'bg-violet-500',
    text: 'text-violet-500',
    bar: 'bg-violet-500',
    wash: 'from-violet-500/[0.08]',
    glyph: 'text-violet-500',
  },
  deliver: {
    dot: 'bg-emerald-500',
    text: 'text-emerald-500',
    bar: 'bg-emerald-500',
    wash: 'from-emerald-500/[0.08]',
    glyph: 'text-emerald-500',
  },
};

export function ProjectJourneyButton() {
  const { t } = useTranslation();
  const location = useLocation();
  const [open, setOpen] = useState(false);

  const currentPhaseKey = useMemo(
    () => resolveJourneyPhaseKey(location.pathname),
    [location.pathname],
  );
  // The trigger stays deliberately small: just the word "Step" plus the
  // current step number. The full phase names live inside the panel, so the
  // top bar is a calm, fixed-width orientation chip, not a label that shifts
  // width every time you move between screens. Click it to open the full map.
  const phaseNumber = useMemo(() => {
    const idx = JOURNEY_PHASES.findIndex((p) => p.key === currentPhaseKey);
    return idx >= 0 ? idx + 1 : 0;
  }, [currentPhaseKey]);

  const label =
    phaseNumber > 0
      ? t('journey.button.step', { defaultValue: 'Step {{n}}', n: phaseNumber })
      : t('journey.button.default', { defaultValue: 'Project journey' });

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-testid="project-journey-button"
        title={t('journey.button.title', {
          defaultValue: 'Project journey - see where you are and what comes next',
        })}
        className={clsx(
          'flex h-8 shrink-0 items-center gap-1.5 rounded-lg border px-2.5',
          'border-border-light bg-white/70 text-content-secondary shadow-sm dark:bg-surface-primary/60',
          'transition-colors hover:border-oe-blue/40 hover:bg-oe-blue/5 hover:text-content-primary',
        )}
      >
        <RouteIcon size={14} strokeWidth={1.75} className="shrink-0 text-oe-blue" aria-hidden />
        <span className="whitespace-nowrap text-xs font-semibold max-[399px]:sr-only">{label}</span>
        <ChevronDown size={12} strokeWidth={2} className="shrink-0 text-content-quaternary" aria-hidden />
      </button>
      {open && (
        <ProjectJourneyPanel
          currentPhaseKey={currentPhaseKey}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function ProjectJourneyPanel({
  currentPhaseKey,
  onClose,
}: {
  currentPhaseKey: string | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const isModuleEnabled = useModuleStore((s) => s.isModuleEnabled);
  const closeRef = useRef<HTMLButtonElement>(null);

  // Close on Escape; focus the close button on open for keyboard users.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    closeRef.current?.focus();
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  // Load the case<->route index once the map opens. Lazy on purpose: the case
  // data must not weigh down the app-shell chunk, and the map is fully usable
  // before it resolves - the "N cases" pills simply appear a moment later.
  const [caseIndex, setCaseIndex] = useState<CaseModuleIndex | null>(null);
  useEffect(() => {
    let alive = true;
    void import('@/features/cases/playbookModules').then((mod) => {
      if (alive) setCaseIndex(mod);
    });
    return () => {
      alive = false;
    };
  }, []);

  // Cases that touch a module route: one pill navigates to the single case
  // when a module has exactly one, otherwise to the full library. The Cases
  // hub does not read a module query param, so multi-case modules open the
  // hub rather than a filtered view that would not filter.
  const casesForModule = useCallback(
    (to: string) => (caseIndex ? caseIndex.playbooksForRoute(to) : []),
    [caseIndex],
  );

  const go = useCallback(
    (to: string) => {
      navigate(to);
      onClose();
    },
    [navigate, onClose],
  );

  // A chip is shown only when its plugin module is enabled (default-true for
  // plain app routes not in the map), so the map never surfaces a dead link
  // the Sidebar deliberately hides.
  const chipEnabled = useCallback(
    (to: string) => {
      const moduleId = CHIP_MODULE_ID[to.split('?')[0]!];
      return !moduleId || isModuleEnabled(moduleId);
    },
    [isModuleEnabled],
  );

  const currentPhase = JOURNEY_PHASES.find((p) => p.key === currentPhaseKey);
  // Global 1-based number for each phase, in lifecycle order.
  const phaseNumber = (key: string) => JOURNEY_PHASES.findIndex((p) => p.key === key) + 1;

  // Render through a portal on document.body. The header and several page
  // shells create their own stacking contexts (sticky + isolate/transform),
  // which would otherwise trap this overlay *underneath* page content even at
  // a high z-index. A body-level portal escapes all of them, so the map always
  // paints on top of everything.
  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-6">
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('journey.title', { defaultValue: 'Your project journey' })}
        className="relative my-2 flex max-h-[calc(100vh-1.5rem)] w-full max-w-6xl flex-col rounded-2xl border border-border-light bg-surface-elevated shadow-2xl animate-scale-in sm:max-h-[calc(100vh-3rem)]"
      >
        {/* ── Header ─────────────────────────────────────────────────── */}
        <div className="z-10 flex shrink-0 items-start justify-between gap-3 rounded-t-2xl border-b border-border-light bg-surface-elevated px-5 py-4">
          <div className="flex items-start gap-3 min-w-0">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
              <RouteIcon size={18} strokeWidth={1.75} />
            </span>
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-content-primary">
                {t('journey.title', { defaultValue: 'Your project journey' })}
              </h2>
              <p className="mt-0.5 text-xs leading-relaxed text-content-secondary">
                {t('journey.subtitle', {
                  defaultValue:
                    'Every stage of a construction project, from first lead to handover, and where you are right now. Pick any step to jump there.',
                })}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {currentPhase && (
              <span className="hidden items-center gap-1.5 rounded-full bg-oe-blue/10 px-2.5 py-1 text-2xs font-medium text-oe-blue sm:inline-flex">
                <MapPin size={11} aria-hidden />
                {t('journey.you_are_here_named', {
                  defaultValue: 'You are here: {{phase}}',
                  phase: t(currentPhase.nameKey, { defaultValue: currentPhase.name }),
                })}
              </span>
            )}
            {/* One clear route from the map into the guided case library. */}
            <button
              type="button"
              onClick={() => go('/cases')}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-oe-blue/30 bg-oe-blue/5 px-2.5 py-1 text-2xs font-semibold text-oe-blue transition-colors hover:border-oe-blue/50 hover:bg-oe-blue/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <GraduationCap size={12} strokeWidth={2} aria-hidden />
              {t('journey.browse_cases', { defaultValue: 'Browse cases' })}
            </button>
            <button
              ref={closeRef}
              type="button"
              onClick={onClose}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* ── Arcs and phases ────────────────────────────────────────── */}
        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
          {JOURNEY_ARCS.map((arc) => {
            const accent = ARC_ACCENT[arc.key];
            const phases = JOURNEY_PHASES.filter((p) => p.arc === arc.key);
            return (
              <section key={arc.key} aria-label={t(arc.nameKey, { defaultValue: arc.name })}>
                <div className="mb-2.5 flex items-center gap-2">
                  <span className={clsx('h-2 w-2 shrink-0 rounded-full', accent.dot)} aria-hidden />
                  <h3 className={clsx('text-xs font-bold uppercase tracking-wider', accent.text)}>
                    {t(arc.nameKey, { defaultValue: arc.name })}
                  </h3>
                  <span className="truncate text-2xs text-content-tertiary">
                    {t(arc.descKey, { defaultValue: arc.desc })}
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {phases.map((phase) => {
                    const Icon: LucideIcon = phase.icon;
                    const isCurrent = phase.key === currentPhaseKey;
                    const num = phaseNumber(phase.key);
                    return (
                      <div
                        key={phase.key}
                        className={clsx(
                          'relative flex flex-col overflow-hidden rounded-xl border p-3',
                          'bg-gradient-to-br to-surface-primary transition-shadow',
                          isCurrent
                            ? 'border-oe-blue from-oe-blue/[0.12] shadow-sm ring-1 ring-oe-blue/30'
                            : clsx('border-border-light hover:shadow-sm', accent.wash),
                        )}
                      >
                        {/* Themed watermark: the phase's own icon, oversized and
                            barely-there, clipped to the card corner so each stage
                            quietly "feels like" itself. */}
                        <Icon
                          size={104}
                          strokeWidth={1}
                          aria-hidden
                          className={clsx(
                            'pointer-events-none absolute -bottom-6 -right-5 z-0',
                            isCurrent
                              ? 'text-oe-blue opacity-[0.10]'
                              : clsx(accent.glyph, 'opacity-[0.07]'),
                          )}
                        />
                        <div className="relative z-10 flex flex-1 flex-col">
                          <div className="flex items-center gap-2.5">
                            <span
                              className={clsx(
                                'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                                isCurrent
                                  ? 'bg-oe-blue text-white'
                                  : 'bg-surface-tertiary text-content-secondary',
                              )}
                            >
                              <Icon size={16} strokeWidth={1.75} />
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-1.5">
                                <span className="text-2xs font-semibold text-content-quaternary">
                                  {num}
                                </span>
                                <h4
                                  className={clsx(
                                    'truncate text-sm font-semibold',
                                    isCurrent ? 'text-oe-blue' : 'text-content-primary',
                                  )}
                                >
                                  {t(phase.nameKey, { defaultValue: phase.name })}
                                </h4>
                              </div>
                            </div>
                            {isCurrent && (
                              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-oe-blue/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-oe-blue">
                                {t('journey.here', { defaultValue: 'Here' })}
                              </span>
                            )}
                          </div>
                          <p className="mt-2 text-xs leading-relaxed text-content-secondary">
                            {t(phase.descKey, { defaultValue: phase.desc })}
                          </p>
                          <div className="mt-2.5 flex flex-wrap gap-1.5">
                            {phase.modules.filter((m) => chipEnabled(m.to)).map((m) => {
                              const cases = casesForModule(m.to);
                              return (
                                <span key={m.to} className="inline-flex items-center gap-1">
                                  <ModuleChip
                                    module={m}
                                    active={isOnRoute(location.pathname, m.to)}
                                    onClick={() => go(m.to)}
                                  />
                                  {cases.length > 0 && (
                                    <CasesPill
                                      cases={cases}
                                      onOpenCase={(id) => go(`/cases/${id}`)}
                                    />
                                  )}
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}

          {/* ── Always-on band ───────────────────────────────────────── */}
          <section
            aria-label={t('journey.always_on.title', { defaultValue: 'Always on' })}
            className="rounded-xl border border-dashed border-border-light bg-surface-secondary/40 p-3"
          >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-500/15 text-amber-500">
                <Sparkles size={15} strokeWidth={1.75} />
              </span>
              <h3 className="text-xs font-bold uppercase tracking-wider text-content-secondary">
                {t('journey.always_on.title', { defaultValue: 'Always on' })}
              </h3>
              <span className="text-2xs text-content-tertiary">
                {t('journey.always_on.desc', {
                  defaultValue: 'These help across every phase, not just one.',
                })}
              </span>
            </div>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {JOURNEY_ALWAYS_ON.filter((m) => chipEnabled(m.to)).map((m) => {
                const cases = casesForModule(m.to);
                return (
                  <span key={m.to} className="inline-flex items-center gap-1">
                    <ModuleChip
                      module={m}
                      active={isOnRoute(location.pathname, m.to)}
                      onClick={() => go(m.to)}
                    />
                    {cases.length > 0 && (
                      <CasesPill cases={cases} onOpenCase={(id) => go(`/cases/${id}`)} />
                    )}
                  </span>
                );
              })}
            </div>
          </section>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function ModuleChip({
  module,
  active,
  onClick,
}: {
  module: JourneyModule;
  active: boolean;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'group inline-flex items-center gap-1 rounded-md border px-2 py-1 text-2xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        active
          ? 'border-oe-blue/50 bg-oe-blue/10 text-oe-blue'
          : 'border-border-light bg-surface-secondary text-content-secondary hover:border-oe-blue/40 hover:bg-oe-blue/5 hover:text-content-primary',
      )}
    >
      <span className="truncate">{t(module.labelKey, { defaultValue: module.label })}</span>
      <ArrowRight
        size={11}
        className="shrink-0 opacity-0 transition-opacity group-hover:opacity-60"
        aria-hidden
      />
    </button>
  );
}

/** Fixed width of the cases preview / menu floating layer (px). */
const CASES_POP_WIDTH = 288;

/**
 * A graduation-cap + count control sitting beside a module chip when one or
 * more guided cases visit that module. It is its own button (never nested in
 * the chip button). Hovering or focusing it previews the first few case
 * titles; clicking opens a small keyboard-navigable menu whose rows link
 * straight to each case. The floating layer renders in a portal on
 * ``document.body`` so the phase card's ``overflow-hidden`` never clips it, and
 * it stays quiet: it only appears where cases exist, so a module with no cases
 * renders no pill at all and its count stays non-interactive.
 */
function CasesPill({
  cases,
  onOpenCase,
}: {
  cases: Playbook[];
  onOpenCase: (id: string) => void;
}) {
  const { t } = useTranslation();
  const count = cases.length;

  const btnRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  // Set true just before we programmatically return focus to the trigger (Esc /
  // Tab out) so the immediate ``focus`` event does not re-open the preview.
  const suppressPreviewRef = useRef(false);
  const activeRef = useRef(0);

  // ``preview`` = passive hover/focus hint; ``open`` = interactive menu.
  const [mode, setMode] = useState<'closed' | 'preview' | 'open'>('closed');
  const [active, setActive] = useState(0);
  const [layout, setLayout] = useState<{
    left: number;
    top: number | null;
    bottom: number | null;
    maxH: number;
  } | null>(null);

  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  const close = useCallback((focusTrigger: boolean) => {
    setMode('closed');
    if (focusTrigger) {
      suppressPreviewRef.current = true;
      btnRef.current?.focus();
    }
  }, []);

  const focusItem = useCallback((i: number) => {
    itemRefs.current[i]?.focus();
  }, []);

  // Anchor the floating layer under the pill, flipping above when the bottom of
  // the (scrollable) map panel is close. When placed above we pin the layer's
  // bottom edge so it hugs the pill regardless of its own height.
  const place = useCallback(() => {
    const r = btnRef.current?.getBoundingClientRect();
    if (!r) return;
    const margin = 8;
    const gap = 6;
    const left = Math.min(Math.max(r.left, margin), window.innerWidth - CASES_POP_WIDTH - margin);
    const spaceBelow = window.innerHeight - r.bottom - gap - margin;
    const spaceAbove = r.top - gap - margin;
    const below = spaceBelow >= 200 || spaceBelow >= spaceAbove;
    const maxH = Math.max(120, Math.min(340, below ? spaceBelow : spaceAbove));
    setLayout(
      below
        ? { left, top: r.bottom + gap, bottom: null, maxH }
        : { left, top: null, bottom: window.innerHeight - r.top + gap, maxH },
    );
  }, []);

  // Position synchronously before paint whenever the layer is visible.
  useLayoutEffect(() => {
    if (mode === 'closed') return;
    place();
  }, [mode, place]);

  // Keep the layer anchored while the map panel scrolls or the window resizes.
  useEffect(() => {
    if (mode === 'closed') return undefined;
    const onMove = () => place();
    window.addEventListener('scroll', onMove, true);
    window.addEventListener('resize', onMove);
    return () => {
      window.removeEventListener('scroll', onMove, true);
      window.removeEventListener('resize', onMove);
    };
  }, [mode, place]);

  // Move focus onto the first row when the menu opens.
  useEffect(() => {
    if (mode !== 'open') return undefined;
    const raf = requestAnimationFrame(() => focusItem(activeRef.current));
    return () => cancelAnimationFrame(raf);
  }, [mode, focusItem]);

  // Outside-click closes the open menu (clicks on the trigger or the menu are
  // treated as inside so the trigger keeps toggling).
  useEffect(() => {
    if (mode !== 'open') return undefined;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (btnRef.current?.contains(target) || popRef.current?.contains(target)) return;
      setMode('closed');
    };
    document.addEventListener('mousedown', onDown, true);
    return () => document.removeEventListener('mousedown', onDown, true);
  }, [mode]);

  // Keyboard handling for the open menu. Captured at the document so it works
  // wherever focus sits, and Escape/arrows are stopped from bubbling to the map
  // panel's own Escape-to-close so this menu shuts first, on its own.
  useEffect(() => {
    if (mode !== 'open' || count === 0) return undefined;
    const onKey = (e: KeyboardEvent) => {
      switch (e.key) {
        case 'Escape':
        case 'Tab':
          e.preventDefault();
          e.stopPropagation();
          close(true);
          break;
        case 'ArrowDown': {
          e.preventDefault();
          e.stopPropagation();
          const n = (activeRef.current + 1) % count;
          setActive(n);
          focusItem(n);
          break;
        }
        case 'ArrowUp': {
          e.preventDefault();
          e.stopPropagation();
          const n = (activeRef.current - 1 + count) % count;
          setActive(n);
          focusItem(n);
          break;
        }
        case 'Home':
          e.preventDefault();
          e.stopPropagation();
          setActive(0);
          focusItem(0);
          break;
        case 'End':
          e.preventDefault();
          e.stopPropagation();
          setActive(count - 1);
          focusItem(count - 1);
          break;
        default:
          break;
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [mode, count, close, focusItem]);

  const showPreview = useCallback(() => {
    if (suppressPreviewRef.current) {
      suppressPreviewRef.current = false;
      return;
    }
    setMode((m) => (m === 'open' ? m : 'preview'));
  }, []);

  const hidePreview = useCallback(() => {
    setMode((m) => (m === 'preview' ? 'closed' : m));
  }, []);

  const toggleOpen = useCallback(() => {
    setActive(0);
    setMode((m) => (m === 'open' ? 'closed' : 'open'));
  }, []);

  const previewTitles = cases.slice(0, 5);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={mode === 'open'}
        aria-label={t('journey.cases_pill', { defaultValue: '{{count}} cases', count })}
        title={t('journey.cases_pill_title', {
          defaultValue: 'Guided cases that use this module - hover to preview, click to open',
        })}
        onMouseEnter={showPreview}
        onMouseLeave={hidePreview}
        onFocus={showPreview}
        onBlur={hidePreview}
        onClick={toggleOpen}
        className={clsx(
          'inline-flex shrink-0 items-center gap-0.5 rounded-md border px-1.5 py-1',
          'text-2xs font-semibold tabular-nums text-oe-blue transition-colors',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
          mode === 'open'
            ? 'border-oe-blue/50 bg-oe-blue/10'
            : 'border-oe-blue/25 bg-oe-blue/5 hover:border-oe-blue/50 hover:bg-oe-blue/10',
        )}
      >
        <GraduationCap size={11} strokeWidth={2} aria-hidden />
        {count}
        <ChevronDown
          size={10}
          strokeWidth={2}
          aria-hidden
          className={clsx('transition-transform', mode === 'open' && 'rotate-180')}
        />
      </button>

      {mode !== 'closed' &&
        layout &&
        createPortal(
          <div
            ref={popRef}
            style={{
              position: 'fixed',
              left: layout.left,
              width: CASES_POP_WIDTH,
              zIndex: 130,
              ...(layout.top != null ? { top: layout.top } : { bottom: layout.bottom ?? 0 }),
            }}
            className={clsx(mode === 'preview' && 'pointer-events-none')}
          >
            {mode === 'preview' ? (
              <div
                aria-hidden
                className="overflow-hidden rounded-lg border border-border-light bg-surface-elevated shadow-xl ring-1 ring-black/5"
              >
                <div className="flex items-center gap-1.5 border-b border-border-light/70 bg-surface-secondary/40 px-3 py-2">
                  <GraduationCap size={12} className="text-oe-blue" aria-hidden />
                  <span className="text-2xs font-semibold text-content-secondary">
                    {t('journey.cases_preview_title', { defaultValue: 'Guided cases' })}
                  </span>
                </div>
                <ul className="py-1">
                  {previewTitles.map((pb) => (
                    <li key={pb.id} className="truncate px-3 py-1 text-2xs text-content-primary">
                      {t(pb.titleKey, { defaultValue: pb.titleDefault })}
                    </li>
                  ))}
                </ul>
                <div className="border-t border-border-light/70 px-3 py-1.5 text-[10px] text-content-tertiary">
                  {count > previewTitles.length
                    ? t('journey.cases_more_hint', {
                        defaultValue: '+{{n}} more - click to open',
                        n: count - previewTitles.length,
                      })
                    : t('journey.cases_click_hint', { defaultValue: 'Click to open' })}
                </div>
              </div>
            ) : (
              <div
                role="menu"
                aria-label={t('journey.cases_menu_label', {
                  defaultValue: 'Cases that use this module',
                })}
                className="overflow-hidden rounded-lg border border-border-light bg-surface-elevated shadow-2xl ring-1 ring-black/5"
              >
                <div className="flex items-center gap-1.5 border-b border-border-light/70 bg-surface-secondary/40 px-3 py-2">
                  <GraduationCap size={12} className="text-oe-blue" aria-hidden />
                  <span className="text-2xs font-semibold text-content-secondary">
                    {t('journey.cases_menu_title', { defaultValue: 'Open a guided case' })}
                  </span>
                </div>
                <ul
                  className="overflow-y-auto py-1"
                  style={{ maxHeight: Math.max(96, layout.maxH - 44) }}
                >
                  {cases.map((pb, i) => (
                    <li key={pb.id} role="none">
                      <button
                        ref={(el) => {
                          itemRefs.current[i] = el;
                        }}
                        role="menuitem"
                        tabIndex={i === active ? 0 : -1}
                        type="button"
                        onClick={() => onOpenCase(pb.id)}
                        onMouseEnter={() => setActive(i)}
                        className="group flex w-full items-center gap-2 px-3 py-1.5 text-left text-2xs text-content-primary transition-colors hover:bg-oe-blue/5 focus:bg-oe-blue/10 focus:outline-none"
                      >
                        <span className="flex-1 truncate">
                          {t(pb.titleKey, { defaultValue: pb.titleDefault })}
                        </span>
                        <ArrowRight
                          size={11}
                          aria-hidden
                          className="shrink-0 text-oe-blue opacity-0 transition-opacity group-hover:opacity-70 group-focus:opacity-100"
                        />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}

/** True when ``pathname`` is on (or under) the module route ``to``. Normalises
 *  the pathname the same way phase detection does, so a project-scoped route
 *  (``/projects/<id>/finance``) highlights its chip instead of silently
 *  failing the equality test. */
function isOnRoute(pathname: string, to: string): boolean {
  const target = to.split('?')[0]!;
  const candidate = journeyRouteCandidate(pathname);
  return candidate === target || candidate.startsWith(target + '/');
}
