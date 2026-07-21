// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * MatchWizard — linear 1→2→3→4 entry flow for /match-elements.
 *
 * Design intent: feel like an Apple-team product page — generous
 * whitespace, soft gradients, subtle depth, micro-interactions, a single
 * unmistakable primary CTA. The wizard replaces the previous "everything
 * scattered, settings hidden until after a session is created" layout
 * that Artem reported as "ничего не работает".
 *
 * Flow:
 *   1. Stage      — what phase of work am I matching?
 *   2. Catalogue  — which CWICR rate book?
 *   3. Source     — BIM model / Excel BoQ / pasted text
 *   4. Review     — confirm + Run (creates session + fires vector match)
 *
 * After Run the user is dropped into the existing results UI via the
 * onComplete(sessionId) callback. Resume path: existing sessions are
 * surfaced on Step 1 so power users can skip the wizard entirely.
 */

import { useState, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { CountryFlag, originFlagCode } from '@/shared/ui';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Box,
  Building2,
  Cable,
  Check,
  Database,
  DoorOpen,
  Download,
  FileSpreadsheet,
  FileText,
  FileType,
  Hammer,
  Image as ImageIcon,
  Layers,
  Loader2,
  Mountain,
  Paintbrush,
  PlayCircle,
  Sofa,
  Sparkles,
  SquareStack,
  Target,
  TreePine,
  Wrench,
} from 'lucide-react';
import { useCatalogueInstallStore } from '@/stores/useCatalogueInstallStore';
import clsx from 'clsx';
import {
  matchElementsApi,
  type ConstructionStage,
  type BIMModelOption,
  type SessionSummary,
  type TextInput,
} from './api';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { unwrapCataloguesPayload } from './catalogues-payload';
import ImageSourceSelector from './ImageSourceSelector';

/* ── Types ─────────────────────────────────────────────────────────────── */

type Source =
  | { kind: 'bim'; modelId: string; modelName: string }
  | { kind: 'excel'; file: File }
  | { kind: 'pdf'; file: File }
  | { kind: 'image'; file: File }
  | { kind: 'text'; lines: string[] };

interface CatalogueRow {
  region: string;
  country_iso: string;
  city: string;
  language: string;
  currency: string;
  install_status: string;
  size_mb: number;
}

interface Props {
  projectId: string;
  projectRegion: string | null;
  sessions: SessionSummary[];
  /** Called the moment the session has been created and the run-match
   *  POST has been *kicked off* (not awaited). The parent mounts
   *  MatchProgressCard immediately so the user sees the timeline; the
   *  wizard continues to await the matcher in the background and
   *  reports the outcome via ``onMatchSuccess`` / ``onMatchError``.
   *
   *  ``abortController`` (when supplied) feeds the in-flight run-match
   *  fetch — the parent stores it so the progress card's Cancel button
   *  can abort the request without the user refreshing the tab. The
   *  argument is optional only for back-compat with callers built
   *  before the cancel affordance landed. */
  onComplete: (sessionId: string, abortController?: AbortController) => void;
  /** Called once the background run-match POST resolves successfully —
   *  the page flips MatchProgressCard to ``status='done'`` and the
   *  card hands over to the results pane. */
  onMatchSuccess?: (sessionId: string) => void;
  /** Called when the background run-match POST fails — the page flips
   *  MatchProgressCard to ``status='error'`` with this message and
   *  shows the "Try again" button. */
  onMatchError?: (sessionId: string, message: string) => void;
  /** Called when the user picks an existing session from the Resume
   *  strip — distinct from ``onComplete`` because no match is being
   *  kicked off, so the parent should NOT mount the progress card.
   *  Defaults to ``onComplete`` for callers that don't care. */
  onResume?: (sessionId: string) => void;
}

/* ── Stepper (numbered circles + connector lines) ──────────────────────── */

function Stepper({
  current,
  onJump,
}: {
  current: 1 | 2 | 3 | 4;
  onJump: (n: 1 | 2 | 3 | 4) => void;
}) {
  const { t } = useTranslation();
  const labels: Record<1 | 2 | 3 | 4, string> = {
    1: t('match_wizard.pill_stage', 'Stage'),
    2: t('match_wizard.pill_catalogue', 'Catalogue'),
    3: t('match_wizard.pill_source', 'Source'),
    4: t('match_wizard.pill_run', 'Run & review'),
  };
  return (
    // Bigger circles + always-visible labels + thicker connector lines.
    // Earlier compact version was barely legible against the wider page;
    // this version reads as a real progress indicator at a glance.
    <ol className="flex items-center justify-center gap-0 sm:gap-2 pt-8 pb-10 select-none">
      {([1, 2, 3, 4] as const).map((n, idx) => {
        const isCurrent = n === current;
        const isDone = n < current;
        const reachable = n <= current;
        return (
          <li key={n} className="flex items-center">
            <button
              type="button"
              onClick={reachable ? () => onJump(n) : undefined}
              disabled={!reachable}
              className={clsx(
                'group flex items-center gap-2.5 transition-all duration-300',
                reachable && 'cursor-pointer',
                !reachable && 'cursor-not-allowed',
              )}
              aria-current={isCurrent ? 'step' : undefined}
              aria-label={`${labels[n]}${
                isDone
                  ? ` - ${t('common.done', 'done')}`
                  : isCurrent
                    ? ` - ${t('common.current', 'current')}`
                    : ''
              }`}
            >
              <span
                className={clsx(
                  'w-11 h-11 rounded-full flex items-center justify-center text-base font-bold transition-all duration-300',
                  isCurrent &&
                    'bg-gradient-to-br from-indigo-500 to-indigo-700 text-white shadow-lg shadow-indigo-500/40 ring-4 ring-indigo-100 dark:ring-indigo-900/40 scale-110',
                  isDone &&
                    'bg-emerald-500 text-white shadow-md shadow-emerald-500/40',
                  !isCurrent && !isDone &&
                    'bg-surface-secondary text-content-tertiary border-2 border-border',
                )}
              >
                {isDone ? <Check className="w-5 h-5" strokeWidth={3} /> : n}
              </span>
              <span
                className={clsx(
                  'text-sm sm:text-base transition-colors duration-300',
                  isCurrent && 'font-semibold text-content-primary',
                  isDone && 'text-content-secondary font-medium',
                  !isCurrent && !isDone && 'text-content-tertiary hidden sm:inline',
                )}
              >
                {labels[n]}
              </span>
            </button>
            {idx < 3 && (
              <span
                className={clsx(
                  'mx-3 sm:mx-4 h-0.5 w-10 sm:w-16 rounded-full transition-colors duration-300',
                  n < current
                    ? 'bg-emerald-400 dark:bg-emerald-600'
                    : 'bg-border',
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

/* ── SelectableTile (the Apple-y card used across all steps) ───────────── */

function SelectableTile({
  selected,
  disabled,
  onClick,
  children,
  className,
}: {
  selected: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'group relative text-left rounded-2xl px-4 py-3.5 transition-all duration-200',
        'border bg-surface-primary',
        selected
          ? 'border-indigo-500/60 bg-gradient-to-br from-indigo-50 to-white dark:from-indigo-950/40 dark:to-surface-primary shadow-md shadow-indigo-500/10 ring-1 ring-indigo-500/20'
          : 'border-border-light hover:border-indigo-300 dark:hover:border-indigo-800 hover:shadow-md hover:shadow-content-quaternary/5 hover:-translate-y-px',
        disabled && 'opacity-40 cursor-not-allowed pointer-events-none',
        className,
      )}
    >
      {selected && (
        <span className="absolute top-2.5 right-2.5 w-5 h-5 rounded-full bg-indigo-600 text-white flex items-center justify-center shadow-sm shadow-indigo-500/40">
          <Check className="w-3 h-3" strokeWidth={3} />
        </span>
      )}
      {children}
    </button>
  );
}

/* ── Step 1: Stage ─────────────────────────────────────────────────────── */

/**
 * Stage visual catalogue.
 *
 * Six "hero" stages get treated as pictorial cards because they cover the
 * vast majority of real construction work — Foundations / Superstructure /
 * Envelope / MEP / Interior / Finishes. The remaining six stages
 * (Demolition, Earthwork, Substructure, Fixed Furnishings, Equipment,
 * Sitework) appear below as a compact icon strip — they're real options
 * but rarely the primary phase someone matches against.
 *
 * Per-stage gradient / accent colours follow OmniClass intuition: cool
 * tones for structural / earth phases, warm for finishes / interior. Icons
 * are deliberately one-shape-per-stage so the user starts to recognise
 * them across sessions.
 */
const STAGE_HERO: ConstructionStage[] = [
  '04_Foundations',
  '06_Superstructure',
  '07_Envelope',
  '09_MEP',
  '08_Interior',
  '10_Finishes',
];
const STAGE_OTHER: ConstructionStage[] = [
  '02_Demolition',
  '03_Earthwork',
  '05_Substructure',
  '11_FixedFurnishings',
  '12_Equipment',
  '13_Sitework',
];

const STAGE_VISUALS: Record<
  ConstructionStage,
  { Icon: typeof Layers; tint: string; iconBg: string; defaultBlurb: string }
> = {
  '02_Demolition': {
    Icon: Hammer,
    tint: 'from-rose-500/10 to-transparent',
    iconBg: 'bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-200',
    defaultBlurb: 'Strip-out, deconstruction, hazmat removal.',
  },
  '03_Earthwork': {
    Icon: Mountain,
    tint: 'from-amber-500/10 to-transparent',
    iconBg: 'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-200',
    defaultBlurb: 'Excavation, fill, grading, dewatering.',
  },
  '04_Foundations': {
    Icon: Layers,
    tint: 'from-stone-500/10 to-transparent',
    iconBg: 'bg-stone-200 text-stone-800 dark:bg-stone-800/60 dark:text-stone-100',
    defaultBlurb: 'Footings, piles, pile caps, slab-on-grade.',
  },
  '05_Substructure': {
    Icon: Box,
    tint: 'from-slate-500/10 to-transparent',
    iconBg: 'bg-slate-200 text-slate-800 dark:bg-slate-800/60 dark:text-slate-100',
    defaultBlurb: 'Basement walls, lower-level slabs, retaining structures.',
  },
  '06_Superstructure': {
    Icon: Building2,
    tint: 'from-blue-500/10 to-transparent',
    iconBg: 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-200',
    defaultBlurb: 'Frame, columns, beams, floors, roof structure.',
  },
  '07_Envelope': {
    Icon: SquareStack,
    tint: 'from-sky-500/10 to-transparent',
    iconBg: 'bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-200',
    defaultBlurb: 'Facade, curtain wall, roof, glazing, insulation.',
  },
  '08_Interior': {
    Icon: DoorOpen,
    tint: 'from-violet-500/10 to-transparent',
    iconBg: 'bg-violet-100 text-violet-700 dark:bg-violet-950/40 dark:text-violet-200',
    defaultBlurb: 'Partitions, doors, ceilings, internal stairs.',
  },
  '09_MEP': {
    Icon: Cable,
    tint: 'from-orange-500/10 to-transparent',
    iconBg: 'bg-orange-100 text-orange-700 dark:bg-orange-950/40 dark:text-orange-200',
    defaultBlurb: 'Mechanical, electrical, plumbing, HVAC, fire.',
  },
  '10_Finishes': {
    Icon: Paintbrush,
    tint: 'from-emerald-500/10 to-transparent',
    iconBg: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200',
    defaultBlurb: 'Plaster, paint, flooring, tiling, joinery.',
  },
  '11_FixedFurnishings': {
    Icon: Sofa,
    tint: 'from-pink-500/10 to-transparent',
    iconBg: 'bg-pink-100 text-pink-700 dark:bg-pink-950/40 dark:text-pink-200',
    defaultBlurb: 'Built-in cabinetry, fixed seating, casework.',
  },
  '12_Equipment': {
    Icon: Wrench,
    tint: 'from-zinc-500/10 to-transparent',
    iconBg: 'bg-zinc-200 text-zinc-800 dark:bg-zinc-800/60 dark:text-zinc-100',
    defaultBlurb: 'Process / lab / kitchen / specialty equipment.',
  },
  '13_Sitework': {
    Icon: TreePine,
    tint: 'from-green-500/10 to-transparent',
    iconBg: 'bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-200',
    defaultBlurb: 'Paving, landscaping, fences, site utilities.',
  },
};

function StageStep({
  selected,
  onPick,
  sessions,
  onResume,
}: {
  selected: ConstructionStage | '';
  onPick: (s: ConstructionStage | '') => void;
  sessions: SessionSummary[];
  onResume: (sessionId: string) => void;
}) {
  const { t } = useTranslation();

  const labelFor = (s: ConstructionStage) =>
    t(`match_elements.stage.${s}`, s.replace(/^\d+_/, ''));
  const blurbFor = (s: ConstructionStage) =>
    t(`match_wizard.stage_blurb.${s}`, STAGE_VISUALS[s].defaultBlurb);

  return (
    <div className="animate-[wizard-fade_300ms_ease-out]">
      <header className="mb-6">
        <p className="text-xs uppercase tracking-[0.14em] text-indigo-600 dark:text-indigo-400 font-semibold mb-1.5">
          {t('match_wizard.step1_eyebrow', 'Step 1')}
        </p>
        <h2 className="text-2xl font-semibold tracking-tight text-content-primary mb-1.5">
          {t('match_wizard.step1_title', 'What stage are you matching?')}
        </h2>
        <p className="text-sm text-content-secondary leading-relaxed max-w-2xl">
          {t(
            'match_wizard.step1_help',
            'Pinning a phase narrows BIM elements and catalogue rates to that work. Pick "Any stage" to search across the whole project.',
          )}
        </p>
      </header>

      {/* "Any stage" — full-width skip lane sitting above the hero grid.
          Keeps the most common power-user choice ("just match everything")
          visually distinct from the per-stage picks instead of burying it
          as the first cell of a 12-tile grid. */}
      <button
        type="button"
        onClick={() => onPick('')}
        className={clsx(
          'group w-full mb-5 rounded-2xl border px-5 py-3.5 text-left transition-all duration-200 flex items-center gap-3',
          selected === ''
            ? 'border-indigo-500/60 bg-gradient-to-r from-indigo-50 to-white dark:from-indigo-950/40 dark:to-surface-primary shadow-md shadow-indigo-500/10 ring-1 ring-indigo-500/20'
            : 'border-border-light bg-surface-primary hover:border-indigo-300 dark:hover:border-indigo-800 hover:shadow-sm hover:-translate-y-px',
        )}
        aria-pressed={selected === ''}
      >
        <span
          className={clsx(
            'shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-colors',
            selected === ''
              ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-500/30'
              : 'bg-surface-secondary text-content-tertiary group-hover:bg-indigo-100 group-hover:text-indigo-700 dark:group-hover:bg-indigo-950/40 dark:group-hover:text-indigo-200',
          )}
        >
          <Sparkles className="w-4 h-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-sm text-content-primary">
            {t('match_elements.stage_any', 'Any stage')}
          </div>
          <div className="text-xs text-content-tertiary mt-0.5">
            {t(
              'match_wizard.stage_any_help',
              'Match across the whole project - no phase filter applied.',
            )}
          </div>
        </div>
        {selected === '' && (
          <Check className="w-5 h-5 text-indigo-600 shrink-0" strokeWidth={3} />
        )}
      </button>

      {/* Hero grid — six dominant phases as visual cards. 1 / 2 / 3 cols at
          phone / tablet / desktop so each card stays comfortably touchable
          without ever falling below readable text size. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-6">
        {STAGE_HERO.map((s) => {
          const v = STAGE_VISUALS[s];
          const isSel = selected === s;
          const Icon = v.Icon;
          return (
            <button
              key={s}
              type="button"
              onClick={() => onPick(s)}
              aria-pressed={isSel}
              className={clsx(
                'group relative overflow-hidden text-left rounded-2xl border p-4 transition-all duration-200',
                'bg-surface-primary',
                isSel
                  ? 'border-indigo-500/60 shadow-md shadow-indigo-500/15 ring-1 ring-indigo-500/25'
                  : 'border-border-light hover:border-indigo-300 dark:hover:border-indigo-800 hover:shadow-md hover:-translate-y-0.5',
              )}
            >
              {/* Per-stage gradient corner accent — soft, never competes
                  with the active-state ring. Sits behind the content with
                  pointer-events disabled so clicks always hit the button. */}
              <div
                aria-hidden
                className={clsx(
                  'pointer-events-none absolute -top-8 -right-8 w-32 h-32 rounded-full blur-2xl opacity-70 transition-opacity duration-300',
                  'bg-gradient-to-br',
                  v.tint,
                  'group-hover:opacity-100',
                )}
              />
              {isSel && (
                <span className="absolute top-3 right-3 w-5 h-5 rounded-full bg-indigo-600 text-white flex items-center justify-center shadow-sm shadow-indigo-500/40 z-10">
                  <Check className="w-3 h-3" strokeWidth={3} />
                </span>
              )}
              <div className={clsx('relative w-11 h-11 rounded-xl flex items-center justify-center mb-3', v.iconBg)}>
                <Icon className="w-5 h-5" strokeWidth={1.75} />
              </div>
              <div className="relative font-semibold text-sm text-content-primary mb-1 pr-7">
                {labelFor(s)}
              </div>
              <div className="relative text-xs text-content-tertiary leading-snug line-clamp-2">
                {blurbFor(s)}
              </div>
            </button>
          );
        })}
      </div>

      {/* Compact strip — less common phases. Icon-led so the user can
          scan visually; full label sits next to the icon so nothing is
          lost behind a tooltip. Wraps freely on narrow widths. */}
      <div className="text-[11px] uppercase tracking-[0.14em] text-content-tertiary font-semibold mb-2">
        {t('match_wizard.stage_other_label', 'Other phases')}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {STAGE_OTHER.map((s) => {
          const v = STAGE_VISUALS[s];
          const isSel = selected === s;
          const Icon = v.Icon;
          return (
            <button
              key={s}
              type="button"
              onClick={() => onPick(s)}
              aria-pressed={isSel}
              title={blurbFor(s)}
              className={clsx(
                'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all duration-200',
                isSel
                  ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-500/30 ring-1 ring-indigo-400/40'
                  : 'bg-surface-secondary text-content-secondary border border-border-light hover:border-indigo-300 dark:hover:border-indigo-800 hover:text-content-primary hover:shadow-sm',
              )}
            >
              <Icon className="w-3.5 h-3.5" strokeWidth={1.75} />
              {labelFor(s)}
            </button>
          );
        })}
      </div>

      {sessions.length > 0 && (
        <div className="mt-7 rounded-2xl bg-gradient-to-br from-amber-50 to-white dark:from-amber-950/20 dark:to-surface-primary border border-amber-200/60 dark:border-amber-800/40 p-4">
          <div className="text-xs font-semibold text-amber-900 dark:text-amber-100 mb-2 inline-flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5" />
            {t('match_wizard.resume_title', 'Resume a saved session')}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {sessions.slice(0, 6).map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => onResume(s.id)}
                className="text-xs px-2.5 py-1 rounded-full bg-white dark:bg-surface-primary border border-amber-300/60 dark:border-amber-700/40 hover:bg-amber-50 dark:hover:bg-amber-900/20 text-amber-900 dark:text-amber-100 shadow-sm transition-all hover:shadow-md hover:-translate-y-px"
                title={s.id}
              >
                {s.name || s.id.slice(0, 8)}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Step 2: Catalogue ─────────────────────────────────────────────────── */

// Exported so the P0-2 regression suite (no-catalogue banner +
// blocked-gate contract) can mount it in isolation without driving the
// full 4-step wizard. Production code keeps using it through
// ``MatchWizard``.
export function CatalogueStep({
  projectRegion,
  selected,
  onPick,
}: {
  projectRegion: string | null;
  selected: string | null;
  onPick: (region: string | null) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { addToast } = useToastStore();
  const installJobs = useCatalogueInstallStore((s) => s.jobs);
  const startInstall = useCatalogueInstallStore((s) => s.startInstall);
  // Active or just-completed installs need an aggressive refetch cadence
  // so the UI reflects backend reality within a couple of seconds — the
  // 8 s "ambient" interval otherwise leaves the user staring at a card
  // that's already been promoted to "loaded" on the server.
  const hasLiveJob = useMemo(() => {
    for (const j of installJobs.values()) {
      if (j.status === 'downloading' || j.status === 'ready') return true;
    }
    return false;
  }, [installJobs]);
  const cataloguesQ = useQuery({
    queryKey: ['catalogues-v3'],
    queryFn: async () => {
      const token = useAuthStore.getState().accessToken;
      const res = await fetch('/api/v1/costs/catalogues-v3/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`catalogues-v3 ${res.status}`);
      return res.json();
    },
    staleTime: 60_000,
    refetchInterval: hasLiveJob ? 2_000 : 8_000,
  });

  const all = useMemo<CatalogueRow[]>(
    () => unwrapCataloguesPayload(cataloguesQ.data) as CatalogueRow[],
    [cataloguesQ.data],
  );
  const installed = useMemo(() => all.filter((c) => c.install_status === 'loaded'), [all]);
  const available = useMemo(() => all.filter((c) => c.install_status === 'available'), [all]);

  // P0-2: when ``installed`` is empty there is nothing to auto-select,
  // and the wizard's Next gate stays blocked on Step 2 → Step 3 (see
  // ``canNext`` further down: ``step === 2 ? catalogueId !== null``).
  // The previous banner buried the recovery path inside a paragraph
  // pointing at the "floating dock at the bottom-right" — but the dock
  // only renders AFTER an install has been started, so an installer-
  // less user staring at this page saw no actionable widget. The
  // explicit "Install a catalogue first" banner below + scroll-to-list
  // button surfaces the recovery directly.
  useEffect(() => {
    if (selected) return;
    if (installed.length === 0) return;
    if (!projectRegion) {
      // No region hint? Auto-pick the first installed catalogue so the
      // gate unblocks. Better to default than to silently strand the
      // user on Step 2 with no actionable feedback.
      onPick(installed[0]!.region);
      return;
    }
    const prefix = projectRegion.slice(0, 2).toUpperCase();
    const match = installed.find((c) => c.region.startsWith(prefix)) ||
                  installed[0];
    if (match) onPick(match.region);
  }, [installed, projectRegion, selected, onPick]);

  // Anchor the "Install a catalogue first" banner's CTA so it scrolls
  // the user to the available-to-install grid below. The banner CTA
  // can't open the floating progress dock directly (the dock only
  // surfaces in-flight + completed jobs), so we surface the closest
  // actionable target: the list of installable catalogues.
  const availableAnchorRef = useRef<HTMLDivElement | null>(null);
  const scrollToAvailable = () => {
    availableAnchorRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
  };

  // Watch jobs flipping to 'ready'. As soon as one completes, kick the
  // catalogues query immediately (don't wait for the polling tick) and
  // auto-select the catalogue if the user hadn't picked one yet — that
  // way "click Install → wait → catalogue is picked & green" feels
  // continuous instead of "Install button vanishes, nothing happens".
  useEffect(() => {
    let dirty = false;
    const justReady: string[] = [];
    for (const j of installJobs.values()) {
      if (j.status === 'ready') {
        dirty = true;
        justReady.push(j.region);
      }
    }
    if (!dirty) return;
    void queryClient.invalidateQueries({ queryKey: ['catalogues-v3'] });
    // If the user hadn't picked anything yet, prefer the most recently
    // installed region. If they had picked an "available" one, switch
    // them to it now that it's actually usable.
    const pendingPick =
      !selected || installJobs.get(selected)?.status === 'ready';
    if (pendingPick && justReady.length > 0) {
      const last = justReady[justReady.length - 1];
      if (last) onPick(last);
    }
  }, [installJobs, queryClient, selected, onPick]);

  return (
    <div className="animate-[wizard-fade_300ms_ease-out]">
      <header className="mb-6">
        <p className="text-xs uppercase tracking-[0.14em] text-indigo-600 dark:text-indigo-400 font-semibold mb-1.5">
          {t('match_wizard.step2_eyebrow', 'Step 2')}
        </p>
        <h2 className="text-2xl font-semibold tracking-tight text-content-primary mb-1.5">
          {t('match_wizard.step2_title', 'Choose the cost catalogue')}
        </h2>
        <p className="text-sm text-content-secondary leading-relaxed max-w-2xl">
          {t(
            'match_wizard.step2_help',
            'Each catalogue is a vector index of priced positions - talk to it in plain language ("reinforced concrete wall 24cm", "ELT cable tray", "DN200 steel pipe") and it returns the closest rate-book lines, regardless of exact wording or language. Rates are sourced from the regional book; switch if you want rates from elsewhere.',
          )}
        </p>
        {/* Reinforces the "vector / semantic" angle with a small, scannable
            chip strip — the prose paragraph above gets skimmed; the chips
            tell the user at a glance what makes this step different from
            a plain dropdown of price lists. */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300 border border-indigo-200/60 dark:border-indigo-800/40">
            <Sparkles className="w-3 h-3" />
            {t('match_wizard.step2_chip_semantic', 'Semantic search')}
          </span>
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200/60 dark:border-emerald-800/40">
            <Database className="w-3 h-3" />
            {t('match_wizard.step2_chip_bgem3', 'BGE-M3 embeddings')}
          </span>
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-surface-secondary text-content-secondary border border-border-light">
            {t('match_wizard.step2_chip_lang', 'Plain-language queries')}
          </span>
        </div>
      </header>

      {cataloguesQ.isLoading && (
        <div className="flex items-center gap-2 text-sm text-content-tertiary py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          {t('match_wizard.loading_catalogues', 'Loading catalogues…')}
        </div>
      )}

      {!cataloguesQ.isLoading && installed.length === 0 && (
        <div
          data-testid="no-catalogue-banner"
          className="rounded-2xl border-2 border-amber-300/70 dark:border-amber-700/50 bg-gradient-to-br from-amber-50 to-white dark:from-amber-950/30 dark:to-surface-primary p-5 mb-4"
          role="alert"
        >
          <div className="flex items-start gap-3">
            <span className="shrink-0 w-9 h-9 rounded-xl bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-200 inline-flex items-center justify-center">
              <AlertTriangle className="w-4 h-4" />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="text-sm font-bold text-amber-900 dark:text-amber-100">
                {t(
                  'match_wizard.no_installed_title',
                  'Install a catalogue first',
                )}
              </h3>
              <p className="text-xs text-amber-800/90 dark:text-amber-200/80 mt-1 leading-relaxed">
                {t(
                  'match_wizard.no_installed_body',
                  'A cost catalogue is the vector index your project elements are matched against. You can\'t move past this step until at least one is installed. Pick the closest regional book below - installs run in the background, the wizard keeps your picks.',
                )}
              </p>
              <button
                type="button"
                data-testid="no-catalogue-install-cta"
                onClick={scrollToAvailable}
                disabled={available.length === 0}
                className={clsx(
                  'mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all',
                  'bg-gradient-to-br from-amber-500 to-orange-600 text-white',
                  'shadow-sm shadow-amber-500/25 hover:shadow-md hover:shadow-amber-500/35 hover:-translate-y-px',
                  'disabled:opacity-60 disabled:shadow-none disabled:translate-y-0 disabled:cursor-not-allowed',
                )}
              >
                <Download className="w-3.5 h-3.5" />
                {t(
                  'match_wizard.no_installed_cta',
                  'Choose a catalogue to install',
                )}
              </button>
              {available.length === 0 && (
                <p className="mt-2 text-[11px] text-amber-700/80 dark:text-amber-300/70">
                  {t(
                    'match_wizard.no_installed_no_available',
                    'No catalogues are available from the server. Check the Qdrant / costs registry status.',
                  )}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {installed.length > 0 && (
        <>
          <div className="text-[11px] uppercase tracking-[0.14em] text-content-tertiary font-semibold mb-3">
            {t('match_wizard.installed_label', 'Installed')}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2.5 mb-5">
            {installed.map((c) => (
              <SelectableTile
                key={c.region}
                selected={selected === c.region}
                onClick={() => onPick(c.region)}
              >
                <div className="font-medium text-sm text-content-primary mb-0.5 pr-7">
                  {c.country_iso} · {c.city}
                </div>
                <div className="text-[11px] text-content-tertiary">
                  {c.language?.toUpperCase()} · {c.currency} · {c.size_mb} MB
                </div>
              </SelectableTile>
            ))}
          </div>
        </>
      )}

      {available.length > 0 && (
        <>
          <div
            ref={availableAnchorRef}
            data-testid="catalogues-available-anchor"
            className="text-[11px] uppercase tracking-[0.14em] text-content-tertiary font-semibold mb-3 mt-2 scroll-mt-20"
          >
            {t('match_wizard.available_label', 'Available to install ({{n}})', {
              n: available.length,
            })}
          </div>
          {/* Region-prefix sort: surface a project-matching region first
              so the most likely install is at the top — matches the
              advisor's "Best" pick logic without a separate badge to
              keep the wizard density down. */}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
            {[...available]
              .sort((a, b) => {
                const prefix = (projectRegion || '').slice(0, 2).toUpperCase();
                const aMatch = prefix && a.region.startsWith(prefix) ? 1 : 0;
                const bMatch = prefix && b.region.startsWith(prefix) ? 1 : 0;
                return bMatch - aMatch;
              })
              .map((c) => {
                const job = installJobs.get(c.region);
                const isInstalling = job?.status === 'downloading';
                const isFailed = job?.status === 'error';
                // 'ready' but still in `available` means the install POST
                // returned ok but the next catalogues-v3 refetch hasn't
                // run yet (or the server-side post-probe didn't see the
                // collection). Show as "Finalizing…" instead of flipping
                // the button back to "Install" — that's exactly the
                // "downloads then resets" symptom Artem flagged.
                const isFinalizing = job?.status === 'ready';
                return (
                  <div
                    key={c.region}
                    className={clsx(
                      'rounded-2xl border p-3 transition-colors',
                      'border-border-light bg-surface-primary',
                      (isInstalling || isFinalizing) &&
                        'border-emerald-300 dark:border-emerald-700 bg-emerald-50/40 dark:bg-emerald-950/20',
                      isFailed &&
                        'border-rose-300 dark:border-rose-700 bg-rose-50/40 dark:bg-rose-950/20',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 font-medium text-sm text-content-primary truncate">
                          <CountryFlag
                            code={originFlagCode(c.country_iso)}
                            size={16}
                            className="shadow-xs border border-black/5"
                          />
                          <span className="truncate">{c.country_iso} · {c.city}</span>
                        </div>
                        <div className="text-[11px] text-content-tertiary mt-0.5">
                          {c.language?.toUpperCase()} · {c.currency} · {c.size_mb} MB
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          startInstall(
                            {
                              region: c.region,
                              label: `${c.country_iso} · ${c.city}`,
                              language: c.language,
                              sizeMb: c.size_mb,
                            },
                            {
                              onSuccess: () => {
                                addToast({
                                  type: 'success',
                                  title: t('match_wizard.install_toast_ok_title', 'Catalogue installed'),
                                  message: t('match_wizard.install_toast_ok_msg', '{{label}} is ready to use.', {
                                    label: `${c.country_iso} · ${c.city}`,
                                  }),
                                });
                                void queryClient.invalidateQueries({ queryKey: ['catalogues-v3'] });
                              },
                              onError: (_region, err) => {
                                addToast({
                                  type: 'error',
                                  title: t('match_wizard.install_toast_err_title', 'Install failed'),
                                  message: err.slice(0, 280),
                                });
                              },
                            },
                          )
                        }
                        disabled={isInstalling || isFinalizing}
                        className={clsx(
                          'shrink-0 inline-flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-semibold transition-all',
                          'bg-gradient-to-br from-emerald-500 to-emerald-700 text-white',
                          'shadow-sm shadow-emerald-500/25 hover:shadow-md hover:shadow-emerald-500/35 hover:-translate-y-px',
                          'disabled:opacity-60 disabled:shadow-none disabled:translate-y-0',
                        )}
                        aria-label={t('match_wizard.install_aria', 'Install {{region}}', {
                          region: c.region,
                        })}
                      >
                        {isInstalling ? (
                          <>
                            <Loader2 className="w-3 h-3 animate-spin" />
                            {job?.progress ?? 0}%
                          </>
                        ) : isFinalizing ? (
                          <>
                            <Loader2 className="w-3 h-3 animate-spin" />
                            {t('match_wizard.install_finalizing', 'Finalizing…')}
                          </>
                        ) : (
                          <>
                            <Download className="w-3 h-3" />
                            {t('match_wizard.install_button', 'Install')}
                          </>
                        )}
                      </button>
                    </div>
                    {(isInstalling || isFinalizing) && job && (
                      <div className="mt-2 h-1 rounded-full bg-emerald-100 dark:bg-emerald-900/40 overflow-hidden">
                        <div
                          className="h-full bg-emerald-500 transition-all duration-500"
                          style={{ width: `${isFinalizing ? 100 : job.progress}%` }}
                        />
                      </div>
                    )}
                    {isFailed && (
                      <div className="mt-1.5 text-[11px] text-rose-700 dark:text-rose-300 line-clamp-2">
                        {job?.errorMessage || t('match_wizard.install_failed', 'Install failed')}
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Step 3: Source ────────────────────────────────────────────────────── */

function SourceStep({
  projectId,
  selected,
  onPick,
}: {
  projectId: string;
  selected: Source | null;
  onPick: (s: Source | null) => void;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<'bim' | 'excel' | 'pdf' | 'image' | 'text'>(
    selected?.kind ?? 'bim',
  );
  const [textValue, setTextValue] = useState(
    selected?.kind === 'text' ? selected.lines.join('\n') : '',
  );

  const bimQ = useQuery({
    enabled: !!projectId && tab === 'bim',
    queryKey: ['match-bim-models', projectId],
    queryFn: () => matchElementsApi.listBIMModels(projectId),
  });

  const tabs = [
    { id: 'bim' as const, icon: Building2, label: t('match_wizard.tab_bim', 'BIM model') },
    { id: 'excel' as const, icon: FileSpreadsheet, label: t('match_wizard.tab_excel', 'Excel BoQ') },
    { id: 'pdf' as const, icon: FileType, label: t('match_wizard.tab_pdf', { defaultValue: 'PDF BoQ' }) },
    {
      id: 'image' as const,
      icon: ImageIcon,
      label: t('match_wizard.tab_image', { defaultValue: 'Photo / Drawing' }),
    },
    { id: 'text' as const, icon: FileText, label: t('match_wizard.tab_text', 'Pasted text') },
  ];

  return (
    <div className="animate-[wizard-fade_300ms_ease-out]">
      <header className="mb-6">
        <p className="text-xs uppercase tracking-[0.14em] text-indigo-600 dark:text-indigo-400 font-semibold mb-1.5">
          {t('match_wizard.step3_eyebrow', 'Step 3')}
        </p>
        <h2 className="text-2xl font-semibold tracking-tight text-content-primary mb-1.5">
          {t('match_wizard.step3_title', 'Where are the items coming from?')}
        </h2>
        <p className="text-sm text-content-secondary leading-relaxed max-w-xl">
          {t(
            'match_wizard.step3_help',
            'BIM gives quantity-aware matches. Excel and pasted text are good for ad-hoc lists.',
          )}
        </p>
      </header>

      {/* Segmented-pill tab strip — Apple iOS style */}
      <div className="inline-flex p-1 mb-5 rounded-full bg-surface-secondary border border-border-light">
        {tabs.map((tabDef) => (
          <button
            key={tabDef.id}
            type="button"
            onClick={() => setTab(tabDef.id)}
            className={clsx(
              'inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full transition-all duration-200',
              tab === tabDef.id
                ? 'bg-white dark:bg-surface-primary text-content-primary shadow-sm'
                : 'text-content-tertiary hover:text-content-secondary',
            )}
          >
            <tabDef.icon className="w-3.5 h-3.5" />
            {tabDef.label}
          </button>
        ))}
      </div>

      {tab === 'bim' && (
        <div>
          {bimQ.isLoading && (
            <div className="flex items-center gap-2 text-sm text-content-tertiary py-6 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('match_wizard.loading_models', 'Loading BIM models…')}
            </div>
          )}
          {!bimQ.isLoading && (bimQ.data?.length ?? 0) === 0 && (
            <div className="rounded-2xl border border-border-light bg-surface-secondary p-5 text-sm text-content-secondary text-center">
              {t(
                'match_wizard.no_bim',
                'No BIM models in this project. Upload one in /bim, or switch to Excel BoQ / pasted text.',
              )}
            </div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2.5">
            {(bimQ.data ?? []).map((m: BIMModelOption) => {
              const isSel = selected?.kind === 'bim' && selected.modelId === m.id;
              const isReady = m.status === 'ready';
              return (
                <SelectableTile
                  key={m.id}
                  selected={isSel}
                  disabled={!isReady}
                  onClick={() => onPick({ kind: 'bim', modelId: m.id, modelName: m.name })}
                >
                  <div className="flex items-center gap-2 mb-0.5 pr-7">
                    <Building2 className="w-4 h-4 text-content-tertiary" />
                    <span className="font-medium text-sm truncate">{m.name}</span>
                  </div>
                  <div className="text-[11px] text-content-tertiary">
                    {(m.model_format || '?').toUpperCase()} ·{' '}
                    {m.element_count ?? 0} elements ·{' '}
                    {isReady
                      ? t('match_wizard.bim_ready', 'Ready')
                      : t('match_wizard.bim_not_ready', m.status ?? 'pending')}
                  </div>
                </SelectableTile>
              );
            })}
          </div>
        </div>
      )}

      {tab === 'excel' && (
        <div>
          <label className="block">
            <span className="block text-sm text-content-secondary mb-2.5">
              {t('match_wizard.excel_label', 'Upload an .xlsx Bill of Quantities')}
            </span>
            <div className="relative rounded-2xl border-2 border-dashed border-border bg-surface-secondary/40 hover:border-indigo-400 dark:hover:border-indigo-700 transition-colors p-8 text-center">
              <input
                type="file"
                accept=".xlsx,.xls"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onPick({ kind: 'excel', file: f });
                }}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
              <FileSpreadsheet className="w-8 h-8 mx-auto text-content-tertiary mb-2" />
              <div className="text-sm text-content-secondary">
                {selected?.kind === 'excel' ? (
                  <span className="inline-flex items-center gap-1.5 text-emerald-700 dark:text-emerald-300 font-medium">
                    <Check className="w-4 h-4" strokeWidth={3} />
                    {selected.file.name}{' '}
                    <span className="text-content-quaternary font-normal">
                      ({Math.round(selected.file.size / 1024)} KB)
                    </span>
                  </span>
                ) : (
                  <>
                    <span className="font-medium text-content-primary">
                      {t('match_wizard.excel_drop', 'Click or drop an Excel file')}
                    </span>
                    <div className="text-xs text-content-tertiary mt-0.5">
                      {t('match_wizard.excel_hint', 'Multi-language column detection - EN/DE/RU/ES/PT/CJK/…')}
                    </div>
                  </>
                )}
              </div>
            </div>
          </label>
        </div>
      )}

      {tab === 'pdf' && (
        <div>
          <label className="block">
            <span className="block text-sm text-content-secondary mb-2.5">
              {t('match_wizard.pdf_label', { defaultValue: 'Upload a tender PDF (printed bill of quantities)' })}
            </span>
            <div className="relative rounded-2xl border-2 border-dashed border-border bg-surface-secondary/40 hover:border-indigo-400 dark:hover:border-indigo-700 transition-colors p-8 text-center">
              <input
                type="file"
                accept=".pdf,application/pdf"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onPick({ kind: 'pdf', file: f });
                }}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
              <FileType className="w-8 h-8 mx-auto text-content-tertiary mb-2" />
              <div className="text-sm text-content-secondary">
                {selected?.kind === 'pdf' ? (
                  <span className="inline-flex items-center gap-1.5 text-emerald-700 dark:text-emerald-300 font-medium">
                    <Check className="w-4 h-4" strokeWidth={3} />
                    {selected.file.name}{' '}
                    <span className="text-content-quaternary font-normal">
                      ({Math.round(selected.file.size / 1024)} KB)
                    </span>
                  </span>
                ) : (
                  <>
                    <span className="font-medium text-content-primary">
                      {t('match_wizard.pdf_drop', { defaultValue: 'Click or drop a PDF file' })}
                    </span>
                    <div className="text-xs text-content-tertiary mt-0.5">
                      {t('match_wizard.pdf_hint', {
                        defaultValue: 'Line items are extracted from tables or text - needs a text layer (not a scan)',
                      })}
                    </div>
                  </>
                )}
              </div>
            </div>
          </label>
        </div>
      )}

      {tab === 'image' && (
        <ImageSourceSelector
          file={selected?.kind === 'image' ? selected.file : null}
          onPick={(f) => onPick(f ? { kind: 'image', file: f } : null)}
        />
      )}

      {tab === 'text' && (
        <div>
          <label className="block">
            <span className="block text-sm text-content-secondary mb-2.5">
              {t('match_wizard.text_label', 'Paste descriptions, one per line')}
            </span>
            <textarea
              value={textValue}
              onChange={(e) => {
                setTextValue(e.target.value);
                const lines = e.target.value
                  .split(/\r?\n/)
                  .map((l) => l.trim())
                  .filter((l) => l.length > 0);
                if (lines.length > 0) {
                  onPick({ kind: 'text', lines });
                } else {
                  onPick(null);
                }
              }}
              rows={9}
              placeholder={t(
                'match_wizard.text_placeholder',
                'Concrete C30/37 wall, 240mm\nDoor - single leaf, hardwood\n…',
              )}
              className="block w-full rounded-2xl border border-border-light bg-surface-primary text-sm font-mono p-3.5 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 transition-colors"
            />
          </label>
          {selected?.kind === 'text' && (
            <div className="mt-2 text-xs text-content-tertiary">
              {t('match_wizard.text_count', '{{n}} lines', { n: selected.lines.length })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Step 4: Review + Run ──────────────────────────────────────────────── */

function ReviewStep({
  stage,
  catalogueId,
  source,
  isRunning,
}: {
  stage: ConstructionStage | '';
  catalogueId: string | null;
  source: Source | null;
  isRunning: boolean;
}) {
  const { t } = useTranslation();
  const sourceLabel = (() => {
    if (!source) return t('match_wizard.review_no_source', 'No source picked');
    if (source.kind === 'bim') return source.modelName;
    if (source.kind === 'excel' || source.kind === 'pdf' || source.kind === 'image')
      return source.file.name;
    return t('match_wizard.review_text_lines', '{{n}} lines pasted', {
      n: source.lines.length,
    });
  })();

  const items = [
    {
      icon: Layers,
      label: t('match_wizard.review_stage', 'Stage'),
      value:
        stage ||
        t('match_elements.stage_any', 'Any stage'),
    },
    {
      icon: Database,
      label: t('match_wizard.review_catalogue', 'Catalogue'),
      value: catalogueId || t('match_wizard.review_no_catalogue', 'None'),
    },
    {
      icon:
        source?.kind === 'excel'
          ? FileSpreadsheet
          : source?.kind === 'pdf'
          ? FileType
          : source?.kind === 'image'
          ? ImageIcon
          : source?.kind === 'text'
          ? FileText
          : Building2,
      label: t('match_wizard.review_source', 'Source'),
      value: sourceLabel,
    },
  ];

  return (
    <div className="animate-[wizard-fade_300ms_ease-out]">
      <header className="mb-6">
        <p className="text-xs uppercase tracking-[0.14em] text-indigo-600 dark:text-indigo-400 font-semibold mb-1.5">
          {t('match_wizard.step4_eyebrow', 'Step 4')}
        </p>
        <h2 className="text-2xl font-semibold tracking-tight text-content-primary mb-1.5">
          {t('match_wizard.step4_title', 'Run the match - then refine it')}
        </h2>
        <p className="text-sm text-content-secondary leading-relaxed max-w-xl">
          {t(
            'match_wizard.step4_help',
            'This creates the session and runs the first match. You then continue in the same flow: the visible 7-stage pipeline (Convert → Load → Schema → Filter → Group → Match → Rollup) opens so you can tune each step and re-run until the priced BoQ fits this project.',
          )}
        </p>
      </header>

      <div className="rounded-2xl border border-border-light bg-gradient-to-br from-surface-secondary/40 to-surface-primary p-5 space-y-4 mb-6">
        {items.map((it) => (
          <div key={it.label} className="flex items-start gap-3">
            <span className="w-8 h-8 rounded-xl bg-surface-primary border border-border-light flex items-center justify-center shrink-0">
              <it.icon className="w-4 h-4 text-indigo-600 dark:text-indigo-300" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[11px] uppercase tracking-[0.12em] text-content-tertiary font-semibold">
                {it.label}
              </div>
              <div className="text-sm text-content-primary truncate">{it.value}</div>
            </div>
          </div>
        ))}
      </div>

      {isRunning && (
        <div className="flex items-center gap-2 text-sm text-indigo-700 dark:text-indigo-300 bg-indigo-50/70 dark:bg-indigo-900/20 rounded-xl px-4 py-2.5">
          <Loader2 className="w-4 h-4 animate-spin" />
          {t('match_wizard.creating', 'Creating session and running vector match…')}
        </div>
      )}
    </div>
  );
}

/* ── Wizard shell ──────────────────────────────────────────────────────── */

export function MatchWizard({
  projectId,
  projectRegion,
  sessions,
  onComplete,
  onMatchSuccess,
  onMatchError,
  onResume,
}: Props) {
  const handleResume = onResume ?? onComplete;
  const { t } = useTranslation();
  const { addToast } = useToastStore();
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [stage, setStage] = useState<ConstructionStage | ''>('');
  const [catalogueId, setCatalogueId] = useState<string | null>(null);
  const [source, setSource] = useState<Source | null>(null);

  const createMut = useMutation({
    mutationFn: async (): Promise<string> => {
      if (!source) throw new Error('No source picked');
      const stagePayload = stage === '' ? null : stage;
      if (source.kind === 'excel') {
        const session = await matchElementsApi.createSessionFromExcel({
          project_id: projectId,
          file: source.file,
          catalogue_id: catalogueId,
          construction_stage: stagePayload,
        });
        return session.id;
      }
      if (source.kind === 'pdf') {
        const session = await matchElementsApi.createSessionFromPdf({
          project_id: projectId,
          file: source.file,
          catalogue_id: catalogueId,
          construction_stage: stagePayload,
        });
        return session.id;
      }
      if (source.kind === 'image') {
        const session = await matchElementsApi.createSessionFromImage({
          project_id: projectId,
          file: source.file,
          catalogue_id: catalogueId,
          construction_stage: stagePayload,
        });
        return session.id;
      }
      const sessionSpec: Parameters<typeof matchElementsApi.createSession>[0] = {
        project_id: projectId,
        source: source.kind === 'text' ? 'text' : 'bim',
        catalogue_id: catalogueId,
        construction_stage: stagePayload,
      };
      if (source.kind === 'bim') {
        sessionSpec.bim_model_id = source.modelId;
      } else {
        sessionSpec.text_inputs = source.lines.map(
          (raw_text): TextInput => ({ raw_text }),
        );
      }
      const session = await matchElementsApi.createSession(sessionSpec);
      return session.id;
    },
    onSuccess: (sessionId) => {
      // Mount the progress card the instant the session exists — it
      // begins polling /progress for real-stage updates from here.
      // Hand the parent an AbortController feeding the in-flight
      // run-match fetch so the card's Cancel button can abort the
      // request when a backend wedges. Hard 5-minute timeout matches
      // the toolbar path — anything beyond that is a wedged backend,
      // not a slow one.
      const ac = new AbortController();
      const timeoutId = window.setTimeout(() => ac.abort(), 5 * 60_000);
      onComplete(sessionId, ac);
      matchElementsApi
        .runMatch(
          sessionId,
          { method: 'vector', top_k: 10, max_groups: 50 },
          { signal: ac.signal },
        )
        .then(() => {
          window.clearTimeout(timeoutId);
          onMatchSuccess?.(sessionId);
        })
        .catch((err) => {
          window.clearTimeout(timeoutId);
          const msg = err instanceof Error ? err.message : String(err);
          if (onMatchError) {
            onMatchError(sessionId, msg);
          } else {
            // Legacy fallback when the parent doesn't wire the error
            // callback — keep the user informed via a toast.
            addToast({
              type: 'warning',
              title: t('match_wizard.match_kickoff_warn', 'Session created'),
              message: t(
                'match_wizard.match_kickoff_warn_msg',
                'Session is ready, but auto-match failed: {{error}}. Re-run from the toolbar.',
                { error: msg },
              ),
            });
          }
        });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('match_wizard.create_failed', 'Could not start matching'),
        message: err.message,
      });
    },
  });

  const canNext = useMemo(() => {
    if (step === 1) return true;
    if (step === 2) return catalogueId !== null;
    if (step === 3) return source !== null;
    return true;
  }, [step, catalogueId, source]);

  return (
    <div className="relative w-full mt-2">
      {/* Subtle ambient gradient — Apple-style "soft glow" backdrop.
          Sized to span the full page width so the card sits on a halo
          rather than appearing in a narrow column on widescreens. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-64 bg-gradient-to-b from-indigo-50/60 via-transparent to-transparent dark:from-indigo-950/20 -z-10 rounded-3xl"
      />

      {/* Goal banner — the single source of "why am I here". States the
          end goal (an accurate, project-adaptive priced BoQ) and frames
          the steps as a progressive refinement, so the stepper below
          reads as one continuous journey rather than a standalone form.
          This replaced the old second entry card + duplicate hero
          breadcrumb — there is now exactly one stepper on the page. */}
      <div className="max-w-3xl mx-auto mb-1">
        <div className="rounded-2xl border border-indigo-200/60 dark:border-indigo-800/50 bg-gradient-to-br from-indigo-50/70 via-white to-sky-50/50 dark:from-indigo-950/30 dark:via-surface-primary dark:to-sky-950/20 px-5 py-3.5 flex items-start gap-3 shadow-sm">
          <span className="shrink-0 w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-sky-500 text-white inline-flex items-center justify-center shadow-sm">
            <Target className="w-4 h-4" />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-content-primary leading-tight">
              {t(
                'match_wizard.goal_title',
                'From your model to a priced Bill of Quantities',
              )}
            </h2>
            <p className="text-xs text-content-secondary mt-0.5 leading-relaxed">
              {t(
                'match_wizard.goal_blurb',
                'Four quick steps set up the match. You then review and tune the 7-stage pipeline - each pass sharpens the costing until the estimate fits this specific project.',
              )}
            </p>
          </div>
        </div>
      </div>

      {/* The single stepper. Inset on a narrow column so it stays
          visually centred even when the content card spans the page. */}
      <div className="max-w-3xl mx-auto">
        <Stepper current={step} onJump={(n) => n <= step && setStep(n)} />
      </div>

      <div className="rounded-2xl bg-surface-primary border border-border shadow-sm p-4 sm:p-6 lg:p-8 min-h-[360px]">
        {step === 1 && (
          <StageStep
            selected={stage}
            onPick={setStage}
            sessions={sessions}
            onResume={handleResume}
          />
        )}
        {step === 2 && (
          <CatalogueStep
            projectRegion={projectRegion}
            selected={catalogueId}
            onPick={setCatalogueId}
          />
        )}
        {step === 3 && (
          <SourceStep
            projectId={projectId}
            selected={source}
            onPick={setSource}
          />
        )}
        {step === 4 && (
          <ReviewStep
            stage={stage}
            catalogueId={catalogueId}
            source={source}
            isRunning={createMut.isPending}
          />
        )}
      </div>

      {/* Footer bar — clearly delineated and aligned with the content card.
          Matches the card width so Next/Run sit on the right edge of the
          content area, not floating in the page. */}
      <div className="mt-4 flex items-center justify-between gap-3 px-1">
        <button
          type="button"
          onClick={() => setStep((s) => Math.max(1, s - 1) as 1 | 2 | 3 | 4)}
          disabled={step === 1 || createMut.isPending}
          className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-full text-sm font-medium text-content-secondary hover:text-content-primary hover:bg-surface-secondary disabled:opacity-30 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          {t('common.back', 'Back')}
        </button>

        {step < 4 ? (
          <button
            type="button"
            onClick={() => setStep((s) => Math.min(4, s + 1) as 1 | 2 | 3 | 4)}
            disabled={!canNext}
            className={clsx(
              'inline-flex items-center gap-2 px-7 py-3 rounded-full text-base font-semibold transition-all duration-200',
              'bg-gradient-to-br from-indigo-500 to-indigo-700 text-white',
              'shadow-lg shadow-indigo-500/30 hover:shadow-xl hover:shadow-indigo-500/40 hover:-translate-y-px',
              'ring-1 ring-indigo-400/30',
              'disabled:opacity-50 disabled:shadow-none disabled:translate-y-0',
            )}
          >
            {t('common.next', 'Next')}
            <ArrowRight className="w-5 h-5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => createMut.mutate()}
            disabled={!source || createMut.isPending}
            className={clsx(
              'inline-flex items-center gap-2.5 px-8 py-3.5 rounded-full text-base font-semibold transition-all duration-200',
              'bg-gradient-to-br from-indigo-500 via-indigo-600 to-indigo-700 text-white',
              'shadow-xl shadow-indigo-500/35 hover:shadow-2xl hover:shadow-indigo-500/45 hover:-translate-y-px',
              'ring-2 ring-indigo-400/40',
              'disabled:opacity-50 disabled:shadow-none disabled:translate-y-0',
            )}
          >
            {createMut.isPending ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <PlayCircle className="w-5 h-5" />
            )}
            {t('match_wizard.run_button', 'Run match')}
          </button>
        )}
      </div>

      {/* Keyframe for the subtle per-step fade-in. Lives inline so the
          component is self-contained and doesn't need a global stylesheet
          edit. */}
      <style>{`
        @keyframes wizard-fade {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
