// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the plant register screens, plus the two pieces of
// context every screen needs: how to name a catalogue entry in the reader's
// language and how to name a person.

import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { listRoster } from '@/features/teams/api';
import { useAuthStore } from '@/stores/useAuthStore';

import {
  getCatalogue,
  getFrameSummary,
  getLimitMatrix,
  getReadiness,
  getSettings,
  listFindings,
  listItems,
  listItServices,
  listLimits,
  listPapers,
  listQuotes,
  listSlots,
  listSpares,
  plantKeys,
} from './api';
import type { LabelContext } from './labels';

/** The pinned catalogue. It changes only when the project pins another one, so it is read once. */
export function usePlantCatalogue(projectId: string) {
  return useQuery({
    queryKey: plantKeys.catalogue(projectId),
    queryFn: () => getCatalogue(projectId),
    enabled: !!projectId,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

/** The project's settings; read for the capability flags the server decides. */
export function usePlantSettings(projectId: string) {
  return useQuery({
    queryKey: plantKeys.settings(projectId),
    queryFn: () => getSettings(projectId),
    enabled: !!projectId,
    retry: false,
  });
}

export function usePlantItems(projectId: string) {
  return useQuery({
    queryKey: plantKeys.items(projectId),
    queryFn: () => listItems(projectId),
    enabled: !!projectId,
    retry: false,
  });
}

export function useQuotes(projectId: string, itemId: string) {
  return useQuery({
    queryKey: plantKeys.quotes(projectId, itemId),
    queryFn: () => listQuotes(projectId, itemId).then((p) => p.items),
    enabled: !!projectId && !!itemId,
  });
}

export function useSlots(projectId: string, itemId: string) {
  return useQuery({
    queryKey: plantKeys.slots(projectId, itemId),
    queryFn: () => listSlots(projectId, itemId).then((p) => p.items),
    enabled: !!projectId && !!itemId,
  });
}

export function usePapers(projectId: string, itemId: string) {
  return useQuery({
    queryKey: plantKeys.papers(projectId, itemId),
    queryFn: () => listPapers(projectId, itemId).then((p) => p.items),
    enabled: !!projectId && !!itemId,
  });
}

export function useLimits(projectId: string, itemId: string) {
  return useQuery({
    queryKey: plantKeys.limits(projectId, itemId),
    queryFn: () => listLimits(projectId, itemId).then((p) => p.items),
    enabled: !!projectId && !!itemId,
  });
}

export function useSpares(projectId: string, itemId: string) {
  return useQuery({
    queryKey: plantKeys.spares(projectId, itemId),
    queryFn: () => listSpares(projectId, itemId).then((p) => p.items),
    enabled: !!projectId && !!itemId,
  });
}

export function useLimitMatrix(projectId: string, enabled = true) {
  return useQuery({
    queryKey: plantKeys.matrix(projectId),
    queryFn: () => getLimitMatrix(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useItServices(projectId: string, enabled = true) {
  return useQuery({
    queryKey: plantKeys.itServices(projectId),
    queryFn: () => listItServices(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useFrameSummary(projectId: string, enabled = true) {
  return useQuery({
    queryKey: plantKeys.frame(projectId),
    queryFn: () => getFrameSummary(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useReadiness(projectId: string, enabled = true) {
  return useQuery({
    queryKey: plantKeys.readiness(projectId),
    queryFn: () => getReadiness(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useFindings(projectId: string, enabled = true) {
  return useQuery({
    queryKey: plantKeys.validation(projectId),
    queryFn: () => listFindings(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

/** Refetch everything the register holds for the project after any write: one quote moves dates, float and readiness. */
export function useInvalidatePlant(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => qc.invalidateQueries({ queryKey: plantKeys.project(projectId) }), [qc, projectId]);
}

/** Names for user ids, read from the project roster under the same key the people picker caches it. */
export function usePeopleNames(projectId: string): (userId: string | null | undefined) => string | null {
  const { data: roster = [] } = useQuery({
    queryKey: ['roster', projectId],
    queryFn: () => listRoster(projectId).then((page) => page.items),
    enabled: !!projectId,
    staleTime: 60_000,
  });
  const userId = useAuthStore((s) => s.userId);
  const fullName = useAuthStore((s) => s.userFullName);
  return useMemo(() => {
    const names = new Map<string, string>();
    for (const m of roster) {
      const name = m.display_name || m.email;
      if (m.user_id && name) names.set(m.user_id, name);
    }
    if (userId && fullName && !names.has(userId)) names.set(userId, fullName);
    return (id) => (id ? names.get(id) ?? null : null);
  }, [roster, userId, fullName]);
}

export function useLabelContext(): LabelContext {
  const { t, i18n } = useTranslation();
  return useMemo(
    () => ({
      t: t as LabelContext['t'],
      language: i18n.language || 'en',
      exists: (key: string) => (typeof i18n.exists === 'function' ? i18n.exists(key) : false),
    }),
    [t, i18n],
  );
}
