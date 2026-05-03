// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * React Query hooks for the translation API.
 *
 * The status endpoint is exposed as a polling query: 5 s while there
 * are in-flight tasks, 30 s when idle.  The download trigger is a
 * mutation that invalidates the status query on success so the
 * progress card lights up immediately.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';
import {
  getTranslationStatus,
  triggerLookupDownload,
  translateOne,
} from './api';
import type {
  DownloadRequestBody,
  DownloadResponse,
  StatusResponse,
  TranslateRequestBody,
  TranslateResponse,
} from './types';

/** Stable query key so other features (e.g. MatchSuggestionsPanel) can
 *  invalidate the status without importing the hook. */
export const TRANSLATION_STATUS_QUERY_KEY = ['translation', 'status'] as const;

/**
 * Polling query for ``GET /lookup-tables/status``.
 *
 * Refetch interval adapts to activity:
 *   - 5 s while at least one task is queued or running
 *   - 30 s when the queue is empty (so the panel stays mostly fresh
 *     without hammering the API).
 *
 * The endpoint is cheap (filesystem stat + cache rowcount), so the
 * adaptive interval is mainly to keep idle browser tabs quiet.
 */
export function useTranslationStatus(): UseQueryResult<StatusResponse, Error> {
  return useQuery<StatusResponse, Error>({
    queryKey: TRANSLATION_STATUS_QUERY_KEY,
    queryFn: getTranslationStatus,
    // ``refetchInterval`` receives the React Query ``Query`` instance; we
    // peek at the latest data to decide.  The 5 s/30 s split mirrors the
    // pattern documented in the Phase 3 spec.
    refetchInterval: (query) => {
      const data = query.state.data as StatusResponse | undefined;
      const inFlight = data?.in_flight ?? [];
      return inFlight.length > 0 ? 5_000 : 30_000;
    },
    refetchOnWindowFocus: true,
    staleTime: 2_000,
  });
}

/**
 * Mutation that POSTs a download trigger.  On success we invalidate the
 * status query so the in-flight panel renders right away.
 */
export function useTriggerDownload() {
  const qc = useQueryClient();
  return useMutation<DownloadResponse, Error, DownloadRequestBody>({
    mutationFn: triggerLookupDownload,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TRANSLATION_STATUS_QUERY_KEY });
    },
  });
}

/** QA / debug mutation — translate one term through the cascade. */
export function useTranslateOne() {
  return useMutation<TranslateResponse, Error, TranslateRequestBody>({
    mutationFn: translateOne,
  });
}
