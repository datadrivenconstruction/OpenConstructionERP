// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the project handbook screens.

import { useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { useToastStore } from '@/stores/useToastStore';

import {
  getChapter,
  getDataRoom,
  getHandbook,
  handbookErrorCode,
  handbookKeys,
  listFindings,
} from './api';
import { refusalText, type TFn } from './labels';

/** The handbook, or null when the project has none yet (404 `handbook_missing`), which is an empty state. */
export function useHandbook(projectId: string) {
  return useQuery({
    queryKey: handbookKeys.handbook(projectId),
    queryFn: async () => {
      try {
        return await getHandbook(projectId);
      } catch (err) {
        // Only `handbook_missing` is the empty state: a bare 404 also means the project is not visible.
        if (handbookErrorCode(err) === 'handbook_missing') return null;
        throw err;
      }
    },
    enabled: !!projectId,
    retry: false,
  });
}

export function useChapter(projectId: string, code: string | null) {
  return useQuery({
    queryKey: handbookKeys.chapter(projectId, code ?? ''),
    queryFn: () => getChapter(projectId, code as string),
    enabled: !!projectId && !!code,
    retry: false,
  });
}

export function useFindings(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: handbookKeys.findings(projectId),
    queryFn: () => listFindings(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useDataRoom(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: handbookKeys.dataRoom(projectId),
    queryFn: () => getDataRoom(projectId),
    enabled: !!projectId && enabled,
    retry: false,
  });
}

/** After any write: every query of the project is stale, because findings and statuses cross the screens. */
export function useInvalidateHandbook(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => qc.invalidateQueries({ queryKey: handbookKeys.project(projectId) }), [qc, projectId]);
}

/**
 * A write whose refusal the reader sees in the server's own words. The client
 * does not predict permissions beyond the capability flags it was sent.
 */
export function useHandbookAction<TArgs = void, TResult = unknown>(
  fn: (args: TArgs) => Promise<TResult>,
  onDone?: (result: TResult, args: TArgs) => void,
) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  return useMutation({
    mutationFn: fn,
    onSuccess: (result, args) => onDone?.(result, args),
    onError: (err) => addToast({ type: 'error', title: refusalText(t as TFn, err) }),
  });
}
