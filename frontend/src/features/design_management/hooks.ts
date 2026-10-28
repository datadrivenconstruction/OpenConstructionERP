// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the design screens, plus the context every screen
// needs: how to name a catalogue item in the reader's language, how to name a
// person, and one way to run a write and show the server's reason when it is
// refused.

import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { listRoster } from '@/features/teams/api';
import { getErrorMessage } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

import { designErrorCode, designErrorMessage, designKeys, getSetup, listOptions, type OptionKind } from './api';
import type { FieldOption } from './FormDialog';
import { errorText, optionLabel, type LabelContext, type TFn } from './labels';

/** The setup, or null when the project has none yet (404 `setup_missing`), which is an empty state and not an error. */
export function useDesignSetup(projectId: string) {
  return useQuery({
    queryKey: designKeys.setup(projectId),
    queryFn: async () => {
      try {
        return await getSetup(projectId);
      } catch (err) {
        // Only `setup_missing` is the empty state. A bare 404 also means the
        // project is not visible to this user, and that must read as an error.
        if (designErrorCode(err) === 'setup_missing') return null;
        throw err;
      }
    },
    enabled: !!projectId,
    retry: false,
  });
}

/** One list of the project, cached under its name so any write can refresh all of them at once. */
export function useDesignList<T>(projectId: string, name: string, load: (projectId: string) => Promise<T[]>, enabled = true) {
  return useQuery({
    queryKey: designKeys.list(projectId, name),
    queryFn: () => load(projectId),
    enabled: !!projectId && enabled,
  });
}

/**
 * The choices of a picker that another module feeds (contacts, gates, review
 * cycles and so on). Null while loading and when that source is not
 * available, so the form leaves the field out instead of showing an empty list.
 */
export function useDesignOptions(projectId: string, kind: OptionKind, labels: LabelContext): FieldOption[] | null {
  const { data } = useQuery({
    queryKey: [...designKeys.list(projectId, 'options'), kind],
    queryFn: () => listOptions(projectId, kind),
    enabled: !!projectId,
    staleTime: 60_000,
  });
  return useMemo(() => {
    if (!data || !data.available) return null;
    return data.items.map((item) => ({ value: item.id, label: optionLabel(labels, item) }));
  }, [data, labels]);
}

/** Refetch everything design holds for the project after any write: a new drawing moves a schedule line and a phase. */
export function useInvalidateDesign(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => qc.invalidateQueries({ queryKey: designKeys.project(projectId) }), [qc, projectId]);
}

/** The sentence to show for a failed write: the server's reason when it gave one. */
export function refusalText(t: TFn, err: unknown): string {
  const code = designErrorCode(err);
  return code ? errorText(t, code, designErrorMessage(err)) : getErrorMessage(err);
}

/** Run a one-click write. A refusal shows the server's reason as a toast; success refreshes the lists. */
export function useDesignAction(onDone: () => void) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const mutation = useMutation({
    mutationFn: (write: () => Promise<unknown>) => write(),
    onSuccess: () => onDone(),
    onError: (err) => addToast({ type: 'error', title: refusalText(t as TFn, err) }),
  });
  return { run: (write: () => Promise<unknown>) => mutation.mutate(write), pending: mutation.isPending };
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
