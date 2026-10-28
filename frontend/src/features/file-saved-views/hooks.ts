// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the file-saved-views (W5) module.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  createSavedView,
  deleteSavedView,
  duplicateSavedView,
  fetchSavedViews,
  updateSavedView,
  useSavedView as useSavedViewApi,
} from './api';
import type {
  FilterSnapshot,
  SavedViewCreatePayload,
  SavedViewListResponse,
  SavedViewResponse,
  SavedViewUpdatePayload,
} from './types';

const KEY = 'file-saved-views';

export const savedViewKeys = {
  list: KEY,
};

export function useSavedViews(projectId: string | null | undefined) {
  return useQuery<SavedViewListResponse>({
    queryKey: [KEY, projectId ?? null],
    queryFn: () => fetchSavedViews(projectId),
    staleTime: 30_000,
  });
}

export function useCreateView(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: SavedViewCreatePayload) => createSavedView(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY, projectId ?? null] });
    },
  });
}

export function useUpdateView(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: SavedViewUpdatePayload }) =>
      updateSavedView(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY, projectId ?? null] });
    },
  });
}

export function useDeleteView(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteSavedView(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY, projectId ?? null] });
    },
  });
}

export function useDuplicateView(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => duplicateSavedView(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY, projectId ?? null] });
    },
  });
}

/**
 * Returns a callback that reproduces a view's filter in the URL query
 * string and bumps its ``use_count`` server-side. The caller controls
 * the base path so the same hook works for ``/files`` and the
 * cross-project search results page.
 */
export function useApplyView(basePath = '/files') {
  const navigate = useNavigate();
  const qc = useQueryClient();
  return useCallback(
    async (view: SavedViewResponse) => {
      // Best-effort telemetry — never block navigation on it.
      try {
        await useSavedViewApi(view.id);
        qc.invalidateQueries({ queryKey: [KEY] });
      } catch {
        // Swallow — telemetry must never gate the action.
      }
      const qs = serializeFilter(view.filter_json);
      navigate(qs ? `${basePath}?${qs}` : basePath);
    },
    [navigate, qc, basePath],
  );
}

/** Serialise a FilterSnapshot into a flat URLSearchParams string. */
export function serializeFilter(filter: FilterSnapshot): string {
  const params = new URLSearchParams();
  if (filter.kind) params.set('kind', String(filter.kind));
  if (filter.q) params.set('q', String(filter.q));
  if (filter.sort) params.set('sort', String(filter.sort));
  if (filter.extension) params.set('extension', String(filter.extension));
  if (Array.isArray(filter.tag_ids) && filter.tag_ids.length > 0) {
    params.set('tag_ids', filter.tag_ids.join(','));
  }
  if (filter.date_range && typeof filter.date_range === 'object') {
    const dr = filter.date_range as Record<string, unknown>;
    if (typeof dr.from === 'string') params.set('date_from', dr.from);
    if (typeof dr.to === 'string') params.set('date_to', dr.to);
  }
  const ck = filter.custom_keys;
  if (ck && typeof ck === 'object') {
    for (const [k, v] of Object.entries(ck)) {
      if (v === undefined || v === null) continue;
      params.set(k, String(v));
    }
  }
  return params.toString();
}
