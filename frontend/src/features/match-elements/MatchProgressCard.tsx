// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * MatchProgressCard — beautiful, informative progress card for the
 * /match-elements wizard. Shown the moment the user clicks "Let's match"
 * on Step 4 and the kickoff mutation flips to pending; replaces the
 * generic spinner that previously made the app look frozen for the
 * 5–30s the backend takes to grind through a vector match.
 *
 * Driven by real backend progress when a ``sessionId`` is supplied
 * (preferred): polls ``GET /api/v1/match_elements/sessions/{id}/progress``
 * every 800ms and reflects whichever of the five real stages the runner
 * is on right now (init / elements / ranking / save / done), with the
 * ``ranking`` stage rendering a live ``groups_done / groups_total``
 * counter so the user sees per-group progress instead of a flat bar.
 *
 * Falls back to a wall-clock heuristic when no session id is wired
 * (legacy callers or when the poll endpoint 404s on an old backend) so
 * the card never goes dark.
 *
 * v3.0.6 fix: previously the card was wall-clock-only with a fake
 * "Currency normalization" stage that activated at the 28s mark — on
 * any match exceeding 28s (which is most real projects) the label sat
 * on that stage forever and the user reported the pipeline "hanging
 * on currency normalization". The backend has no currency stage; the
 * label was a heuristic that outran reality. Real-stage polling fixes
 * the UI; a 5-minute fetch timeout + an explicit Cancel button means a
 * genuinely wedged backend can no longer wedge the page.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Check,
  Database,
  Layers,
  Loader2,
  PackageOpen,
  RefreshCw,
  Save,
  Search,
  SlidersHorizontal,
  Sparkles,
  TriangleAlert,
  X,
} from 'lucide-react';
import clsx from 'clsx';

import { matchElementsApi } from './api';
import type { MatchProgress } from './api';

/**
 * ``empty`` is a distinct terminal state from ``done``: the match POST
 * resolved successfully, but every group came back with zero catalogue
 * candidates (no catalogue installed for the region, an empty Qdrant
 * collection, or simply nothing close enough). Painting that green as a
 * "Match complete" was misleading — the user has nothing to confirm or
 * apply. ``empty`` renders an amber explainer + the actionable recovery
 * paths instead.
 */
export type MatchProgressStatus = 'running' | 'done' | 'empty' | 'error';

interface Props {
  /** Driven by the parent mutation. ``running`` is the default while the
   *  POST is in flight; flip to ``done`` to finalise the timeline + bar
   *  and trigger ``onDone`` after a brief satisfaction frame, to
   *  ``empty`` when the match resolved but found no catalogue candidates
   *  (amber explainer, no auto-advance), or to ``error`` to expose the
   *  retry button. */
  status: MatchProgressStatus;
  /** Surfaced on the active stage row when ``status === 'error'``. */
  errorMessage?: string | null;
  /** Called ~800ms after the parent flips to ``status='done'`` — gives
   *  the user a moment to see "all green, bar 100%" before the results
   *  pane swaps in. NOT called for the ``empty`` state (there is nothing
   *  to review, so the card stays put and offers recovery instead). */
  onDone: () => void;
  /** Called when the user clicks "Try again" in the error footer, or
   *  "Match again" in the empty footer. The parent is expected to
   *  re-run the match. */
  onRetry?: () => void;
  /** Called when the user clicks "Change catalogue" in the empty-state
   *  footer — the most common fix for a zero-candidate run is picking /
   *  installing a catalogue for the region. The parent routes back to
   *  the catalogue step. Optional: when absent the button is hidden. */
  onAdjust?: () => void;
  /** When supplied, the card polls
   *  ``/api/v1/match_elements/sessions/{id}/progress`` every 800ms while
   *  ``status === 'running'`` so the timeline reflects what the
   *  ``run_match`` runner is actually doing instead of a wall-clock
   *  heuristic. Optional for back-compat with callers that don't have
   *  a session id wired (the wall-clock fallback still works). */
  sessionId?: string | null;
  /** Optional Cancel-button handler. Mounts a "Cancel" affordance
   *  alongside the spinner so the user can abort a genuinely stuck
   *  backend instead of refreshing the tab. Caller is expected to fire
   *  the AbortController feeding the in-flight ``runMatch`` fetch. */
  onCancel?: () => void;
}

type StageId = 'init' | 'elements' | 'ranking' | 'save' | 'done';

interface StageDef {
  id: StageId;
  /** Wall-clock seconds at which this stage becomes the "active" one
   *  when no real progress is available. The last stage's range
   *  extends to infinity. */
  startSec: number;
  label: string;
  Icon: typeof Layers;
}

function formatElapsed(ms: number): string {
  if (ms < 0) return '0s';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem.toString().padStart(2, '0')}s`;
}

/** Indeterminate ramp 5% → 95% over ~30s. Used only when no real
 *  ``groups_done / groups_total`` counter is available — once polling
 *  is live we compute a deterministic percentage from those values.
 *  Smooth ease-out so the bar rushes early and slows down. */
function rampPct(elapsedSec: number): number {
  if (elapsedSec <= 0) return 5;
  const k = elapsedSec / 30;
  const eased = 1 - 1 / (1 + k * 1.6);
  return Math.min(95, Math.round(5 + eased * 90));
}

/** The empty-state causes the backend can actually tell us apart.
 *
 *  ``run_match`` already resolves why a run produced nothing and stamps it
 *  on the progress record before returning an empty result - it writes
 *  ``no_catalogue_rows:<id>`` when no catalogue is bound or it holds
 *  nothing at all, and ``catalog_not_vectorized:<id>`` when the bound
 *  catalogue has rows but no vectors to search. The answer was already on
 *  the wire by the time this card rendered its explainer; it was simply
 *  never read, so the card listed every possible cause instead of the one
 *  that happened. */
type EmptyReason = 'no_catalogue_rows' | 'catalog_not_vectorized';

const KNOWN_EMPTY_REASONS: readonly string[] = [
  'no_catalogue_rows',
  'catalog_not_vectorized',
];

/** Read the reason token out of a progress ``error`` string.
 *
 *  The value arrives as ``<token>:<catalogue_id>``; the id belongs in a log
 *  line, not in front of a user, so only the part before the colon is
 *  matched. Anything this does not recognise - a token from a newer
 *  backend, an unrelated error, an empty string - returns null, and the
 *  card keeps the generic explainer it has always shown. That is the
 *  point: an unknown token must never reach the screen as a raw string.
 *
 *  Exported for the unit test, which pins both directions - a known token
 *  narrows the explanation, an unknown one must leave it alone. */
export function emptyReason(
  error: string | null | undefined,
): EmptyReason | null {
  if (!error) return null;
  const token = error.split(':')[0]?.trim() ?? '';
  return KNOWN_EMPTY_REASONS.includes(token) ? (token as EmptyReason) : null;
}

export function MatchProgressCard({
  status,
  errorMessage,
  onDone,
  onRetry,
  onAdjust,
  sessionId,
  onCancel,
}: Props) {
  const { t } = useTranslation();
  const startedAtRef = useRef<number>(Date.now());
  const [now, setNow] = useState<number>(Date.now());
  const [progress, setProgress] = useState<MatchProgress | null>(null);
  const [pollFailed, setPollFailed] = useState(false);
  const firedDoneRef = useRef(false);

  // Reset the wall-clock the moment the card mounts. Using a ref keeps
  // the start time stable across re-renders without a useState ceremony.
  useEffect(() => {
    startedAtRef.current = Date.now();
    firedDoneRef.current = false;
    setProgress(null);
    setPollFailed(false);
  }, [sessionId]);

  // 1Hz wall-clock ticker for the elapsed counter and (when no real
  // progress is available) the fallback stage rotation. Stops the
  // instant ``status`` flips terminal so we don't churn timers.
  useEffect(() => {
    if (status !== 'running') return;
    const handle = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(handle);
  }, [status]);

  // Real-progress poll. When the parent gives us a session id, hit the
  // backend every 800ms while running. AbortController makes the
  // in-flight fetch cancellable on unmount so we don't leak network
  // calls across remounts (the parent remounts this component on
  // every kickoff). One failed poll is OK — we flip ``pollFailed`` to
  // surface the wall-clock fallback only after a sustained failure
  // window (3 consecutive errors).
  useEffect(() => {
    if (status !== 'running') return;
    if (!sessionId) return;
    let consecFailures = 0;
    let cancelled = false;

    const poll = async () => {
      try {
        const snap = await matchElementsApi.getProgress(sessionId);
        if (cancelled) return;
        setProgress(snap);
        consecFailures = 0;
        setPollFailed(false);
      } catch {
        consecFailures += 1;
        if (consecFailures >= 3) {
          setPollFailed(true);
        }
      }
    };
    // Immediate poll on mount so the card has real data on the first
    // render — without it the user sees the wall-clock fallback for
    // ~800ms before the first poll lands.
    void poll();
    const handle = window.setInterval(poll, 800);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [sessionId, status]);

  // One final progress read when the run lands on the empty state.
  //
  // The poll above stops the instant ``status`` leaves ``running``, and the
  // backend stamps the reason onto the progress record immediately before
  // ``run_match`` returns - so the snapshot carrying it is usually written
  // inside the window between the last 800ms poll and the POST resolving.
  // Reading once here is what makes the explanation reliable instead of a
  // matter of whether the timing happened to be kind. It reuses the same
  // endpoint and the same state the poll already writes; nothing about how
  // progress is fetched changes.
  useEffect(() => {
    if (status !== 'empty' || !sessionId) return;
    let cancelled = false;
    void (async () => {
      try {
        const snap = await matchElementsApi.getProgress(sessionId);
        if (!cancelled) setProgress(snap);
      } catch {
        // Keep whatever the poll last saw. The generic explainer below is
        // still a correct answer, only a less specific one.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status, sessionId]);

  // Fire onDone exactly once, ~800ms after the parent flips to done.
  // Gives the user a satisfying "all green, bar full" frame before the
  // results pane swaps in.
  useEffect(() => {
    if (status !== 'done' || firedDoneRef.current) return;
    firedDoneRef.current = true;
    const handle = window.setTimeout(onDone, 800);
    return () => window.clearTimeout(handle);
  }, [status, onDone]);

  const stages: StageDef[] = useMemo(
    () => [
      {
        id: 'init',
        startSec: 0,
        label: t('match_progress.stage_init', {
          defaultValue: 'Preparing session',
        }),
        Icon: Sparkles,
      },
      {
        id: 'elements',
        startSec: 2,
        label: t('match_progress.stage_elements', {
          defaultValue: 'Loading elements',
        }),
        Icon: Layers,
      },
      {
        id: 'ranking',
        startSec: 5,
        label: t('match_progress.stage_ranking', {
          defaultValue: 'Ranking candidates',
        }),
        Icon: Search,
      },
      {
        id: 'save',
        startSec: 22,
        label: t('match_progress.stage_save', {
          defaultValue: 'Saving results',
        }),
        Icon: Save,
      },
      {
        id: 'done',
        startSec: 28,
        label: t('match_progress.stage_done', {
          defaultValue: 'Wrapping up',
        }),
        Icon: Database,
      },
    ],
    [t],
  );

  const elapsedMs = Math.max(0, now - startedAtRef.current);
  const elapsedSec = Math.floor(elapsedMs / 1000);

  // Real progress wins when we have it; otherwise fall back to the
  // wall-clock heuristic so the card stays informative even on legacy
  // backends or while the first poll is in flight.
  const useRealProgress = !pollFailed && progress != null && progress.status !== 'idle';

  // Map backend stage → the timeline index. ``init`` / ``elements`` /
  // ``ranking`` / ``save`` align 1-to-1; ``done`` flips every row
  // green. Unknown / idle stages collapse onto the wall-clock pass.
  const activeIdx = useMemo(() => {
    // ``empty`` is terminal like ``done`` — every stage ran, the result
    // was just barren — so the timeline shows all rows complete.
    if (status === 'done' || status === 'empty') return stages.length;
    if (useRealProgress && progress) {
      const idx = stages.findIndex((s) => s.id === progress.stage);
      if (idx >= 0) return idx;
    }
    let idx = 0;
    for (let i = 0; i < stages.length; i++) {
      const s = stages[i];
      if (s && elapsedSec >= s.startSec) idx = i;
    }
    return idx;
  }, [elapsedSec, status, stages, useRealProgress, progress]);

  // Per-group counter for the ranking stage. Computed from the real
  // poll snapshot when available so the bar advances proportionally to
  // actual work done. Outside the ranking stage we fall back to the
  // wall-clock ramp.
  const overallPct = useMemo(() => {
    if (status === 'done' || status === 'empty') return 100;
    if (useRealProgress && progress) {
      // Stage weight: init=5, elements=10, ranking=70, save=10, done=5
      const stageWeights: Record<StageId, [number, number]> = {
        init: [0, 5],
        elements: [5, 15],
        ranking: [15, 85],
        save: [85, 95],
        done: [95, 100],
      };
      const [lo, hi] = stageWeights[progress.stage as StageId] ?? [5, 95];
      if (progress.stage === 'ranking' && progress.groups_total > 0) {
        const frac = Math.min(
          1,
          Math.max(0, progress.groups_done / progress.groups_total),
        );
        return Math.round(lo + (hi - lo) * frac);
      }
      // Mid-stage default — sit halfway between the stage's lo/hi so
      // the bar visibly advances at each stage boundary.
      return Math.round((lo + hi) / 2);
    }
    return rampPct(elapsedSec);
  }, [status, useRealProgress, progress, elapsedSec]);

  const isRunning = status === 'running';
  const isDone = status === 'done';
  const isEmpty = status === 'empty';
  const isError = status === 'error';

  // Which of the empty-state causes actually happened, when the backend
  // said so. Null - no progress snapshot, no error stamped, or a token we
  // do not know - keeps the generic explainer that lists every cause.
  const reason = emptyReason(progress?.error);

  const rankingCounter = useMemo(() => {
    if (!useRealProgress || !progress) return null;
    if (progress.stage !== 'ranking') return null;
    if (progress.groups_total <= 0) return null;
    return `${progress.groups_done} / ${progress.groups_total}`;
  }, [useRealProgress, progress]);

  const headline = useMemo(() => {
    if (isError) {
      return t('match_progress.headline_error', {
        defaultValue: 'Something went wrong',
      });
    }
    if (isEmpty) {
      return t('match_progress.headline_empty', {
        defaultValue: 'No catalogue matches found',
      });
    }
    if (isDone) {
      return t('match_progress.headline_done', {
        defaultValue: 'All done - opening your results',
      });
    }
    const stageLabel = stages[activeIdx]?.label ?? stages[0]?.label ?? '';
    if (rankingCounter) {
      return `${stageLabel} - ${rankingCounter}`;
    }
    if (elapsedSec >= 60) {
      return t('match_progress.headline_long', {
        defaultValue:
          'Almost done - large projects can take a minute',
      });
    }
    return stageLabel;
  }, [isError, isEmpty, isDone, elapsedSec, stages, activeIdx, t, rankingCounter]);

  const handleCancel = useCallback(() => {
    onCancel?.();
  }, [onCancel]);

  return (
    <div
      className={clsx(
        'rounded-2xl border bg-surface-primary shadow-sm p-5 sm:p-7 max-w-3xl mx-auto mt-4 transition-opacity duration-500',
        isError
          ? 'border-rose-200 dark:border-rose-800/60'
          : isEmpty
            ? 'border-amber-200 dark:border-amber-800/60'
            : 'border-border',
      )}
      data-testid="match-progress-card"
      data-status={status}
      data-stage={stages[activeIdx]?.id ?? 'done'}
      data-progress-source={useRealProgress ? 'backend' : 'heuristic'}
    >
      {/* Header — title + elapsed */}
      <header className="flex items-start justify-between gap-3 mb-5">
        <div className="min-w-0 flex-1">
          <h3 className="text-lg font-semibold tracking-tight text-content-primary inline-flex items-center gap-2">
            {isError ? (
              <>
                <TriangleAlert className="w-5 h-5 text-rose-600" />
                {t('match_progress.title_error', {
                  defaultValue: 'Match failed',
                })}
              </>
            ) : isEmpty ? (
              <>
                <span className="w-6 h-6 rounded-full bg-amber-500 text-white inline-flex items-center justify-center shadow-sm shadow-amber-500/40">
                  <PackageOpen className="w-4 h-4" strokeWidth={2.5} />
                </span>
                {t('match_progress.title_empty', {
                  defaultValue: 'No matches found',
                })}
              </>
            ) : isDone ? (
              <>
                <span className="w-6 h-6 rounded-full bg-emerald-500 text-white inline-flex items-center justify-center shadow-sm shadow-emerald-500/40">
                  <Check className="w-4 h-4" strokeWidth={3} />
                </span>
                {t('match_progress.title_done', {
                  defaultValue: 'Match complete',
                })}
              </>
            ) : (
              <>
                <Loader2 className="w-5 h-5 animate-spin text-indigo-600" />
                {t('match_progress.title_running', {
                  defaultValue: 'Matching in progress',
                })}
              </>
            )}
          </h3>
          <p className="text-xs text-content-tertiary mt-1.5 max-w-xl">
            {isError
              ? errorMessage ??
                t('match_progress.subtitle_error', {
                  defaultValue:
                    'The matcher couldn’t finish - try again or pick a different catalogue.',
                })
              : isEmpty
              ? t('match_progress.subtitle_empty', {
                  defaultValue:
                    'The run finished but no catalogue rows matched. There is nothing to review or apply yet.',
                })
              : isDone
              ? t('match_progress.subtitle_done', {
                  defaultValue:
                    'All stages green - handing over to the review panel.',
                })
              : t('match_progress.subtitle_running', {
                  defaultValue:
                    'We’re searching the catalogue with vector + lexical + region signals. Safe to leave open in a tab.',
                })}
          </p>
        </div>
        <div className="shrink-0 text-right tabular-nums">
          <div className="text-[11px] uppercase tracking-[0.14em] text-content-tertiary font-semibold">
            {t('match_progress.elapsed', { defaultValue: 'Elapsed' })}
          </div>
          <div className="text-sm font-semibold text-content-primary">
            {formatElapsed(elapsedMs)}
          </div>
        </div>
      </header>

      {/* Overall progress bar — proportional to real groups_done /
          groups_total during the ranking stage when polling is live,
          otherwise a smooth wall-clock ramp. */}
      <div
        className={clsx(
          'h-1.5 rounded-full mb-5 overflow-hidden',
          isError
            ? 'bg-rose-100 dark:bg-rose-950/40'
            : isEmpty
              ? 'bg-amber-100 dark:bg-amber-950/40'
              : 'bg-surface-secondary',
        )}
      >
        <div
          className={clsx(
            'h-full rounded-full transition-all duration-700 ease-out',
            isError
              ? 'bg-rose-500'
              : isEmpty
              ? 'bg-amber-500'
              : isDone
              ? 'bg-emerald-500'
              : 'bg-gradient-to-r from-indigo-500 to-indigo-700',
          )}
          style={{ width: `${overallPct}%` }}
          role="progressbar"
          aria-valuenow={overallPct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={t('match_progress.overall_aria', {
            defaultValue: 'Overall match progress',
          })}
        />
      </div>

      {/* Rotating headline — the current stage label, or the long-tail
          reassurance message after 60s. */}
      <p
        className={clsx(
          'text-sm font-semibold mb-5 transition-colors',
          isError
            ? 'text-rose-700 dark:text-rose-300'
            : isEmpty
            ? 'text-amber-700 dark:text-amber-300'
            : isDone
            ? 'text-emerald-700 dark:text-emerald-300'
            : 'text-content-primary',
        )}
        aria-live="polite"
      >
        {headline}
      </p>

      {/* Vertical timeline — 5 real stages. Past stages are emerald +
          check; active stage is indigo + spinner; pending stages dim
          down. On error the active row flips to a rose X. */}
      <ol className="space-y-3">
        {stages.map((s, i) => {
          const isPast = !isError && i < activeIdx;
          const isCurrent = !isError && !isDone && !isEmpty && i === activeIdx;
          const isFinalGreen = isDone;
          const isErrorRow = isError && i === activeIdx;

          const badge = (() => {
            if (isErrorRow) {
              return (
                <span className="w-7 h-7 rounded-full bg-rose-100 dark:bg-rose-950/40 text-rose-600 dark:text-rose-300 inline-flex items-center justify-center ring-2 ring-rose-200 dark:ring-rose-800/40">
                  <X className="w-4 h-4" strokeWidth={3} />
                </span>
              );
            }
            if (isEmpty) {
              // Every stage ran — show an amber check, not the emerald
              // "success" tick, because the outcome was barren.
              return (
                <span className="w-7 h-7 rounded-full bg-amber-500 text-white inline-flex items-center justify-center shadow-sm shadow-amber-500/40">
                  <Check className="w-4 h-4" strokeWidth={3} />
                </span>
              );
            }
            if (isPast || isFinalGreen) {
              return (
                <span className="w-7 h-7 rounded-full bg-emerald-500 text-white inline-flex items-center justify-center shadow-sm shadow-emerald-500/40">
                  <Check className="w-4 h-4" strokeWidth={3} />
                </span>
              );
            }
            if (isCurrent) {
              return (
                <span className="w-7 h-7 rounded-full bg-gradient-to-br from-indigo-500 to-indigo-700 text-white inline-flex items-center justify-center shadow-md shadow-indigo-500/40 ring-2 ring-indigo-200 dark:ring-indigo-900/40">
                  <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2.5} />
                </span>
              );
            }
            return (
              <span className="w-7 h-7 rounded-full bg-surface-secondary text-content-tertiary inline-flex items-center justify-center border-2 border-border">
                <s.Icon className="w-3.5 h-3.5" strokeWidth={1.75} />
              </span>
            );
          })();

          return (
            <li
              key={s.id}
              className={clsx(
                'flex items-center gap-3 transition-opacity duration-300',
                !isCurrent && !isPast && !isFinalGreen && !isErrorRow && 'opacity-45',
              )}
              data-stage-row={s.id}
              data-active={isCurrent}
              data-done={isPast || isFinalGreen}
              data-error={isErrorRow || undefined}
            >
              {badge}
              <span
                className={clsx(
                  'text-sm transition-colors',
                  isErrorRow
                    ? 'font-semibold text-rose-700 dark:text-rose-300'
                    : isCurrent
                    ? 'font-semibold text-content-primary'
                    : isPast || isFinalGreen
                    ? 'font-medium text-content-secondary'
                    : 'text-content-tertiary',
                )}
              >
                {s.label}
                {isCurrent && s.id === 'ranking' && rankingCounter && (
                  <span className="ml-2 text-content-tertiary tabular-nums">
                    {rankingCounter}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ol>

      {/* Error footer — message + Try again button. Only mounts on
          error so it doesn't add weight to the running / done states. */}
      {isError && (
        <div className="mt-6 rounded-xl border border-rose-200 dark:border-rose-800/60 bg-rose-50/60 dark:bg-rose-950/20 p-4 flex flex-col sm:flex-row sm:items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-semibold text-rose-900 dark:text-rose-100 mb-0.5">
              {t('match_progress.error_label', {
                defaultValue: 'Error details',
              })}
            </div>
            <div className="text-xs text-rose-700 dark:text-rose-300 break-words">
              {errorMessage ||
                t('match_progress.error_fallback', {
                  defaultValue: 'Unknown error',
                })}
            </div>
          </div>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold bg-gradient-to-br from-rose-500 to-rose-600 text-white shadow-sm shadow-rose-500/30 hover:shadow-md hover:shadow-rose-500/40 hover:-translate-y-px transition-all"
            >
              <RefreshCw className="w-4 h-4" />
              {t('match_progress.retry', { defaultValue: 'Try again' })}
            </button>
          )}
        </div>
      )}

      {/* Empty footer — the run completed but every group came back with
          zero catalogue candidates. This is NOT a success: there is
          nothing to confirm or apply. Explain the likely causes and give
          the two recovery paths (pick/install a catalogue, or re-run).
          Mounted only on the empty state. */}
      {isEmpty && (
        <div
          data-testid="match-progress-empty"
          className="mt-6 rounded-xl border border-amber-200 dark:border-amber-800/60 bg-amber-50/60 dark:bg-amber-950/20 p-4"
        >
          <div className="text-xs font-semibold text-amber-900 dark:text-amber-100 mb-1">
            {t('match_progress.empty_label', {
              defaultValue: 'Why am I seeing this?',
            })}
          </div>
          {/* When the backend named the cause, say that one thing. Listing
              both alongside it would put the answer back in a guessing game
              the run already settled. Without a named cause we keep the
              original pair, which is honest about not knowing. */}
          <ul
            className="text-xs text-amber-800 dark:text-amber-200 list-disc pl-4 space-y-0.5"
            data-reason={reason ?? undefined}
          >
            {reason === 'no_catalogue_rows' ? (
              <li data-testid="match-progress-empty-reason">
                {t('match_progress.empty_reason_catalogue', {
                  defaultValue:
                    'No cost catalogue is installed for this region, so there were no rates to match against.',
                })}
              </li>
            ) : reason === 'catalog_not_vectorized' ? (
              <li data-testid="match-progress-empty-reason">
                {t('match_progress.empty_reason_not_vectorized', {
                  defaultValue:
                    'This catalogue is installed but has not been indexed for search yet, so there was nothing to match against. Run a vector reindex to enable matching.',
                })}
              </li>
            ) : (
              <>
                <li>
                  {t('match_progress.empty_reason_catalogue', {
                    defaultValue:
                      'No cost catalogue is installed for this region, so there were no rates to match against.',
                  })}
                </li>
                <li>
                  {t('match_progress.empty_reason_collection', {
                    defaultValue:
                      'The selected catalogue is empty, or nothing in it was close enough to your elements.',
                  })}
                </li>
              </>
            )}
          </ul>
          <div className="mt-3 flex flex-col sm:flex-row sm:items-center gap-2">
            {onAdjust && (
              <button
                type="button"
                data-testid="match-progress-empty-adjust"
                onClick={onAdjust}
                className="shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold bg-gradient-to-br from-amber-500 to-orange-600 text-white shadow-sm shadow-amber-500/30 hover:shadow-md hover:shadow-amber-500/40 hover:-translate-y-px transition-all"
              >
                <SlidersHorizontal className="w-4 h-4" />
                {t('match_progress.empty_adjust', {
                  defaultValue: 'Change catalogue',
                })}
              </button>
            )}
            {onRetry && (
              <button
                type="button"
                data-testid="match-progress-empty-retry"
                onClick={onRetry}
                className="shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold border border-amber-300 dark:border-amber-700 bg-surface-primary text-amber-900 dark:text-amber-100 hover:bg-amber-50 dark:hover:bg-amber-900/30 transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                {t('match_progress.empty_retry', { defaultValue: 'Match again' })}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Cancel affordance — mounted only while the match is running
          AND elapsed time has passed the point where most healthy runs
          would have completed. Earlier than 20s it's noisy ("wait,
          this is fast!"); past 20s it's a genuine safety valve for a
          stuck backend. */}
      {isRunning && onCancel && elapsedSec >= 20 && (
        <div className="mt-5 flex items-center justify-between gap-3 rounded-xl border border-border bg-surface-secondary/40 p-3">
          <div className="text-xs text-content-secondary">
            {t('match_progress.cancel_hint', {
              defaultValue:
                'Taking longer than usual? You can cancel and try a smaller selection.',
            })}
          </div>
          <button
            type="button"
            data-testid="match-progress-cancel"
            onClick={handleCancel}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border border-border bg-surface-primary text-content-primary hover:bg-surface-tertiary transition-colors"
          >
            <X className="w-3.5 h-3.5" />
            {t('match_progress.cancel', { defaultValue: 'Cancel' })}
          </button>
        </div>
      )}

      {/* Hint — running state only. Tells the user what to do if it
          really does take a long time. */}
      {isRunning && elapsedSec >= 45 && (
        <p className="text-[11px] text-content-tertiary mt-5 leading-snug">
          {t('match_progress.long_hint', {
            defaultValue:
              'Still working - first runs on large BIM models take longer because vectors are warming up. Subsequent runs on the same project are much faster.',
          })}
        </p>
      )}
    </div>
  );
}
