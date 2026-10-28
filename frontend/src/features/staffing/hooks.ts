// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the staffing screens, plus the two pieces of context
// every screen needs: how to name a catalogue item in the reader's language
// and how to name a person by user id.

import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { listRoster } from '@/features/teams/api';
import { useAuthStore } from '@/stores/useAuthStore';

import {
  getAccessLog,
  getCompliance,
  getFile,
  getOrgChart,
  getPinnedCatalogue,
  getPlan,
  getPlannedVsActual,
  getUpcoming,
  listCatalogues,
  listFiles,
  listHandovers,
  listPlanFindings,
  listPositions,
  staffingErrorCode,
  staffingKeys,
} from './api';
import type { LabelContext } from './labels';

/** The plan, or null when the project has none yet (404 `plan_missing`), which is an empty state and not an error. */
export function useStaffingPlan(projectId: string) {
  return useQuery({
    queryKey: staffingKeys.plan(projectId),
    queryFn: async () => {
      try {
        return await getPlan(projectId);
      } catch (err) {
        // Only `plan_missing` is the empty state. A bare 404 also means the
        // project is not visible to this user, and that must read as an error.
        if (staffingErrorCode(err) === 'plan_missing') return null;
        throw err;
      }
    },
    enabled: !!projectId,
    retry: false,
  });
}

export function useStaffingCatalogues(enabled = true) {
  return useQuery({
    queryKey: staffingKeys.catalogues,
    queryFn: () => listCatalogues().then((page) => page.items),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function usePinnedCatalogue(projectId: string, enabled = true) {
  return useQuery({
    queryKey: staffingKeys.catalogue(projectId),
    queryFn: () => getPinnedCatalogue(projectId),
    enabled: !!projectId && enabled,
  });
}

export function usePlanFindings(projectId: string, enabled = true) {
  return useQuery({
    queryKey: staffingKeys.findings(projectId),
    queryFn: () => listPlanFindings(projectId).then((page) => ({ findings: page.items, restrictedPeople: page.restricted_people ?? 0 })),
    enabled: !!projectId && enabled,
  });
}

export function usePositions(projectId: string, enabled = true) {
  return useQuery({
    queryKey: staffingKeys.positions(projectId),
    queryFn: () => listPositions(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useHandovers(projectId: string, enabled = true) {
  return useQuery({
    queryKey: staffingKeys.handovers(projectId),
    queryFn: () => listHandovers(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useOrgChart(projectId: string, enabled = true) {
  return useQuery({
    queryKey: staffingKeys.orgChart(projectId),
    queryFn: () => getOrgChart(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useCompliance(projectId: string, enabled = true) {
  return useQuery({
    queryKey: staffingKeys.compliance(projectId),
    queryFn: () => getCompliance(projectId),
    enabled: !!projectId && enabled,
  });
}

export function usePlannedVsActual(projectId: string, enabled = true) {
  return useQuery({
    queryKey: staffingKeys.plannedVsActual(projectId),
    queryFn: () => getPlannedVsActual(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useUpcoming(projectId: string, enabled = true) {
  return useQuery({
    queryKey: staffingKeys.upcoming(projectId),
    queryFn: () => getUpcoming(projectId),
    enabled: !!projectId && enabled,
  });
}

export function usePersonnelFiles(projectId: string, enabled = true) {
  return useQuery({
    queryKey: staffingKeys.files(projectId),
    queryFn: () => listFiles(projectId).then((page) => ({ files: page.items, candidates: page.candidates ?? [] })),
    enabled: !!projectId && enabled,
  });
}

/**
 * One personnel file.
 *
 * The server writes an audit row for every read, so this query is fetched
 * once when the reader opens the file and again only after the reader changes
 * it. It never refetches on window focus or on remount, and nothing prefetches
 * it; otherwise "who opened this file" would fill with tab switches.
 */
export function usePersonnelFile(projectId: string, fileId: string | null) {
  return useQuery({
    queryKey: staffingKeys.file(projectId, fileId ?? ''),
    queryFn: () => getFile(projectId, fileId as string),
    enabled: !!projectId && !!fileId,
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: false,
  });
}

/** The access log, loaded only when the reader asks for it: asking is itself a logged read. */
export function useAccessLog(projectId: string, fileId: string, enabled: boolean) {
  return useQuery({
    queryKey: staffingKeys.accessLog(projectId, fileId),
    queryFn: () => getAccessLog(projectId, fileId).then((page) => page.items),
    enabled: !!projectId && !!fileId && enabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

/** Refetch what a plan, position or assignment write can change. Open personnel files are left alone. */
export function useInvalidateStaffing(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => qc.invalidateQueries({ queryKey: staffingKeys.project(projectId) }), [qc, projectId]);
}

/** After a write to one personnel file: reload that file and the lists that summarise it. */
export function useInvalidateFile(projectId: string, fileId: string) {
  const qc = useQueryClient();
  return useCallback(() => {
    void qc.invalidateQueries({ queryKey: staffingKeys.file(projectId, fileId), exact: true });
    return qc.invalidateQueries({ queryKey: staffingKeys.project(projectId) });
  }, [qc, projectId, fileId]);
}

/** The project roster, under the same key the people picker caches it. */
export function useRoster(projectId: string, enabled = true) {
  return useQuery({
    queryKey: ['roster', projectId],
    queryFn: () => listRoster(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
    staleTime: 60_000,
  });
}

/** Names for user ids, read from the project roster. */
export function usePeopleNames(projectId: string): (userId: string | null | undefined) => string | null {
  const { data: roster = [] } = useRoster(projectId);
  const userId = useAuthStore((s) => s.userId);
  const fullName = useAuthStore((s) => s.userFullName);
  return useMemo(() => {
    const names = new Map<string, string>();
    for (const m of roster) if (m.user_id) names.set(m.user_id, m.display_name || m.email);
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
