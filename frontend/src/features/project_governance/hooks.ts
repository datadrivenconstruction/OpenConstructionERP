// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the governance screens, plus the two pieces of
// context every screen needs: who is looking (for the button verdicts) and
// how to name a catalogue item in the reader's language.

import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { listRoster } from '@/features/teams/api';
import { useAuthStore } from '@/stores/useAuthStore';

import {
  getGate,
  getMatrix,
  getModel,
  type GovernanceModel,
  governanceErrorCode,
  governanceKeys,
  missingModelCanManage,
  listAreas,
  listChangeRequests,
  listConditions,
  listDocuments,
} from './api';
import type { Viewer } from './access';
import type { LabelContext } from './labels';

interface ModelAnswer {
  model: GovernanceModel | null;
  /** Without a model: whether the reader may set the first one. Null when the server did not say. */
  canSet: boolean | null;
}

async function fetchModel(projectId: string): Promise<ModelAnswer> {
  try {
    return { model: await getModel(projectId), canSet: null };
  } catch (err) {
    // Only `model_missing` is the empty state. A bare 404 also means the
    // project is not visible to this user, and that must read as an error.
    if (governanceErrorCode(err) === 'model_missing') return { model: null, canSet: missingModelCanManage(err) };
    throw err;
  }
}

/** The model, or null when the project has none yet (404 `model_missing`), which is an empty state and not an error. */
export function useGovernanceModel(projectId: string, enabled = true) {
  return useQuery({
    queryKey: governanceKeys.model(projectId),
    queryFn: () => fetchModel(projectId),
    select: (answer) => answer.model,
    enabled: !!projectId && enabled,
    retry: false,
  });
}

/** For a project without a model: the server's word on whether the reader may set one. Null when it gave none. */
export function useCanSetModel(projectId: string): boolean | null {
  const query = useQuery({
    queryKey: governanceKeys.model(projectId),
    queryFn: () => fetchModel(projectId),
    select: (answer) => answer.canSet,
    enabled: !!projectId,
    retry: false,
  });
  return query.data ?? null;
}

export function useGovernanceAreas(projectId: string, enabled = true) {
  return useQuery({
    queryKey: governanceKeys.areas(projectId),
    queryFn: () => listAreas(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useGovernanceDocuments(projectId: string, enabled = true) {
  return useQuery({
    queryKey: governanceKeys.documents(projectId),
    queryFn: () => listDocuments(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useGovernanceMatrix(projectId: string, enabled = true) {
  return useQuery({
    queryKey: governanceKeys.matrix(projectId),
    queryFn: () => getMatrix(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useGateDetail(projectId: string, gateId: string | null) {
  return useQuery({
    queryKey: governanceKeys.gate(projectId, gateId ?? ''),
    queryFn: () => getGate(projectId, gateId as string),
    enabled: !!projectId && !!gateId,
  });
}

export function useChangeRequests(projectId: string, enabled = true) {
  return useQuery({
    queryKey: governanceKeys.changeRequests(projectId),
    queryFn: () => listChangeRequests(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useConditions(projectId: string, enabled = true) {
  return useQuery({
    queryKey: governanceKeys.conditions(projectId),
    queryFn: () => listConditions(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

/** Refetch everything governance holds for the project after any write: one gate decision touches all of it. */
export function useInvalidateGovernance(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => qc.invalidateQueries({ queryKey: governanceKeys.project(projectId) }), [qc, projectId]);
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

/** Who is looking, by id only: it tells an area owner apart, and never stands in for a permission. */
export function useViewer(): Viewer {
  const userId = useAuthStore((s) => s.userId);
  return useMemo(() => ({ userId }), [userId]);
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
