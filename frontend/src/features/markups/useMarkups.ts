/**
 * useMarkups - React-Query hook that loads markups for a single
 * (document, page) pair and exposes a per-markup comment-count map for
 * badge rendering.
 *
 * Designed to be called from any takeoff overlay (PDF or DWG) so the
 * persistence wiring lives in one hook instead of being duplicated per
 * caller.
 */

import { useMemo } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';

import {
  fetchMarkupsByPage,
  fetchMarkupComments,
  type Markup,
} from './api';

interface UseMarkupsArgs {
  projectId: string | null | undefined;
  documentId: string | null | undefined;
  pageNumber: number | null | undefined;
  /** Disable the query (e.g. while the page is still loading the document). */
  enabled?: boolean;
}

export interface UseMarkupsResult {
  markups: Markup[];
  /** ``markup_id -> comment_count``. Empty until the per-markup queries
   *  resolve; falls back to 0 for unseen ids. */
  commentCounts: Record<string, number>;
  /** Set of markup ids whose comment fetch errored. The UI can mark the
   *  badge as unknown (e.g. a muted dash) instead of silently showing 0,
   *  which would hide the fact that comments exist. */
  commentCountErrors: Set<string>;
  isLoading: boolean;
  error: Error | null;
}

const MARKUPS_QUERY_KEY = ['markups-by-page'] as const;
const COUNTS_QUERY_KEY = ['markup-comment-counts'] as const;

/**
 * Hook contract:
 *  - When ``projectId``, ``documentId``, or ``pageNumber`` is missing/null,
 *    returns an empty list and stays disabled (no network).
 *  - Once markups arrive, fans out per-markup comments fetches in
 *    parallel via ``useQueries`` and collapses them into a count map.
 */
export function useMarkups({
  projectId,
  documentId,
  pageNumber,
  enabled = true,
}: UseMarkupsArgs): UseMarkupsResult {
  const ready =
    enabled &&
    !!projectId &&
    !!documentId &&
    typeof pageNumber === 'number' &&
    pageNumber > 0;

  const markupsQuery = useQuery<Markup[]>({
    queryKey: [
      ...MARKUPS_QUERY_KEY,
      projectId ?? '',
      documentId ?? '',
      pageNumber ?? 0,
    ],
    queryFn: () =>
      fetchMarkupsByPage(projectId as string, documentId as string, pageNumber as number),
    enabled: ready,
    staleTime: 30_000,
  });

  const markups = markupsQuery.data ?? [];

  const commentQueries = useQueries({
    queries: markups.map((m) => ({
      queryKey: [...COUNTS_QUERY_KEY, m.id],
      queryFn: () => fetchMarkupComments(m.id),
      enabled: ready,
      staleTime: 30_000,
    })),
  });

  const { commentCounts, commentCountErrors } = useMemo(() => {
    const counts: Record<string, number> = {};
    const errors = new Set<string>();
    markups.forEach((m, idx) => {
      const q = commentQueries[idx];
      const data = q?.data;
      // React Query keeps the last good ``data`` on a refetch error, so a
      // populated array is still the truthy count. Only when there is no
      // data AND the query errored do we flag the id as unknown rather
      // than silently reporting 0 (which would hide that comments exist).
      if (Array.isArray(data)) {
        counts[m.id] = data.length;
      } else {
        // In-flight queries report 0; errored-with-no-data are flagged.
        counts[m.id] = 0;
        if (q?.isError) {
          errors.add(m.id);
        }
      }
    });
    return { commentCounts: counts, commentCountErrors: errors };
  }, [markups, commentQueries]);

  const error =
    (markupsQuery.error as Error | undefined) ??
    (commentQueries.find((q) => q.error)?.error as Error | undefined) ??
    null;

  return {
    markups,
    commentCounts,
    commentCountErrors,
    isLoading: markupsQuery.isLoading,
    error,
  };
}
