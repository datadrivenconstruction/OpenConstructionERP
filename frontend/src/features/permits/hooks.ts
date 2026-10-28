// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the permit screens, plus what every screen needs
// around them: names for user ids, labels in the reader's language, and one
// way to run a write so a refusal is always shown in the server's words.

import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchCDEContainers } from '@/features/cde/api';
import { listRoster } from '@/features/teams/api';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtList } from '@/shared/lib/formatters';
import { useAuthStore } from '@/stores/useAuthStore';

import {
  getApplication,
  getCondition,
  getReadiness,
  getRoadmap,
  getShippedCatalogue,
  getTimeline,
  getValidation,
  listApplications,
  listCatalogues,
  listConditions,
  listPermits,
  listRequirements,
  permitErrorCode,
  permitErrorMessage,
  permitKeys,
  type ReadinessGate,
  type Roadmap,
} from './api';
import { errorText, type LabelContext, type TFn } from './labels';

/** The roadmap, or null when the project has none yet (404 `roadmap_missing`), which is an empty state and not an error. */
export function useRoadmap(projectId: string) {
  return useQuery({
    queryKey: permitKeys.roadmap(projectId),
    queryFn: async () => {
      try {
        return await getRoadmap(projectId);
      } catch (err) {
        // Only `roadmap_missing` is the empty state. A bare 404 also means the
        // project is not visible to this user, and that must read as an error.
        if (permitErrorCode(err) === 'roadmap_missing') return null;
        throw err;
      }
    },
    enabled: !!projectId,
    retry: false,
  });
}

export function useCatalogues(enabled = true) {
  return useQuery({
    queryKey: permitKeys.catalogues,
    queryFn: () => listCatalogues().then((page) => page.items),
    enabled,
    staleTime: 5 * 60_000,
  });
}

/**
 * The permit types the project's catalogue offers. Only a shipped catalogue
 * can be read this way; for a tenant catalogue the list is empty and the
 * dialog asks for the type code instead.
 */
export function useCatalogueTypes(roadmap: Roadmap | null | undefined, enabled = true) {
  const shipped = roadmap?.catalogue_source === 'shipped';
  return useQuery({
    queryKey: permitKeys.catalogue(roadmap?.catalogue_id ?? ''),
    queryFn: () => getShippedCatalogue(roadmap!.catalogue_id).then((c) => c.permit_types),
    enabled: !!roadmap && shipped && enabled,
    staleTime: 5 * 60_000,
  });
}

export function useRequirements(projectId: string, enabled = true) {
  return useQuery({
    queryKey: permitKeys.requirements(projectId),
    queryFn: () => listRequirements(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useTimeline(projectId: string, enabled = true) {
  return useQuery({
    queryKey: permitKeys.timeline(projectId),
    queryFn: () => getTimeline(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useApplications(projectId: string, enabled = true) {
  return useQuery({
    queryKey: permitKeys.applications(projectId),
    queryFn: () => listApplications(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useApplicationDetail(projectId: string, applicationId: string | null) {
  return useQuery({
    queryKey: permitKeys.application(projectId, applicationId ?? ''),
    queryFn: () => getApplication(projectId, applicationId as string),
    enabled: !!projectId && !!applicationId,
  });
}

export function usePermits(projectId: string, enabled = true) {
  return useQuery({
    queryKey: permitKeys.permits(projectId),
    queryFn: () => listPermits(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useConditions(projectId: string, enabled = true) {
  return useQuery({
    queryKey: permitKeys.conditions(projectId),
    queryFn: () => listConditions(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useConditionDetail(projectId: string, conditionId: string | null) {
  return useQuery({
    queryKey: permitKeys.condition(projectId, conditionId ?? ''),
    queryFn: () => getCondition(projectId, conditionId as string),
    enabled: !!projectId && !!conditionId,
  });
}

export function useReadiness(projectId: string, gate: ReadinessGate, enabled = true) {
  return useQuery({
    queryKey: permitKeys.readiness(projectId, gate),
    queryFn: () => getReadiness(projectId, gate),
    enabled: !!projectId && enabled,
  });
}

export function useValidation(projectId: string, enabled = true) {
  return useQuery({
    queryKey: permitKeys.validation(projectId),
    queryFn: () => getValidation(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

/** Refetch everything permits hold for the project after any write: one decision touches all of it. */
export function useInvalidatePermits(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => qc.invalidateQueries({ queryKey: permitKeys.project(projectId) }), [qc, projectId]);
}

/**
 * The sentence for a failed write: the refusal code in the reader's language
 * when the server named one, otherwise whatever the transport can say.
 */
export function refusalText(t: TFn, err: unknown): string {
  const code = permitErrorCode(err);
  return code ? errorText(t, code, permitErrorMessage(err)) : getErrorMessage(err);
}

export interface PermitAction<TInput> {
  run: (input: TInput) => void;
  busy: boolean;
  /** Why the last attempt was refused, as a sentence; null before and after a success. */
  error: string | null;
  reset: () => void;
}

/**
 * One write against the permits API. On success everything the project holds
 * is refetched and `onDone` runs; on a refusal `error` carries the reason, so
 * the dialog that asked can show it where the reader is looking.
 */
export function usePermitAction<TInput, TResult = unknown>(
  projectId: string,
  fn: (input: TInput) => Promise<TResult>,
  onDone?: (result: TResult) => void,
): PermitAction<TInput> {
  const { t } = useTranslation();
  const invalidate = useInvalidatePermits(projectId);
  const m = useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      void invalidate();
      onDone?.(result);
    },
  });
  return {
    run: (input) => m.mutate(input),
    busy: m.isPending,
    error: m.isError ? refusalText(t as TFn, m.error) : null,
    reset: m.reset,
  };
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

/**
 * The name of the document a revision id belongs to, read from the project
 * documents under the key the document picker caches them. Null for a
 * revision that is no longer the current one of its document.
 */
export function useDocumentNames(projectId: string, enabled = true): (revisionId: string | null | undefined) => string | null {
  const { data: containers = [] } = useQuery({
    queryKey: ['permits', projectId, 'cde-containers'],
    queryFn: () => fetchCDEContainers({ project_id: projectId }),
    enabled: enabled && !!projectId,
    staleTime: 60_000,
  });
  return useMemo(() => {
    const names = new Map<string, string>();
    for (const c of containers) if (c.current_revision_id) names.set(c.current_revision_id, fmtList([c.container_code, c.title]));
    return (id) => (id ? names.get(id) ?? null : null);
  }, [containers]);
}

export function useViewerId(): string | null {
  return useAuthStore((s) => s.userId);
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
