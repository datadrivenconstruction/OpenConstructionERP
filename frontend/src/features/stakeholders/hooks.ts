// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the stakeholder screens, plus the two pieces of
// context every screen needs: how to name a person and how to name a
// framework item in the reader's language.

import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { listRoster, type RosterMember } from '@/features/teams/api';
import { useAuthStore } from '@/stores/useAuthStore';

import {
  getGrid,
  getMandates,
  getReadiness,
  getRoles,
  getSettings,
  listValidation,
  listAssessments,
  listBodies,
  listCommitments,
  listDue,
  listEvents,
  listFrameworks,
  listPlanItems,
  listStakeholders,
  stakeholderErrorCan,
  stakeholderErrorCode,
  type StakeholderSettings,
  stakeholderKeys,
} from './api';
import type { LabelContext } from './labels';

/** What the settings route answered: the settings, or none yet together with what the reader may do about that. */
export interface SettingsState {
  settings: StakeholderSettings | null;
  /** The flags sent with `settings_missing`; null from a server that does not send them. */
  can: StakeholderSettings['can'] | null;
}

/** The settings, or none when no framework is pinned yet (404 `settings_missing`), which is an empty state and not an error. */
export function useStakeholderSettings(projectId: string) {
  return useQuery({
    queryKey: stakeholderKeys.settings(projectId),
    queryFn: async (): Promise<SettingsState> => {
      try {
        const settings = await getSettings(projectId);
        return { settings, can: settings.can };
      } catch (err) {
        // Only `settings_missing` is the empty state. A bare 404 also means the
        // project is not visible to this user, and that must read as an error.
        if (stakeholderErrorCode(err) === 'settings_missing') return { settings: null, can: stakeholderErrorCan(err) };
        throw err;
      }
    },
    enabled: !!projectId,
    retry: false,
  });
}

export function useFrameworks(enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.frameworks,
    queryFn: () => listFrameworks().then((page) => page.items),
    enabled,
  });
}

export function useRegister(projectId: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.register(projectId),
    queryFn: () => listStakeholders(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useAssessments(projectId: string, stakeholderId: string | null) {
  return useQuery({
    queryKey: stakeholderKeys.assessments(projectId, stakeholderId ?? ''),
    queryFn: () => listAssessments(projectId, stakeholderId as string).then((page) => page.items),
    enabled: !!projectId && !!stakeholderId,
  });
}

export function useGrid(projectId: string, method: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.grid(projectId, method),
    queryFn: () => getGrid(projectId, method),
    enabled: !!projectId && !!method && enabled,
  });
}

export function useReadiness(projectId: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.readiness(projectId),
    queryFn: () => getReadiness(projectId),
    enabled: !!projectId && enabled,
  });
}

/** The findings of the module's validation rules for the project. */
export function useValidation(projectId: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.validation(projectId),
    queryFn: () => listValidation(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
    retry: false,
  });
}

export function usePlanItems(projectId: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.plan(projectId),
    queryFn: () => listPlanItems(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useDue(projectId: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.due(projectId),
    queryFn: () => listDue(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useEvents(projectId: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.events(projectId),
    queryFn: () => listEvents(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useCommitments(projectId: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.commitments(projectId),
    queryFn: () => listCommitments(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useRoles(projectId: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.roles(projectId),
    queryFn: () => getRoles(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useBodies(projectId: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.bodies(projectId),
    queryFn: () => listBodies(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useMandates(projectId: string, enabled = true) {
  return useQuery({
    queryKey: stakeholderKeys.mandates(projectId),
    queryFn: () => getMandates(projectId),
    enabled: !!projectId && enabled,
  });
}

/** Refetch everything the module holds for the project after any write: a new holder changes who decides a commitment. */
export function useInvalidateStakeholders(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => qc.invalidateQueries({ queryKey: stakeholderKeys.project(projectId) }), [qc, projectId]);
}

/** The project roster, under the same key the people picker caches it. */
export function useRoster(projectId: string): RosterMember[] {
  const { data = [] } = useQuery({
    queryKey: ['roster', projectId],
    queryFn: () => listRoster(projectId).then((page) => page.items),
    enabled: !!projectId,
    staleTime: 60_000,
  });
  return data;
}

/** Names for user ids, read from the project roster. */
export function usePeopleNames(projectId: string): (userId: string | null | undefined) => string | null {
  const roster = useRoster(projectId);
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
