// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** React Query hooks for the W3 file-search feature. */

import { useEffect, useState } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  indexFile,
  reindexProject,
  removeFromIndex,
  searchContent,
} from './api';
import type {
  FileKind,
  IndexFileRequest,
  ReindexResponse,
  SearchMode,
  SearchResponse,
} from './types';

const KEY_SEARCH = 'file-search-results';
const DEBOUNCE_MS = 300;

/** Tiny string-only debouncer (no lodash dependency). */
function useDebouncedValue(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(handle);
  }, [value, ms]);
  return debounced;
}

/** Content/filename search hook with 300 ms debounce.
 *
 * Always returns a `SearchResponse` shape (empty when q is blank) so
 * the consumer can render unconditionally. `placeholderData:
 * keepPreviousData` keeps the previous result on-screen while the next
 * one loads — no flicker between keystrokes.
 */
export function useContentSearch(
  projectId: string | null | undefined,
  q: string,
  kind?: FileKind,
  mode: SearchMode = 'content',
) {
  const debouncedQ = useDebouncedValue(q, DEBOUNCE_MS);
  const trimmed = debouncedQ.trim();

  return useQuery<SearchResponse>({
    queryKey: [KEY_SEARCH, projectId, trimmed, mode, kind ?? null],
    queryFn: () => searchContent(projectId as string, trimmed, mode, kind),
    enabled: Boolean(projectId) && trimmed.length > 0,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

/** Mutation: index a single file (call after a successful upload). */
export function useIndexFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: IndexFileRequest) => indexFile(payload),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: [KEY_SEARCH, vars.project_id] });
    },
  });
}

/** Mutation: re-OCR every file in the project. */
export function useReindexProject() {
  const qc = useQueryClient();
  return useMutation<ReindexResponse, Error, string>({
    mutationFn: (projectId: string) => reindexProject(projectId),
    onSuccess: (_, projectId) => {
      qc.invalidateQueries({ queryKey: [KEY_SEARCH, projectId] });
    },
  });
}

/** Mutation: drop a single file from the index (called by delete dispatchers). */
export function useRemoveFromIndex() {
  const qc = useQueryClient();
  return useMutation<
    void,
    Error,
    { projectId: string; fileId: string; kind?: FileKind }
  >({
    mutationFn: ({ projectId, fileId, kind }) =>
      removeFromIndex(projectId, fileId, kind),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: [KEY_SEARCH, vars.projectId] });
    },
  });
}

export const fileSearchKeys = {
  search: KEY_SEARCH,
};
