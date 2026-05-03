// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * MatchSuggestionsPanel — shared component that surfaces ranked CWICR
 * candidates for one element from any source pipeline (BIM/PDF/DWG/photo).
 *
 * The panel is purely presentational: the parent decides what to do with
 * an accepted candidate (write to BOQ, update cost-link, etc — Phase 4).
 * Feedback is sent to the backend automatically on accept; rejected codes
 * are batched in a session-scoped Set and submitted alongside the accept
 * call so the boost re-tuner sees the full negative example list.
 *
 * The component is React Query-driven via `useMatchElement` mutation;
 * we expose the response shape in `./types.ts` and the mutations in
 * `./queries.ts` so other Phase-3+ surfaces can reuse the wiring.
 */

import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Sparkles,
  RefreshCw,
  Check,
  X as XIcon,
  Languages,
  Wand2,
  Info,
  ShieldCheck,
} from 'lucide-react';
import { Skeleton } from '@/shared/ui/Skeleton';
import { useToastStore } from '@/stores/useToastStore';
import { useMatchElement, useSubmitMatchFeedback } from './queries';
import type {
  MatchCandidate,
  MatchResponse,
  MatchSource,
} from './types';

/* ── Props ─────────────────────────────────────────────────────────────── */

export interface MatchSuggestionsPanelProps {
  source: MatchSource;
  projectId: string;
  rawElementData: Record<string, unknown>;
  /** Called when the user accepts a candidate.  The parent decides what
   *  to do (write to BOQ, update cost-link, etc).  Phase 4 wires this. */
  onAccept?: (candidate: MatchCandidate) => void | Promise<void>;
  /** Called when the user dismisses the panel without accepting. */
  onDismiss?: () => void;
  /** Initial top_k.  Defaults to 5. */
  topK?: number;
  /** Auto-fire the match request on mount.  When false, the user clicks
   *  a "Find matches" button instead.  Defaults to true. */
  autoFetch?: boolean;
  /** Compact mode for narrow side rails.  Defaults to false. */
  compact?: boolean;
  /** Optional className passthrough on the outer wrapper. */
  className?: string;
  /**
   * When ``true`` and the response carries ``auto_linked``, the panel
   * automatically calls ``onAccept`` after a short confirmation delay
   * so the user can read the green banner before the link commits.
   * The delay is :data:`AUTO_APPLY_DELAY_MS`. Default ``false`` — the
   * existing manual-accept flow is preserved.
   *
   * Wire to the per-project ``MatchProjectSettings.auto_link_enabled``
   * toggle so each tenant decides whether automation kicks in.
   */
  autoApplyLinks?: boolean;
}

/** Confirmation delay before the panel auto-fires ``onAccept`` for an
 *  auto-linked candidate. Long enough for the user to read the green
 *  banner, short enough that the next-element flow stays snappy. */
const AUTO_APPLY_DELAY_MS = 1500;

/* ── Helpers ───────────────────────────────────────────────────────────── */

const CONFIDENCE_CLASSES: Record<
  MatchCandidate['confidence_band'],
  { pill: string; ariaKey: string; defaultLabel: string }
> = {
  high: {
    pill: 'bg-green-100 text-green-800 border-green-300 dark:bg-green-900/40 dark:text-green-200',
    ariaKey: 'match.confidence.high_aria',
    defaultLabel: 'High confidence',
  },
  medium: {
    pill: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/40 dark:text-amber-200',
    ariaKey: 'match.confidence.medium_aria',
    defaultLabel: 'Medium confidence',
  },
  low: {
    pill: 'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-700/40 dark:text-slate-200',
    ariaKey: 'match.confidence.low_aria',
    defaultLabel: 'Low confidence',
  },
};

function formatBoostDelta(delta: number): string {
  // Boosts are deltas added/subtracted from the base vector score.
  // Show explicit sign + 2 decimals so users can see "+0.05" / "-0.10".
  const sign = delta >= 0 ? '+' : '';
  return `${sign}${delta.toFixed(2)}`;
}

function formatScore(score: number): string {
  return Math.round(score * 100).toString();
}

/* ── Public component ──────────────────────────────────────────────────── */

export function MatchSuggestionsPanel({
  source,
  projectId,
  rawElementData,
  onAccept,
  onDismiss,
  topK = 5,
  autoFetch = true,
  compact = false,
  className,
  autoApplyLinks = false,
}: MatchSuggestionsPanelProps) {
  const { t } = useTranslation();
  const matchMutation = useMatchElement();
  const feedbackMutation = useSubmitMatchFeedback();

  /** Toggle for the AI reranker — adds a small backend cost so off by default. */
  const [useReranker, setUseReranker] = useState(false);

  /** Codes the user rejected during this session (in-memory, not persisted). */
  const [rejectedCodes, setRejectedCodes] = useState<Set<string>>(new Set());

  /** Index of the focused candidate for keyboard navigation. */
  const [focusedIndex, setFocusedIndex] = useState<number>(0);

  const listRef = useRef<HTMLUListElement | null>(null);

  /* ── Fire the match request ─────────────────────────────────────────── */

  const fireMatch = useCallback(
    (overrideUseReranker?: boolean) => {
      matchMutation.mutate({
        source,
        project_id: projectId,
        raw_element_data: rawElementData,
        top_k: topK,
        use_reranker: overrideUseReranker ?? useReranker,
      });
      setRejectedCodes(new Set());
      setFocusedIndex(0);
    },
    [matchMutation, source, projectId, rawElementData, topK, useReranker],
  );

  // Auto-fire on mount when requested.  We deliberately depend on a stable
  // identifier rather than the full request body so re-renders don't refire.
  // The parent must pass a stable rawElementData reference (or remount) to
  // request a refetch.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (autoFetch) fireMatch();
  }, [autoFetch, source, projectId]);

  const response: MatchResponse | undefined = matchMutation.data;
  const candidates = response?.candidates ?? [];
  const visibleCandidates = useMemo(
    () => candidates.filter((c) => !rejectedCodes.has(c.code)),
    [candidates, rejectedCodes],
  );

  /* ── Accept / Reject handlers ───────────────────────────────────────── */

  const handleAccept = useCallback(
    (candidate: MatchCandidate) => {
      // 1) Submit feedback first so the audit log captures the negative
      //    list alongside the positive choice.  This is fire-and-forget;
      //    we don't block the UI on the round-trip.
      if (response?.request.envelope) {
        const rejected = candidates.filter((c) => rejectedCodes.has(c.code));
        feedbackMutation.mutate({
          project_id: projectId,
          element_envelope: response.request.envelope,
          accepted_candidate: candidate,
          rejected_candidates: rejected,
          user_chose_code: candidate.code,
        });
      }

      // 2) Notify the parent — the parent decides what to do (BOQ link
      //    in Phase 4+).  We swallow the parent's promise rejection so a
      //    bad parent handler doesn't break the panel.
      void Promise.resolve(onAccept?.(candidate)).catch(() => {});

      // 3) User-visible confirmation. When the parent supplies an
      //    ``onAccept`` callback it owns the success toast (it has more
      //    context — position ordinal, BOQ id, etc). Without a parent
      //    handler we fall back to a neutral acknowledgement so the
      //    panel still feels alive.
      if (!onAccept) {
        useToastStore.getState().addToast({
          type: 'success',
          title: t('match.accept_toast_title', { defaultValue: 'Match accepted' }),
          message: t('match.accept_toast_recorded', {
            defaultValue: 'Match recorded — feedback submitted.',
          }),
        });
      }
    },
    [
      response,
      candidates,
      rejectedCodes,
      feedbackMutation,
      projectId,
      onAccept,
      t,
    ],
  );

  const handleReject = useCallback((candidate: MatchCandidate) => {
    setRejectedCodes((prev) => {
      const next = new Set(prev);
      next.add(candidate.code);
      return next;
    });
  }, []);

  /* ── Auto-apply for auto-linked candidates ─────────────────────────────
   *
   * When the per-project ``auto_link_enabled`` setting is on AND the
   * backend flagged a candidate as ``auto_linked``, we fire ``onAccept``
   * automatically after a short confirmation delay so the user sees the
   * green banner before the link commits. The delay is cancellable —
   * if the response identity changes (refresh / next element / panel
   * unmount) the timer never fires. */
  const autoLinkedRef = useRef<string | null>(null);
  const autoLinkedCandidate = response?.auto_linked ?? null;
  useEffect(() => {
    if (!autoApplyLinks) return undefined;
    if (!autoLinkedCandidate) return undefined;
    // Skip when the user already rejected the auto-link candidate this
    // session (rare, but possible on refresh + reject).
    if (rejectedCodes.has(autoLinkedCandidate.code)) return undefined;
    // Skip when we already auto-applied this exact code for the current
    // response — guards against double-fires on re-render.
    if (autoLinkedRef.current === autoLinkedCandidate.code) return undefined;
    const timer = setTimeout(() => {
      autoLinkedRef.current = autoLinkedCandidate.code;
      handleAccept(autoLinkedCandidate);
    }, AUTO_APPLY_DELAY_MS);
    return () => clearTimeout(timer);
  }, [autoApplyLinks, autoLinkedCandidate, rejectedCodes, handleAccept]);

  const handleToggleReranker = useCallback(() => {
    const next = !useReranker;
    setUseReranker(next);
    fireMatch(next);
  }, [useReranker, fireMatch]);

  /* ── Keyboard navigation ────────────────────────────────────────────── */

  const handleListKeyDown = useCallback(
    (e: KeyboardEvent<HTMLUListElement>) => {
      if (visibleCandidates.length === 0) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setFocusedIndex((i) => Math.min(visibleCandidates.length - 1, i + 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setFocusedIndex((i) => Math.max(0, i - 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const target = visibleCandidates[focusedIndex];
        if (target) handleAccept(target);
      }
    },
    [visibleCandidates, focusedIndex, handleAccept],
  );

  /* ── Render ─────────────────────────────────────────────────────────── */

  const isLoading = matchMutation.isPending;
  const hasResults = !isLoading && visibleCandidates.length > 0;
  const isEmpty = !isLoading && visibleCandidates.length === 0;
  const autoLinkedCode = response?.auto_linked?.code ?? null;

  return (
    <section
      className={clsx('flex flex-col h-full', className)}
      aria-label={t('match.panel_aria', { defaultValue: 'Match suggestions panel' })}
      data-testid="match-suggestions-panel"
    >
      <Header
        translationUsed={response?.translation_used ?? null}
        useReranker={useReranker}
        onToggleReranker={handleToggleReranker}
        onRefresh={() => fireMatch()}
        onDismiss={onDismiss}
        loading={isLoading}
        hasAutoLink={Boolean(response?.auto_linked)}
        compact={compact}
      />

      {/* Fallback hint: when the cascade fell through to monolingual
          matching (no MUSE/IATE pair, no cache hit, LLM tier missing
          or off), nudge the user to download a dictionary so future
          matches go through a real translator.  Routes to the
          Translation section of Project Settings via the #translation
          deep-link added in Phase 3. */}
      {response?.translation_used?.tier_used === 'fallback' && !compact && (
        <div
          className="flex items-start gap-2 px-3 py-2 border-b border-border-light bg-amber-50 text-amber-900 text-[11px] dark:bg-amber-900/20 dark:text-amber-200"
          role="status"
          data-testid="match-fallback-hint"
        >
          <Info size={11} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span className="flex-1">
            {t('match.fallback_hint', {
              defaultValue:
                'Translation cascade fell back to monolingual matching.',
            })}{' '}
            <a
              href={`/projects/${projectId}/settings#translation`}
              className="font-medium text-oe-blue hover:underline"
              data-testid="match-fallback-hint-link"
            >
              {t('match.fallback_hint_link', {
                defaultValue: 'Download dictionary →',
              })}
            </a>
          </span>
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto">
        {isLoading && <SkeletonList compact={compact} />}

        {isEmpty && (
          <EmptyState projectId={projectId} hadResponse={Boolean(response)} />
        )}

        {hasResults && (
          <ul
            ref={listRef}
            role="list"
            aria-label={t('match.candidate_list_aria', {
              defaultValue: 'Candidate matches',
            })}
            className="flex flex-col divide-y divide-border-light"
            onKeyDown={handleListKeyDown}
            tabIndex={0}
          >
            {visibleCandidates.map((candidate, idx) => (
              <CandidateCard
                key={candidate.code}
                candidate={candidate}
                isFocused={idx === focusedIndex}
                isAutoLinked={candidate.code === autoLinkedCode}
                onFocus={() => setFocusedIndex(idx)}
                onAccept={() => handleAccept(candidate)}
                onReject={() => handleReject(candidate)}
                compact={compact}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

/* ── Header ────────────────────────────────────────────────────────────── */

interface HeaderProps {
  translationUsed: MatchResponse['translation_used'];
  useReranker: boolean;
  onToggleReranker: () => void;
  onRefresh: () => void;
  onDismiss: (() => void) | undefined;
  loading: boolean;
  hasAutoLink: boolean;
  compact: boolean;
}

function Header({
  translationUsed,
  useReranker,
  onToggleReranker,
  onRefresh,
  onDismiss,
  loading,
  hasAutoLink,
  compact,
}: HeaderProps) {
  const { t } = useTranslation();
  const showTranslation =
    translationUsed && translationUsed.tier_used !== 'fallback';

  return (
    <header
      className={clsx(
        'flex items-center gap-2 px-3 border-b border-border-light bg-surface-secondary',
        compact ? 'py-1.5' : 'py-2',
      )}
    >
      <Sparkles
        size={compact ? 12 : 14}
        className="text-oe-blue shrink-0"
        aria-hidden="true"
      />
      <h2
        className={clsx(
          'font-semibold text-content-primary truncate',
          compact ? 'text-[11px]' : 'text-xs',
        )}
      >
        {t('match.title', { defaultValue: 'Match suggestions' })}
      </h2>

      {hasAutoLink && (
        <span
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-green-100 text-green-800 border border-green-300 dark:bg-green-900/40 dark:text-green-200"
          aria-label={t('match.auto_linked_aria', {
            defaultValue: 'A high-confidence match was auto-linked',
          })}
          data-testid="match-auto-linked-banner"
        >
          <ShieldCheck size={10} aria-hidden="true" />
          {t('match.auto_linked', { defaultValue: 'Auto-linked' })}
        </span>
      )}

      {showTranslation && (
        <span
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-tertiary text-content-secondary border border-border-light"
          title={t('match.translated_via_tooltip', {
            defaultValue: 'Description translated before matching',
          })}
          data-testid="match-translation-chip"
        >
          <Languages size={10} aria-hidden="true" />
          {t('match.translated_via', {
            defaultValue: 'Translated via {{tier}}',
            tier: translationUsed.tier_used,
          })}
        </span>
      )}

      <div className="flex-1" />

      <label
        className={clsx(
          'inline-flex items-center gap-1.5 cursor-pointer select-none',
          compact ? 'text-[10px]' : 'text-[11px]',
          'text-content-secondary',
        )}
        title={t('match.use_rerank_tooltip', {
          defaultValue: 'Re-rank with the AI reranker (small extra cost)',
        })}
      >
        <input
          type="checkbox"
          checked={useReranker}
          onChange={onToggleReranker}
          className="h-3 w-3 accent-oe-blue"
          data-testid="match-rerank-toggle"
          aria-label={t('match.use_rerank_aria', {
            defaultValue: 'Use AI reranker',
          })}
        />
        <Wand2 size={10} aria-hidden="true" />
        <span>{t('match.use_rerank', { defaultValue: 'AI rerank' })}</span>
      </label>

      <button
        type="button"
        onClick={onRefresh}
        disabled={loading}
        aria-label={t('match.refresh_aria', { defaultValue: 'Refresh matches' })}
        title={t('match.refresh_aria', { defaultValue: 'Refresh matches' })}
        className="p-1 rounded hover:bg-surface-tertiary text-content-tertiary hover:text-content-primary disabled:opacity-40"
        data-testid="match-refresh-button"
      >
        <RefreshCw
          size={12}
          className={clsx(loading && 'animate-spin')}
          aria-hidden="true"
        />
      </button>

      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t('match.dismiss_aria', {
            defaultValue: 'Dismiss panel',
          })}
          className="p-1 rounded hover:bg-surface-tertiary text-content-tertiary hover:text-content-primary"
        >
          <XIcon size={12} aria-hidden="true" />
        </button>
      )}
    </header>
  );
}

/* ── Skeleton list (loading state) ─────────────────────────────────────── */

function SkeletonList({ compact }: { compact: boolean }) {
  const rows = compact ? 3 : 5;
  return (
    <ul
      role="list"
      aria-busy="true"
      aria-label="Loading matches"
      className="flex flex-col divide-y divide-border-light"
      data-testid="match-skeleton-list"
    >
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className={clsx('px-3', compact ? 'py-1.5' : 'py-2.5')}>
          <Skeleton height={compact ? 14 : 16} className="w-3/5 mb-1.5" />
          {!compact && <Skeleton height={12} className="w-2/3" />}
        </li>
      ))}
    </ul>
  );
}

/* ── Empty state ───────────────────────────────────────────────────────── */

function EmptyState({
  projectId,
  hadResponse,
}: {
  projectId: string;
  hadResponse: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-col items-center justify-center text-center px-6 py-10"
      data-testid="match-empty-state"
    >
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-surface-secondary text-content-tertiary">
        <Sparkles size={18} aria-hidden="true" />
      </div>
      <h3 className="text-sm font-semibold text-content-primary">
        {t('match.no_results_title', {
          defaultValue: 'No matches found yet',
        })}
      </h3>
      <p className="mt-1.5 max-w-xs text-xs text-content-secondary">
        {hadResponse
          ? t('match.no_results_after_search', {
              defaultValue:
                'Try adjusting the description or run a vector reindex.',
            })
          : t('match.no_results_initial', {
              defaultValue:
                'Click Refresh to find candidates, or run a vector reindex if results stay empty.',
            })}
      </p>
      <a
        href={`/projects/${projectId}/settings#match`}
        className="mt-3 text-xs text-oe-blue hover:underline"
      >
        {t('match.open_settings', {
          defaultValue: 'Open match settings',
        })}
      </a>
    </div>
  );
}

/* ── Candidate card ────────────────────────────────────────────────────── */

interface CandidateCardProps {
  candidate: MatchCandidate;
  isFocused: boolean;
  isAutoLinked: boolean;
  onFocus: () => void;
  onAccept: () => void;
  onReject: () => void;
  compact: boolean;
}

const CandidateCard = memo(function CandidateCard({
  candidate,
  isFocused,
  isAutoLinked,
  onFocus,
  onAccept,
  onReject,
  compact,
}: CandidateCardProps) {
  const { t } = useTranslation();
  const conf = CONFIDENCE_CLASSES[candidate.confidence_band];
  const confidenceAriaLabel = t(conf.ariaKey, {
    defaultValue: conf.defaultLabel,
  });

  if (compact) {
    return (
      <li
        onClick={onFocus}
        className={clsx(
          'flex items-center gap-1.5 px-2 py-1 cursor-pointer',
          isFocused && 'bg-surface-tertiary',
          isAutoLinked && 'border-l-2 border-l-green-500',
        )}
        data-testid={`match-candidate-${candidate.code}`}
      >
        <span className="font-mono text-[10px] font-semibold text-content-primary truncate">
          {candidate.code}
        </span>
        <span
          className={clsx(
            'inline-flex items-center px-1 rounded text-[9px] font-semibold border',
            conf.pill,
          )}
          aria-label={confidenceAriaLabel}
          title={`${formatScore(candidate.score)}%`}
        >
          {formatScore(candidate.score)}
        </span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onAccept}
          aria-label={t('match.accept_aria', {
            defaultValue: 'Accept match',
            code: candidate.code,
          })}
          className="p-1 rounded hover:bg-green-100 text-green-700"
          data-testid={`match-accept-${candidate.code}`}
        >
          <Check size={11} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={onReject}
          aria-label={t('match.reject_aria', {
            defaultValue: 'Reject match',
            code: candidate.code,
          })}
          className="p-1 rounded hover:bg-surface-tertiary text-content-tertiary"
          data-testid={`match-reject-${candidate.code}`}
        >
          <XIcon size={11} aria-hidden="true" />
        </button>
      </li>
    );
  }

  return (
    <li
      onClick={onFocus}
      className={clsx(
        'flex flex-col gap-1.5 px-3 py-2.5 cursor-pointer',
        isFocused && 'bg-surface-tertiary',
        isAutoLinked && 'border-l-2 border-l-green-500',
      )}
      data-testid={`match-candidate-${candidate.code}`}
    >
      {/* Top row: code · description · confidence pill */}
      <div className="flex items-start gap-2">
        <span
          className="font-mono text-xs font-semibold text-content-primary shrink-0"
          title={candidate.code}
        >
          {candidate.code}
        </span>
        <span
          className="flex-1 text-xs text-content-primary truncate"
          title={candidate.description}
        >
          {candidate.description}
        </span>
        <ScoreBadge candidate={candidate} ariaLabel={confidenceAriaLabel} />
        <span
          className={clsx(
            'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border shrink-0',
            conf.pill,
          )}
          aria-label={confidenceAriaLabel}
        >
          {t(`match.confidence.${candidate.confidence_band}`, {
            defaultValue: conf.defaultLabel.replace(' confidence', ''),
          })}
        </span>
      </div>

      {/* Mid row: unit / unit-rate / region */}
      <div className="flex items-center gap-2 text-[11px] text-content-secondary">
        <span className="font-medium text-content-primary">
          {candidate.unit_rate.toFixed(2)} {candidate.currency}
        </span>
        <span>·</span>
        <span>
          {t('match.per_unit', {
            defaultValue: 'per {{unit}}',
            unit: candidate.unit || '—',
          })}
        </span>
        {candidate.region_code && (
          <>
            <span>·</span>
            <span className="inline-flex items-center px-1 rounded bg-surface-tertiary border border-border-light text-[10px]">
              {candidate.region_code}
            </span>
          </>
        )}
      </div>

      {/* Reasoning (rerank only) */}
      {candidate.reasoning && (
        <p
          className="text-[11px] italic text-content-tertiary leading-snug"
          data-testid={`match-reasoning-${candidate.code}`}
        >
          {candidate.reasoning}
        </p>
      )}

      {/* Action row */}
      <div className="flex items-center gap-2 mt-0.5">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onAccept();
          }}
          className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium bg-oe-blue text-content-inverse hover:bg-oe-blue-hover"
          data-testid={`match-accept-${candidate.code}`}
        >
          <Check size={11} aria-hidden="true" />
          {t('match.accept', { defaultValue: 'Accept' })}
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onReject();
          }}
          className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium border border-border text-content-secondary hover:bg-surface-tertiary"
          data-testid={`match-reject-${candidate.code}`}
        >
          <XIcon size={11} aria-hidden="true" />
          {t('match.reject', { defaultValue: 'Reject' })}
        </button>
      </div>
    </li>
  );
});

/* ── Score badge with boost-breakdown popover ──────────────────────────── */

function ScoreBadge({
  candidate,
  ariaLabel,
}: {
  candidate: MatchCandidate;
  ariaLabel: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const boosts = Object.entries(candidate.boosts_applied);
  const tooltipId = `match-boosts-tooltip-${candidate.code}`;

  return (
    <span
      className="relative inline-flex items-center"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={ariaLabel}
        aria-describedby={open ? tooltipId : undefined}
        aria-expanded={open}
        // ``onClick`` toggles the popover so touch users (no hover, no
        // ``onMouseEnter``) and screen-reader users still get the boost
        // breakdown. ``onFocus``/``onBlur`` keep keyboard navigation
        // working.
        onClick={() => setOpen((prev) => !prev)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-surface-tertiary border border-border-light text-content-secondary"
        data-testid={`match-score-badge-${candidate.code}`}
      >
        <Info size={9} aria-hidden="true" />
        {formatScore(candidate.score)}%
      </button>
      {open && (
        <div
          id={tooltipId}
          role="tooltip"
          data-testid={`match-boosts-tooltip-${candidate.code}`}
          className="absolute right-0 top-full mt-1 z-10 min-w-[180px] rounded-md border border-border-light bg-surface-primary shadow-lg p-2 text-[10px]"
        >
          <div className="flex items-center justify-between mb-1 font-semibold text-content-primary">
            <span>
              {t('match.score_breakdown', {
                defaultValue: 'Score breakdown',
              })}
            </span>
          </div>
          <div className="flex justify-between text-content-secondary">
            <span>
              {t('match.vector_score', { defaultValue: 'Vector' })}
            </span>
            <span className="font-mono">
              {candidate.vector_score.toFixed(2)}
            </span>
          </div>
          {boosts.length === 0 ? (
            <div className="mt-1 text-content-tertiary italic">
              {t('match.no_boosts', { defaultValue: 'No boosts applied' })}
            </div>
          ) : (
            <ul className="mt-1 space-y-0.5">
              {boosts.map(([name, delta]) => (
                <li
                  key={name}
                  className="flex justify-between text-content-secondary"
                >
                  <span className="truncate" title={name}>
                    {name}
                  </span>
                  <span
                    className={clsx(
                      'font-mono ml-2',
                      delta >= 0 ? 'text-green-700' : 'text-red-700',
                    )}
                  >
                    {formatBoostDelta(delta)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </span>
  );
}

export default MatchSuggestionsPanel;
