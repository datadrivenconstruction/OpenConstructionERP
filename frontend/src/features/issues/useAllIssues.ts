// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Unified Issue Hub - aggregation hook.
//
// Fetches every available issue source for a project in parallel, normalizes
// and merges them, and returns the sorted list plus per-source counts and
// per-source warnings. One source failing never blanks the page: its slot
// becomes a small warning and the other sources still render.

import { useMemo } from 'react';
import { useQueries } from '@tanstack/react-query';

import { fetchMarkups } from '../markups/api';
import { fetchPunchItems } from '../punchlist/api';
import { fetchNCRs } from '../ncr/api';
import { clashApi } from '../clash/api';
import { fetchNeighbourIssues } from '../site-logistics/api';

import { bcfSourceAvailable, fetchBcfTopicsSafe } from './bcfSource';
import {
  mapMarkup,
  mapPunch,
  mapNcr,
  mapClashIssue,
  mapBcfTopic,
  mapNeighbourIssue,
  mapEach,
  sortIssues,
  type IssueSource,
  type IssueSortKey,
  type UnifiedIssue,
} from './issueSources';

/* --- Return shape --------------------------------------------------------- */

export type SourceStatus = 'ok' | 'error' | 'disabled';

export interface SourceState {
  source: IssueSource;
  /** Count of open issues this source contributed. */
  count: number;
  status: SourceStatus;
  /** Error message when `status === 'error'`. */
  error?: string;
}

export interface SourceWarning {
  source: IssueSource;
  message: string;
}

export interface UseAllIssuesResult {
  /** Normalized, merged, sorted list of open issues. */
  issues: UnifiedIssue[];
  /** Open-issue count per source (0 for a failed or disabled source). */
  bySource: Record<IssueSource, number>;
  /** Per-source status. */
  sources: SourceState[];
  /** Non-fatal per-source failures (the page still renders the rest). */
  warnings: SourceWarning[];
  /** True while any enabled source is doing its first load. */
  isLoading: boolean;
  /** True only when every enabled source failed (nothing to show). */
  isError: boolean;
  /** Refetch every source. */
  refetch: () => void;
}

/** Display order for the per-source chips + state list. */
export const SOURCE_ORDER: IssueSource[] = ['punch', 'ncr', 'clash', 'neighbour', 'markup', 'bcf'];

/* --- Constants ------------------------------------------------------------ */

// Generous page sizes so the hub shows the real backlog, not the first screen.
const MARKUP_LIMIT = 200;
const CLASH_LIMIT = 200;
// The punch list route caps `limit` at 100 and rejects anything above it, so
// this one cannot match its siblings. It used to send no limit at all and
// silently took the server default of 50.
const PUNCH_LIMIT = 100;
// The NCR route has the same 100 ceiling, and this slot was the one still
// sending no limit at all: the hub's "ncr" chip counted the server default
// of 50 and called it the backlog.
const NCR_LIMIT = 100;

/** Minimal read view of a react-query result, enough to build source state. */
interface ResultLike {
  isError?: boolean;
  error?: unknown;
}

function errMessage(e: unknown): string {
  if (e instanceof Error && e.message) return e.message;
  return 'Could not load this source';
}

function buildSourceState(
  source: IssueSource,
  count: number,
  res: ResultLike | undefined,
  disabled = false,
): SourceState {
  if (disabled) return { source, count, status: 'disabled' };
  if (res?.isError) return { source, count, status: 'error', error: errMessage(res.error) };
  return { source, count, status: 'ok' };
}

/* --- Hook ----------------------------------------------------------------- */

/**
 * Aggregate all issue sources for a project.
 *
 * @param projectId Active project id (empty string disables all queries).
 * @param sortKey   How to order the merged list. Defaults to `priority`.
 */
export function useAllIssues(
  projectId: string,
  sortKey: IssueSortKey = 'priority',
): UseAllIssuesResult {
  const enabled = !!projectId;

  const results = useQueries({
    queries: [
      {
        queryKey: ['issues-hub', 'markups', projectId],
        queryFn: () => fetchMarkups(projectId, { status: 'active', limit: MARKUP_LIMIT }),
        enabled,
        staleTime: 30_000,
      },
      {
        queryKey: ['issues-hub', 'punch', projectId],
        queryFn: () => fetchPunchItems(projectId, { limit: PUNCH_LIMIT }),
        enabled,
        staleTime: 30_000,
      },
      {
        queryKey: ['issues-hub', 'ncr', projectId],
        queryFn: () => fetchNCRs({ project_id: projectId, limit: NCR_LIMIT }),
        enabled,
        staleTime: 30_000,
      },
      {
        queryKey: ['issues-hub', 'clash', projectId],
        queryFn: () => clashApi.issues(projectId, { limit: CLASH_LIMIT }),
        enabled,
        staleTime: 30_000,
      },
      {
        // The neighbour-issues route returns the whole register (no paging), so
        // the hub sees every open complaint, not a first page.
        queryKey: ['issues-hub', 'neighbour', projectId],
        queryFn: () => fetchNeighbourIssues(projectId),
        enabled,
        staleTime: 30_000,
      },
      {
        queryKey: ['issues-hub', 'bcf', projectId],
        queryFn: () => fetchBcfTopicsSafe(projectId),
        // Only run when a BCF api module is actually present in the build.
        enabled: enabled && bcfSourceAvailable,
        staleTime: 30_000,
      },
    ],
  });

  const markupRes = results[0];
  const punchRes = results[1];
  const ncrRes = results[2];
  const clashRes = results[3];
  const neighbourRes = results[4];
  const bcfRes = results[5];

  const derived = useMemo(() => {
    // Each mapEach isolates per-item failures; a bad row is dropped alone.
    const markups = mapEach(markupRes?.data, mapMarkup);
    const punch = mapEach(punchRes?.data?.items, mapPunch);
    const ncr = mapEach(ncrRes?.data?.items, mapNcr);
    const clash = mapEach(clashRes?.data?.items, mapClashIssue);
    const neighbour = mapEach(neighbourRes?.data?.items, mapNeighbourIssue);
    const bcf = bcfSourceAvailable ? mapEach(bcfRes?.data, mapBcfTopic) : [];

    const bySource: Record<IssueSource, number> = {
      markup: markups.length,
      punch: punch.length,
      ncr: ncr.length,
      clash: clash.length,
      neighbour: neighbour.length,
      bcf: bcf.length,
    };

    const merged = sortIssues([...punch, ...ncr, ...clash, ...neighbour, ...markups, ...bcf], sortKey);

    const sources: SourceState[] = [
      buildSourceState('punch', bySource.punch, punchRes),
      buildSourceState('ncr', bySource.ncr, ncrRes),
      buildSourceState('clash', bySource.clash, clashRes),
      buildSourceState('neighbour', bySource.neighbour, neighbourRes),
      buildSourceState('markup', bySource.markup, markupRes),
      buildSourceState('bcf', bySource.bcf, bcfRes, !bcfSourceAvailable),
    ];

    const warnings: SourceWarning[] = sources
      .filter((s) => s.status === 'error')
      .map((s) => ({ source: s.source, message: s.error ?? 'Could not load this source' }));

    return { issues: merged, bySource, sources, warnings };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    markupRes?.data,
    punchRes?.data,
    ncrRes?.data,
    clashRes?.data,
    neighbourRes?.data,
    bcfRes?.data,
    markupRes?.isError,
    punchRes?.isError,
    ncrRes?.isError,
    clashRes?.isError,
    neighbourRes?.isError,
    bcfRes?.isError,
    sortKey,
  ]);

  // The enabled queries (BCF only counts when its module is present). BCF is
  // the last query, so dropping it is dropping the tail.
  const enabledResults = bcfSourceAvailable ? results : results.slice(0, results.length - 1);

  const isLoading = enabledResults.some((r) => r?.isLoading === true);
  // Page-level error only when every enabled source failed: there is genuinely
  // nothing to show. A partial failure stays a per-source warning.
  const isError =
    enabledResults.length > 0 && enabledResults.every((r) => r?.isError === true);

  const refetch = () => {
    for (const r of results) r?.refetch?.();
  };

  return {
    issues: derived.issues,
    bySource: derived.bySource,
    sources: derived.sources,
    warnings: derived.warnings,
    isLoading,
    isError,
    refetch,
  };
}
