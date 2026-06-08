// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Stage 3 - Match rates (human-confirm checkpoint #3). One expandable card
// per group: colored score badge, chosen catalogue rate, expandable
// resource breakdown, alternative candidates to override (inline list or a
// full drawer), re-query, "ask the agent to re-search", and accept / skip.
// Low-confidence rows are pinned to the top, never silently dropped. The
// agent suggests; the human confirms every rate. Resource + candidate
// detail is fetched per-card on expand (the list endpoint returns
// summaries only). A threshold control drives bulk-confirm.

import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  ChevronDown,
  ChevronRight,
  Check,
  SkipForward,
  RefreshCw,
  Sparkles,
  Layers3,
  AlertTriangle,
  Loader2,
  ListFilter,
  Info,
} from 'lucide-react';
import { Button, EmptyState } from '@/shared/ui';
import { ResourceBreakdown } from './ResourceBreakdown';
import { AlternativesDrawer } from './AlternativesDrawer';
import { MappingTrace, OutlierBadge } from './MappingTrace';
import {
  scoreBorder,
  scoreColor,
  scorePercent,
  groupStatusChip,
  fmtMoneyStr,
  toNum,
} from '../helpers';
import { useScoreThresholds } from '../meta';
import { aiEstimatorApi, type CandidateOut, type GroupSummary } from '../api';

export interface Stage3MatchProps {
  runId: string;
  groups: GroupSummary[];
  loading: boolean;
  /** True while the batched match pass is still running. Drives the live
   *  progress bar and lets results stream in instead of hiding behind a
   *  skeleton until every batch finishes. */
  matching?: boolean;
  locale?: string;
  aiConnected: boolean;
  highThreshold: number;
  /** Groups matched per pass (server-driven). When the group count exceeds
   *  this, match-all batches and we disclose that to the user. */
  matchGroupCap: number;
  onAccept: (groupId: string, candidateId: string | null) => void;
  onSkip: (groupId: string) => void;
  onRematch: (groupId: string, useAgent: boolean) => void;
  rematchingId: string | null;
  onBulkAccept: (threshold: number) => void;
  bulkPending: boolean;
}

/** Sort low-confidence + unmatched first so they are never missed. */
function sortForReview(groups: GroupSummary[]): GroupSummary[] {
  const rank = (g: GroupSummary) => {
    if (g.status === 'needs_human' || g.status === 'unmatched') return 0;
    if (g.confidence_band === 'low') return 1;
    if (g.confidence_band === 'medium') return 2;
    return 3;
  };
  return [...groups].sort((a, b) => rank(a) - rank(b) || a.sort_order - b.sort_order);
}

/** A group still wants a human look: unmatched, flagged, or no rate yet. */
function needsAttention(g: GroupSummary): boolean {
  return (
    g.status === 'needs_human' ||
    g.status === 'unmatched' ||
    g.confidence_band === 'low' ||
    g.chosen_code == null
  );
}

/** Readable section title for a trade key when no `aiest.trade.<key>` exists. */
function humanizeTrade(trade: string): string {
  return trade
    .replace(/[_-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (c) => c.toUpperCase());
}

interface TradeSection {
  trade: string | null;
  groups: GroupSummary[];
  attention: number;
}

/** Bucket groups by trade, sort each bucket for review, and order the
 *  buckets so trades that still need attention float to the top. */
function buildTradeSections(groups: GroupSummary[]): TradeSection[] {
  const buckets = new Map<string, GroupSummary[]>();
  for (const g of groups) {
    const key = g.trade ?? '';
    const list = buckets.get(key);
    if (list) list.push(g);
    else buckets.set(key, [g]);
  }
  const sections: TradeSection[] = [];
  for (const [key, list] of buckets) {
    const sorted = sortForReview(list);
    sections.push({
      trade: key || null,
      groups: sorted,
      attention: sorted.filter(needsAttention).length,
    });
  }
  // Trades with open items first (most first), then alphabetically; the
  // "no trade" bucket always sinks to the bottom.
  return sections.sort((a, b) => {
    if (!a.trade && b.trade) return 1;
    if (a.trade && !b.trade) return -1;
    if (a.attention !== b.attention) return b.attention - a.attention;
    return (a.trade ?? '').localeCompare(b.trade ?? '');
  });
}

function MatchCard({
  runId,
  group,
  locale,
  aiConnected,
  onAccept,
  onSkip,
  onRematch,
  rematching,
  onOpenAlternatives,
}: {
  runId: string;
  group: GroupSummary;
  locale?: string;
  aiConnected: boolean;
  onAccept: (groupId: string, candidateId: string | null) => void;
  onSkip: (groupId: string) => void;
  onRematch: (groupId: string, useAgent: boolean) => void;
  rematching: boolean;
  onOpenAlternatives: (groupId: string) => void;
}) {
  const { t } = useTranslation();
  const thresholds = useScoreThresholds();
  const [open, setOpen] = useState(
    group.status === 'unmatched' || group.confidence_band === 'low',
  );
  const [showAlts, setShowAlts] = useState(false);
  const altListRef = useRef<HTMLUListElement>(null);

  // Lazily fetch detail (resources + candidates) only when expanded.
  const detailQ = useQuery({
    enabled: open,
    queryKey: ['aiest-group-detail', runId, group.id, group.chosen_code],
    queryFn: () => aiEstimatorApi.getGroup(runId, group.id),
  });
  const detail = detailQ.data;

  const hasRate = group.chosen_code != null;
  // A code can be matched yet carry no price (the cost table has no priced row
  // for it). Then unit_rate is null and we show "matched, no price" rather than
  // a fabricated $0.00.
  const hasPrice = group.unit_rate != null && Number(group.unit_rate) > 0;
  const confirmed = group.status === 'confirmed' || group.status === 'overridden';
  // Alternatives = every returned candidate other than the chosen one
  // (matched by code, since the group is summarised by chosen_code).
  const candidates = detail?.candidates ?? [];
  const alternatives = candidates.filter((c) => c.code !== group.chosen_code);
  // The chosen rate is a benchmark-band outlier when its candidate carries the
  // rate-sanity flag. We surface it on the header so a suspect rate is never
  // confirmed unseen (the real DB rate is kept, only flagged).
  const chosenOutlier =
    hasRate && candidates.some((c) => c.code === group.chosen_code && c.rate_outlier === true);

  // Roving keyboard navigation across the alternative candidate buttons.
  const onAltKeyDown = (e: React.KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const items = Array.from(
      altListRef.current?.querySelectorAll<HTMLButtonElement>('button[data-alt]') ?? [],
    );
    if (items.length === 0) return;
    const idx = items.findIndex((el) => el === document.activeElement);
    e.preventDefault();
    const next = e.key === 'ArrowDown' ? Math.min(idx + 1, items.length - 1) : Math.max(idx - 1, 0);
    items[next < 0 ? 0 : next]?.focus();
  };

  return (
    <div className={clsx('rounded-lg border bg-surface-elevated', scoreBorder(group.score, thresholds))}>
      {/* Header row */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-3 py-2.5 text-left"
      >
        {open ? (
          <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-content-tertiary" />
        ) : (
          <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-content-tertiary" />
        )}
        <span
          className={clsx(
            'mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold',
            scoreColor(group.score, thresholds),
          )}
        >
          {scorePercent(group.score)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-content-primary">
            {group.description || group.group_key}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-content-tertiary">
            <span>
              {toNum(group.primary_quantity)} {group.chosen_unit ?? ''}
            </span>
            {hasRate ? (
              <>
                <span className="font-mono">{group.chosen_code}</span>
                {hasPrice ? (
                  <span>
                    {fmtMoneyStr(group.unit_rate, group.currency, locale)} /{' '}
                    {group.chosen_unit ?? ''}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
                    <AlertTriangle className="h-3 w-3" />
                    {t('aiest.match.no_price', { defaultValue: 'matched, no price in catalogue' })}
                  </span>
                )}
                {group.match_method && (
                  <span className="rounded bg-surface-muted px-1 py-0.5 text-[10px] uppercase">
                    {t(`aiest.method.${group.match_method}`, { defaultValue: group.match_method })}
                  </span>
                )}
                {chosenOutlier && <OutlierBadge />}
              </>
            ) : (
              <span className="inline-flex items-center gap-1 text-rose-500">
                <AlertTriangle className="h-3 w-3" />
                {t('aiest.match.no_rate', { defaultValue: 'No rate found' })}
              </span>
            )}
          </div>
        </div>
        <span
          className={clsx(
            'mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-xs',
            groupStatusChip(group.status),
          )}
        >
          {t(`aiest.status.group_${group.status}`, { defaultValue: group.status })}
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-border-light px-3 py-3">
          {detailQ.isLoading ? (
            <div className="flex items-center gap-2 text-xs text-content-tertiary">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t('aiest.match.loading_detail', { defaultValue: 'Loading candidates...' })}
            </div>
          ) : (
            <>
              {hasRate && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-content-secondary">
                    <Layers3 className="h-3.5 w-3.5" />
                    {t('aiest.match.breakdown', { defaultValue: 'Resource breakdown' })}
                  </div>
                  <ResourceBreakdown
                    resources={detail?.resources ?? []}
                    currency={group.currency}
                    locale={locale}
                  />
                </div>
              )}

              {/* Why this rate: the three-pass mapping trace (semantic ->
                  unit/scale -> rate sanity). Auto-opens when the chosen rate is
                  a flagged outlier so the reason is in view without a click. */}
              <MappingTrace trace={detail?.mapping_trace} defaultOpen={chosenOutlier} />

              {/* Alternatives */}
              {alternatives.length > 0 && (
                <div>
                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={() => setShowAlts((s) => !s)}
                      aria-expanded={showAlts}
                      className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
                    >
                      {showAlts
                        ? t('aiest.match.hide_alts', { defaultValue: 'Hide alternatives' })
                        : t('aiest.match.show_alts', {
                            defaultValue: 'Show {{n}} alternatives',
                            n: alternatives.length,
                          })}
                    </button>
                    <button
                      type="button"
                      onClick={() => onOpenAlternatives(group.id)}
                      className="inline-flex items-center gap-1 text-xs font-medium text-content-secondary hover:text-oe-blue"
                    >
                      <ListFilter className="h-3 w-3" />
                      {t('aiest.match.compare_all', { defaultValue: 'Compare all' })}
                    </button>
                  </div>
                  {showAlts && (
                    <ul
                      ref={altListRef}
                      onKeyDown={onAltKeyDown}
                      className="mt-2 space-y-1.5"
                      aria-label={t('aiest.match.alternatives', { defaultValue: 'Alternatives' })}
                    >
                      {alternatives.map((c: CandidateOut, i) => (
                        <li
                          key={c.candidate_id ?? `${c.code}-${i}`}
                          className="flex items-center gap-2 rounded-lg border border-border-light px-2.5 py-1.5"
                        >
                          <span
                            className={clsx(
                              'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold',
                              scoreColor(c.score, thresholds),
                            )}
                          >
                            {scorePercent(c.score)}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                              <span className="truncate text-xs font-medium text-content-primary">
                                {c.description}
                              </span>
                              {c.rate_outlier === true && <OutlierBadge className="shrink-0" />}
                            </div>
                            <div className="text-[11px] text-content-tertiary">
                              <span className="font-mono">{c.code}</span> ·{' '}
                              {c.unit_rate != null && Number(c.unit_rate) > 0 ? (
                                <>
                                  {fmtMoneyStr(c.unit_rate, c.currency, locale)} / {c.unit}
                                </>
                              ) : (
                                <span className="text-amber-600 dark:text-amber-400">
                                  {t('aiest.match.no_price', {
                                    defaultValue: 'matched, no price in catalogue',
                                  })}
                                </span>
                              )}
                            </div>
                          </div>
                          <Button
                            variant="secondary"
                            size="sm"
                            data-alt
                            onClick={() => onAccept(group.id, c.candidate_id)}
                          >
                            {t('aiest.match.use', { defaultValue: 'Use' })}
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </>
          )}

          {/* Actions */}
          <div className="flex flex-wrap gap-2">
            {hasRate && !confirmed && (
              <Button
                variant="primary"
                size="sm"
                icon={<Check className="h-3.5 w-3.5" />}
                onClick={() => onAccept(group.id, null)}
              >
                {t('aiest.match.accept', { defaultValue: 'Accept rate' })}
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              loading={rematching}
              onClick={() => onRematch(group.id, false)}
            >
              {t('aiest.match.requery', { defaultValue: 'Re-query' })}
            </Button>
            {aiConnected && (
              <Button
                variant="ghost"
                size="sm"
                icon={<Sparkles className="h-3.5 w-3.5" />}
                disabled={rematching}
                onClick={() => onRematch(group.id, true)}
                title={t('aiest.match.ask_agent_hint', {
                  defaultValue: 'Let the agent refine the query and re-search',
                })}
              >
                {t('aiest.match.ask_agent', { defaultValue: 'Ask the agent to re-search' })}
              </Button>
            )}
            {group.status !== 'skipped' && (
              <Button
                variant="ghost"
                size="sm"
                icon={<SkipForward className="h-3.5 w-3.5" />}
                onClick={() => onSkip(group.id)}
              >
                {t('aiest.match.skip', { defaultValue: 'Skip' })}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function Stage3Match(props: Stage3MatchProps) {
  const { t } = useTranslation();
  const {
    runId,
    groups,
    loading,
    matching = false,
    locale,
    aiConnected,
    highThreshold,
    matchGroupCap,
    onAccept,
    onSkip,
    onRematch,
    rematchingId,
    onBulkAccept,
    bulkPending,
  } = props;

  const [threshold, setThreshold] = useState(Math.round(highThreshold * 100));
  const [altGroupId, setAltGroupId] = useState<string | null>(null);
  // Group the result cards by trade (default) so a long match list reads as
  // "concrete, masonry, finishes" instead of one flat scroll. A toggle keeps
  // the old flat priority view for users who prefer it.
  const [groupByTrade, setGroupByTrade] = useState(true);
  const [collapsedTrades, setCollapsedTrades] = useState<Record<string, boolean>>({});

  const ordered = useMemo(() => sortForReview(groups), [groups]);
  const tradeSections = useMemo(() => buildTradeSections(groups), [groups]);
  // Only worth grouping when there is more than one trade to separate.
  const canGroup = useMemo(
    () => new Set(groups.map((g) => g.trade ?? '')).size > 1,
    [groups],
  );

  const stats = useMemo(() => {
    let confirmed = 0;
    let noRate = 0;
    for (const g of groups) {
      if (g.status === 'confirmed' || g.status === 'overridden') confirmed += 1;
      if (g.chosen_code == null && g.status !== 'skipped') noRate += 1;
    }
    return { confirmed, noRate };
  }, [groups]);

  // Live match progress: a group is "done" once it has been ranked (score or
  // a chosen code) or the user has already resolved it. Since the page
  // invalidates the group list after every batch, this advances as the match
  // runs - the bar the founder asked for, instead of a frozen skeleton.
  const matchProgress = useMemo(() => {
    const total = groups.length;
    if (total === 0) return { total: 0, done: 0, pct: 0 };
    const done = groups.filter(
      (g) =>
        g.score != null ||
        g.chosen_code != null ||
        g.status === 'confirmed' ||
        g.status === 'overridden' ||
        g.status === 'skipped',
    ).length;
    return { total, done, pct: Math.round((done / total) * 100) };
  }, [groups]);

  // Only show the bare skeleton on the very first load, before any group
  // exists. Once groups are present we render them and stream match results
  // in, with the progress bar on top.
  if (loading && groups.length === 0) {
    return (
      <div className="space-y-2.5">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-20 animate-pulse rounded-lg border border-border-light bg-surface-muted"
          />
        ))}
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <EmptyState
        icon={<Layers3 className="h-6 w-6" />}
        title={t('aiest.match.empty_title', { defaultValue: 'Nothing to match' })}
        description={t('aiest.match.empty_desc', {
          defaultValue: 'No groups reached the matching stage.',
        })}
      />
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-content-secondary">
        {t('aiest.match.help', {
          defaultValue:
            'Each group is matched against the catalogue with semantic search and ranking. Accept the suggested rate, pick an alternative, re-query for a better fit, or skip. Low-confidence rows are shown first.',
        })}
      </p>

      {/* Live match progress. Streams while the batched pass runs so the
          stage never looks frozen. */}
      {matching && (
        <div className="rounded-lg border border-oe-blue/30 bg-oe-blue/5 px-3 py-2.5">
          <div className="flex items-center gap-2 text-sm font-medium text-content-primary">
            <Loader2 className="h-4 w-4 animate-spin text-oe-blue" />
            {matchProgress.total > 0
              ? t('aiest.match.progress_n', {
                  defaultValue: 'Matching {{done}} of {{total}} groups…',
                  done: matchProgress.done,
                  total: matchProgress.total,
                })
              : t('aiest.match.progress', { defaultValue: 'Matching groups…' })}
            {matchProgress.total > 0 && (
              <span className="ml-auto tabular-nums text-xs text-content-secondary">
                {matchProgress.pct}%
              </span>
            )}
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-muted">
            <div
              className="h-full rounded-full bg-oe-blue transition-all duration-500"
              style={{ width: `${Math.max(6, matchProgress.pct)}%` }}
            />
          </div>
        </div>
      )}

      {/* Honest disclosure: large group sets are matched in batches so the
          vector search never blocks the UI. Match-all iterates until every
          group has been processed. */}
      {groups.length > matchGroupCap && (
        <div className="flex items-start gap-2 rounded-lg border border-border-light bg-surface-muted px-3 py-2 text-xs text-content-secondary">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t('aiest.match_batch_notice', {
            defaultValue:
              'Matching {{total}} groups runs in batches of {{cap}}. Every group is matched - the batches just keep the search responsive.',
            total: groups.length,
            cap: matchGroupCap,
          })}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-content-secondary">
          {t('aiest.match.confirmed_n', {
            defaultValue: '{{c}} of {{total}} confirmed',
            c: stats.confirmed,
            total: groups.length,
          })}
        </span>
        {stats.noRate > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-xs text-rose-700 dark:bg-rose-900/40 dark:text-rose-200">
            <AlertTriangle className="h-3 w-3" />
            {t('aiest.match.no_rate_n', {
              defaultValue: '{{n}} with no rate',
              n: stats.noRate,
            })}
          </span>
        )}

        {canGroup && (
          <button
            type="button"
            onClick={() => setGroupByTrade((v) => !v)}
            aria-pressed={groupByTrade}
            className={clsx(
              'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition',
              groupByTrade
                ? 'border-oe-blue bg-oe-blue/5 text-oe-blue'
                : 'border-border text-content-secondary hover:bg-surface-secondary',
            )}
          >
            <ListFilter className="h-3 w-3" />
            {t('aiest.match.group_by_trade', { defaultValue: 'Group by trade' })}
          </button>
        )}

        {/* Bulk-confirm with threshold control */}
        <div className="ml-auto flex items-center gap-2">
          <label htmlFor="aiest-bulk-threshold" className="text-xs text-content-secondary">
            {t('aiest.match.threshold', { defaultValue: 'Threshold' })}
          </label>
          <input
            id="aiest-bulk-threshold"
            type="range"
            min={50}
            max={99}
            step={1}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-28 accent-oe-blue"
          />
          <span className="w-9 text-right text-xs font-medium tabular-nums text-content-primary">
            {threshold}%
          </span>
          <Button
            variant="primary"
            size="sm"
            icon={<Check className="h-3.5 w-3.5" />}
            loading={bulkPending}
            onClick={() => onBulkAccept(threshold / 100)}
          >
            {t('aiest.match.accept_above', {
              defaultValue: 'Accept above {{n}}%',
              n: threshold,
            })}
          </Button>
        </div>
      </div>

      {(() => {
        const renderCard = (g: GroupSummary) => (
          <MatchCard
            key={g.id}
            runId={runId}
            group={g}
            locale={locale}
            aiConnected={aiConnected}
            onAccept={onAccept}
            onSkip={onSkip}
            onRematch={onRematch}
            rematching={rematchingId === g.id}
            onOpenAlternatives={setAltGroupId}
          />
        );

        if (!groupByTrade || !canGroup) {
          return <div className="space-y-2.5">{ordered.map(renderCard)}</div>;
        }

        return (
          <div className="space-y-3">
            {tradeSections.map((section) => {
              const sectionKey = section.trade ?? '__none__';
              // Sections with open items start expanded; resolved trades start
              // collapsed so the user's eye lands on what still needs work.
              const collapsed =
                collapsedTrades[sectionKey] ?? section.attention === 0;
              const title = section.trade
                ? t(`aiest.trade.${section.trade}`, {
                    defaultValue: humanizeTrade(section.trade),
                  })
                : t('aiest.match.no_trade', { defaultValue: 'Other' });
              return (
                <div
                  key={sectionKey}
                  className="overflow-hidden rounded-lg border border-border-light"
                >
                  <button
                    type="button"
                    onClick={() =>
                      setCollapsedTrades((prev) => ({
                        ...prev,
                        [sectionKey]: !collapsed,
                      }))
                    }
                    aria-expanded={!collapsed}
                    className="flex w-full items-center gap-2 bg-surface-muted px-3 py-2 text-left"
                  >
                    {collapsed ? (
                      <ChevronRight className="h-4 w-4 shrink-0 text-content-tertiary" />
                    ) : (
                      <ChevronDown className="h-4 w-4 shrink-0 text-content-tertiary" />
                    )}
                    <Layers3 className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />
                    <span className="text-sm font-medium text-content-primary">
                      {title}
                    </span>
                    <span className="text-xs text-content-tertiary">
                      {section.groups.length}
                    </span>
                    {section.attention > 0 && (
                      <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-200">
                        <AlertTriangle className="h-3 w-3" />
                        {t('aiest.match.attention_n', {
                          defaultValue: '{{n}} to review',
                          n: section.attention,
                        })}
                      </span>
                    )}
                  </button>
                  {!collapsed && (
                    <div className="space-y-2.5 p-2.5">
                      {section.groups.map(renderCard)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        );
      })()}

      {altGroupId && (
        <AlternativesDrawer
          runId={runId}
          groupId={altGroupId}
          locale={locale}
          open
          onClose={() => setAltGroupId(null)}
          onUse={(candidateId) => {
            onAccept(altGroupId, candidateId);
            setAltGroupId(null);
          }}
        />
      )}
    </div>
  );
}
