// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the commitment screens, plus the context every
// screen needs: what the caller may do on the project, the names behind
// user ids, and how to name a catalogue item in the reader's language.

import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { listRoster } from '@/features/teams/api';
import { useAuthStore } from '@/stores/useAuthStore';

import {
  commitmentErrorCode,
  commitmentKeys,
  getCapabilities,
  getExposure,
  getMatrix,
  getReferences,
  listAbortBases,
  listAbortTerms,
  listAssignments,
  listFindings,
  listItems,
  listReleases,
  listScenarios,
  listSchedules,
} from './api';
import type { LabelContext } from './labels';

/** The matrix, or null when the project has none yet (404 `matrix_missing`), which is an empty state and not an error. */
export function useCommitmentMatrix(projectId: string) {
  return useQuery({
    queryKey: commitmentKeys.matrix(projectId),
    queryFn: async () => {
      try {
        return await getMatrix(projectId);
      } catch (err) {
        // Only `matrix_missing` is the empty state. A bare 404 also means the
        // project is not visible to this user, and that must read as an error.
        if (commitmentErrorCode(err) === 'matrix_missing') return null;
        throw err;
      }
    },
    enabled: !!projectId,
    retry: false,
  });
}

/** What the caller may do on the project's matrix, as the server says. */
export function useCapabilities(projectId: string) {
  return useQuery({
    queryKey: commitmentKeys.capabilities(projectId),
    queryFn: () => getCapabilities(projectId),
    enabled: !!projectId,
    // A failure is shown with its own retry button; silent retries would read as "checking" for seconds.
    retry: false,
  });
}

/** Gates, areas, frame documents and funding applications a form may pick from. */
export function useReferences(projectId: string, enabled = true) {
  return useQuery({
    queryKey: commitmentKeys.references(projectId),
    queryFn: () => getReferences(projectId),
    enabled: !!projectId && enabled,
    staleTime: 60_000,
  });
}

export function useCommitmentItems(projectId: string, enabled = true) {
  return useQuery({
    queryKey: commitmentKeys.items(projectId),
    queryFn: () => listItems(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useReleaseHistory(projectId: string, itemId: string | null) {
  return useQuery({
    queryKey: commitmentKeys.releases(projectId, itemId ?? ''),
    queryFn: () => listReleases(projectId, itemId as string).then((p) => p.items),
    enabled: !!projectId && !!itemId,
  });
}

export function useAbortTerms(projectId: string, itemId: string | null) {
  return useQuery({
    queryKey: commitmentKeys.abortTerms(projectId, itemId ?? ''),
    queryFn: () => listAbortTerms(projectId, itemId as string).then((p) => p.items),
    enabled: !!projectId && !!itemId,
  });
}

export function useAssignments(projectId: string, enabled = true) {
  return useQuery({
    queryKey: commitmentKeys.assignments(projectId),
    queryFn: () => listAssignments(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useExposure(projectId: string, asOf: string, enabled = true) {
  return useQuery({
    queryKey: commitmentKeys.exposure(projectId, asOf),
    queryFn: () => getExposure(projectId, asOf),
    enabled: !!projectId && !!asOf && enabled,
  });
}

export function useScenarios(projectId: string, enabled = true) {
  return useQuery({
    queryKey: commitmentKeys.scenarios(projectId),
    queryFn: () => listScenarios(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useFindings(projectId: string, enabled = true) {
  return useQuery({
    queryKey: commitmentKeys.findings(projectId),
    queryFn: () => listFindings(projectId).then((p) => p.items.filter((f) => !f.passed)),
    enabled: !!projectId && enabled,
  });
}

export function useSchedules() {
  return useQuery({
    queryKey: commitmentKeys.schedules,
    queryFn: () => listSchedules().then((p) => p.items),
    staleTime: 5 * 60_000,
  });
}

export function useAbortBases(enabled = true) {
  return useQuery({
    queryKey: commitmentKeys.abortBases,
    queryFn: () => listAbortBases().then((p) => p.items),
    staleTime: 5 * 60_000,
    enabled,
  });
}

/** Refetch everything the matrix holds for the project after any write: one release moves totals, states and exposure. */
export function useInvalidateCommitments(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => qc.invalidateQueries({ queryKey: commitmentKeys.project(projectId) }), [qc, projectId]);
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
