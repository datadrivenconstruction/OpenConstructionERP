// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
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
  PlayCircle,
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
  type JourneyPhase,
} from './projectJourneyData';
import { useModuleStore } from '@/stores/useModuleStore';
import { videoCountForRoute, videoRouteFor } from '@/features/videos/videoRoutes';
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
// The player and the academy catalogue load only when a step's video is opened.
const JourneyStepVideo = lazy(() => import('@/features/videos/JourneyStepVideo'));

/** True when the academy catalogue has a video walking any of the step's module routes. */
function phaseHasVideo(phase: JourneyPhase): boolean {
  return phase.modules.some((m) => {
    const route = videoRouteFor(m.to.split('?')[0]!);
    return route !== null && videoCountForRoute(route) > 0;
  });
}

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
    dot: 'bg-semantic-success',
    text: 'text-semantic-success',
    bar: 'bg-semantic-success',
    wash: 'from-emerald-500/[0.08]',
    glyph: 'text-semantic-success',
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

  // Routes of the step whose video is playing; the player owns Escape while it is up.
  const [videoRoutes, setVideoRoutes] = useState<readonly string[] | null>(null);
  const videoOpenRef = useRef(false);
  videoOpenRef.current = videoRoutes !== null;
  const closeVideo = useCallback(() => setVideoRoutes(null), []);

  // Close on Escape; focus the close button on open for keyboard users.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !videoOpenRef.current) onClose();
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

  const currentIndex = JOURNEY_PHASES.findIndex((p) => p.key === currentPhaseKey);
  const currentPhase = currentIndex >= 0 ? JOURNEY_PHASES[currentIndex] : undefined;
  const nextPhase = currentIndex >= 0 ? JOURNEY_PHASES[currentIndex + 1] : JOURNEY_PHASES[0];
  const total = JOURNEY_PHASES.length;
  // Global 1-based number for each phase, in lifecycle order.
  const phaseNumber = (key: string) => JOURNEY_PHASES.findIndex((p) => p.key === key) + 1;
  const phaseName = (p: JourneyPhase) => t(p.nameKey, { defaultValue: p.name });

  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const showPhase = useCallback((key: string) => {
    const el = cardRefs.current[key];
    el?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
    el?.focus({ preventScroll: true });
  }, []);

  // Render through a portal on document.body. The header and several page
  // shells create their own stacking contexts (sticky + isolate/transform),
  // which would otherwise trap this overlay *underneath* page content even at
  // a high z-index. A body-level portal escapes all of them, so the map always
  // paints on top of everything.
  return createPortal(
    <div className="fixed inset-0 z-modal flex items-center justify-center p-2 sm:p-6">
      {/* Light veil: the platform stays visible around the panel. */}
      <div
        className="fixed inset-0 bg-black/25 backdrop-blur-[3px] animate-fade-in dark:bg-black/45"
        onClick={onClose}
        aria-hidden
        data-testid="project-journey-backdrop"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('journey.title', { defaultValue: 'Your project journey' })}
        data-testid="project-journey-panel"
        className="relative flex max-h-[calc(100dvh-1rem)] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in sm:max-h-[calc(100dvh-3rem)]"
      >
        {/* ── Header ─────────────────────────────────────────────────── */}
        <div className="shrink-0 border-b border-border-light px-4 pb-3 pt-4 sm:px-5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-start gap-3">
              <span className="mt-0.5 hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue sm:flex">
                <RouteIcon size={20} strokeWidth={1.75} />
              </span>
              <div className="min-w-0">
                <h2 className="oe-section-title">{t('journey.title', { defaultValue: 'Your project journey' })}</h2>
                <p className="mt-0.5 text-xs leading-relaxed text-content-secondary">
                  {t('journey.subtitle', {
                    defaultValue:
                      'Every stage of a construction project, from first lead to handover, and where you are right now. Pick any step to jump there.',
                  })}
                </p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {/* One clear route from the map into the guided case library. */}
              <button
                type="button"
                onClick={() => go('/cases')}
                className="hidden h-8 shrink-0 items-center gap-1.5 rounded-lg border border-border bg-surface-primary px-3 text-xs font-medium text-content-primary transition-colors hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60 sm:inline-flex"
              >
                <GraduationCap size={14} strokeWidth={2} className="text-oe-blue" aria-hidden />
                {t('journey.browse_cases', { defaultValue: 'Browse cases' })}
              </button>
              <button
                ref={closeRef}
                type="button"
                onClick={onClose}
                aria-label={t('common.close', { defaultValue: 'Close' })}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
              >
                <X size={20} />
              </button>
            </div>
          </div>

          {/* ── Progress: every step on one line, the current one ringed ── */}
          <div className="mt-3">
            <div className="mb-1.5 flex items-center justify-between gap-2 text-2xs">
              <span className="font-semibold uppercase tracking-wide text-content-tertiary" data-testid="project-journey-progress">
                {currentPhase
                  ? t('journey.progress', { defaultValue: 'Step {{n}} of {{total}}', n: currentIndex + 1, total })
                  : t('journey.pick_a_step', { defaultValue: 'This screen sits outside the line. Pick a step to start.' })}
              </span>
              {currentPhase && (
                <span className="inline-flex min-w-0 items-center gap-1 font-medium text-oe-blue-text">
                  <MapPin size={12} className="shrink-0" aria-hidden />
                  <span className="truncate">{phaseName(currentPhase)}</span>
                </span>
              )}
            </div>
            <ol className="flex items-center gap-1 overflow-x-auto pb-1" aria-label={t('journey.title', { defaultValue: 'Your project journey' })}>
              {JOURNEY_PHASES.map((phase, i) => {
                const isCurrent = i === currentIndex;
                const isBehind = currentIndex >= 0 && i < currentIndex;
                const accent = ARC_ACCENT[phase.arc];
                return (
                  <li key={phase.key} className="flex min-w-[1.75rem] flex-1 items-center gap-1">
                    <button
                      type="button"
                      onClick={() => showPhase(phase.key)}
                      aria-current={isCurrent ? 'step' : undefined}
                      aria-label={t('journey.step_aria', {
                        defaultValue: 'Step {{n}}: {{phase}}',
                        n: i + 1,
                        phase: phaseName(phase),
                      })}
                      title={phaseName(phase)}
                      data-testid={`project-journey-node-${phase.key}`}
                      className={clsx(
                        'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-2xs font-semibold tabular-nums transition-colors',
                        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60 focus-visible:ring-offset-1',
                        isCurrent
                          ? 'bg-oe-blue text-white ring-4 ring-oe-blue/20'
                          : isBehind
                            ? clsx(accent.bar, 'text-white opacity-70 hover:opacity-100')
                            : 'border border-border bg-surface-primary text-content-secondary hover:border-oe-blue/50 hover:text-content-primary',
                      )}
                    >
                      {i + 1}
                    </button>
                    {i < total - 1 && (
                      <span
                        aria-hidden
                        className={clsx(
                          'h-0.5 min-w-[0.25rem] flex-1 rounded-full',
                          isBehind || isCurrent ? accent.bar : 'bg-border-light',
                          isCurrent && 'opacity-40',
                        )}
                      />
                    )}
                  </li>
                );
              })}
            </ol>
          </div>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4 sm:px-5">
          {/* ── You are here: the current step, what it is for, what is next ── */}
          {currentPhase && (
            <section
              data-testid="project-journey-current"
              className="flex flex-col gap-3 rounded-xl border border-oe-blue/40 bg-gradient-to-br from-oe-blue/[0.08] to-transparent p-4 sm:flex-row sm:items-center"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue text-white">
                <currentPhase.icon size={20} strokeWidth={1.75} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-2xs font-semibold uppercase tracking-wide text-oe-blue-text">
                  {t('journey.you_are_here_named', {
                    defaultValue: 'You are here: {{phase}}',
                    phase: t('journey.progress', { defaultValue: 'Step {{n}} of {{total}}', n: currentIndex + 1, total }),
                  })}
                </p>
                <h3 className="text-base font-semibold text-content-primary">{phaseName(currentPhase)}</h3>
                <p className="mt-0.5 text-xs leading-relaxed text-content-secondary">
                  {t(currentPhase.descKey, { defaultValue: currentPhase.desc })}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                {phaseHasVideo(currentPhase) && (
                  <button
                    type="button"
                    onClick={() => setVideoRoutes(currentPhase.modules.map((m) => m.to))}
                    data-testid="project-journey-video"
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface-primary px-3 text-xs font-medium text-content-primary transition-colors hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60"
                  >
                    <PlayCircle size={16} className="text-oe-blue" aria-hidden />
                    {t('journey.watch_video', { defaultValue: 'Watch a short video' })}
                  </button>
                )}
                {nextPhase && (
                  <button
                    type="button"
                    onClick={() => showPhase(nextPhase.key)}
                    data-testid="project-journey-next"
                    className="inline-flex h-8 min-w-0 items-center gap-1.5 rounded-lg bg-oe-blue px-3 text-xs font-medium text-white transition-colors hover:bg-oe-blue-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60 focus-visible:ring-offset-1"
                  >
                    <span className="truncate">
                      {t('journey.next_step', { defaultValue: 'Next: {{phase}}', phase: phaseName(nextPhase) })}
                    </span>
                    <ArrowRight size={14} className="shrink-0 rtl:rotate-180" aria-hidden />
                  </button>
                )}
              </div>
            </section>
          )}

          {/* ── Arcs and phases ────────────────────────────────────────── */}
          {JOURNEY_ARCS.map((arc) => {
            const accent = ARC_ACCENT[arc.key];
            const phases = JOURNEY_PHASES.filter((p) => p.arc === arc.key);
            return (
              <section key={arc.key} aria-label={t(arc.nameKey, { defaultValue: arc.name })}>
                <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className={clsx('h-2 w-2 shrink-0 rounded-full', accent.dot)} aria-hidden />
                  <h3 className={clsx('text-xs font-semibold uppercase tracking-wider', accent.text)}>
                    {t(arc.nameKey, { defaultValue: arc.name })}
                  </h3>
                  <span className="text-2xs text-content-tertiary">
                    {t(arc.descKey, { defaultValue: arc.desc })}
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {phases.map((phase) => {
                    const Icon: LucideIcon = phase.icon;
                    const isCurrent = phase.key === currentPhaseKey;
                    const num = phaseNumber(phase.key);
                    const hasVideo = phaseHasVideo(phase);
                    return (
                      <div
                        key={phase.key}
                        ref={(el) => {
                          cardRefs.current[phase.key] = el;
                        }}
                        tabIndex={-1}
                        data-testid={`project-journey-phase-${phase.key}`}
                        className={clsx(
                          'relative flex scroll-m-4 flex-col overflow-hidden rounded-xl border p-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60',
                          'bg-gradient-to-br to-surface-primary transition-shadow',
                          isCurrent
                            ? 'border-oe-blue from-oe-blue/[0.12] ring-1 ring-oe-blue/30'
                            : clsx('border-border-light hover:shadow-sm', accent.wash),
                        )}
                      >
                        {/* Themed watermark: the phase's own icon, oversized and
                            barely-there, clipped to the card corner. */}
                        <Icon
                          size={104}
                          strokeWidth={1}
                          aria-hidden
                          className={clsx(
                            'pointer-events-none absolute -bottom-6 -end-5 z-0',
                            isCurrent ? 'text-oe-blue opacity-[0.10]' : clsx(accent.glyph, 'opacity-[0.07]'),
                          )}
                        />
                        <div className="relative z-10 flex flex-1 flex-col">
                          <div className="flex items-center gap-2">
                            <span
                              className={clsx(
                                'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                                isCurrent ? 'bg-oe-blue text-white' : 'bg-surface-tertiary text-content-secondary',
                              )}
                            >
                              <Icon size={16} strokeWidth={1.75} />
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-1.5">
                                <span className="text-2xs font-semibold tabular-nums text-content-tertiary">{num}</span>
                                <h4
                                  className={clsx(
                                    'truncate text-sm font-semibold',
                                    isCurrent ? 'text-oe-blue-text' : 'text-content-primary',
                                  )}
                                >
                                  {phaseName(phase)}
                                </h4>
                              </div>
                            </div>
                            {hasVideo && (
                              <button
                                type="button"
                                onClick={() => setVideoRoutes(phase.modules.map((m) => m.to))}
                                aria-label={t('journey.watch_video_for', {
                                  defaultValue: 'Watch a short video: {{phase}}',
                                  phase: phaseName(phase),
                                })}
                                title={t('journey.watch_video', { defaultValue: 'Watch a short video' })}
                                data-testid={`project-journey-video-${phase.key}`}
                                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-oe-blue transition-colors hover:bg-oe-blue/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60"
                              >
                                <PlayCircle size={16} aria-hidden />
                              </button>
                            )}
                            {isCurrent && (
                              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-oe-blue/10 px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide text-oe-blue-text">
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
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-semantic-warning/15 text-semantic-warning">
                <Sparkles size={16} strokeWidth={1.75} />
              </span>
              <h3 className="oe-overline">
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

          {/* The cases link moves into the scroll on a phone, where the header has no room. */}
          <button
            type="button"
            onClick={() => go('/cases')}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface-primary px-3 text-xs font-medium text-content-primary transition-colors hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60 sm:hidden"
          >
            <GraduationCap size={14} strokeWidth={2} className="text-oe-blue" aria-hidden />
            {t('journey.browse_cases', { defaultValue: 'Browse cases' })}
          </button>
        </div>
      </div>
      {videoRoutes && (
        <Suspense fallback={null}>
          <JourneyStepVideo routes={videoRoutes} onClose={closeVideo} />
        </Suspense>
      )}
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
        size={12}
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
        <GraduationCap size={12} strokeWidth={2} aria-hidden />
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
                <div className="border-t border-border-light/70 px-3 py-1.5 text-2xs text-content-tertiary">
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
                          size={12}
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
