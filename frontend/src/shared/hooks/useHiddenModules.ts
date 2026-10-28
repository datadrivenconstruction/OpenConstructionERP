// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Per-user sidebar visibility — hybrid local-cache + server-sync hook.
 *
 * Replaces the previous per-browser `localStorage['oe.sidebar_hidden_modules']`
 * key. The old key was shared across every user who logged into the same
 * browser, so user B inherited user A's hidden list — that's the bug this
 * hook fixes.
 *
 * Strategy (gives instant render + multi-device sync):
 *
 *   1. Read `hidden_modules:${userEmail}` from localStorage synchronously
 *      for the initial state. No render flash, works offline.
 *   2. On mount React Query fetches `GET /v1/users/me/sidebar-preferences/`.
 *      When it lands and differs from the cached value, both state and
 *      localStorage are updated.
 *   3. `setHiddenModules(list)` does an optimistic local write (state +
 *      localStorage) then fires `PUT /v1/users/me/sidebar-preferences/`
 *      in the background. Server errors are swallowed silently — the user
 *      stays unblocked and the next mount's sync will reconcile.
 *   4. The localStorage key is namespaced by user email so anonymous /
 *      logged-out callers never see another user's list, and switching
 *      accounts in the same browser starts from a clean slate.
 *
 * Anonymous callers (no `userEmail` in the auth store) get a read-only
 * empty list and the mutation is a no-op — the menu editor itself is
 * gated behind auth anyway.
 */

import { useCallback, useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPut } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

interface SidebarPreferencesPayload {
  hidden_modules: string[];
}

const LS_PREFIX = 'oe.sidebar_hidden_modules:';
const ENDPOINT = '/v1/users/me/sidebar-preferences/';

function lsKey(userId: string | null): string | null {
  if (!userId) return null;
  return `${LS_PREFIX}${userId}`;
}

function readLocal(userId: string | null): string[] {
  const key = lsKey(userId);
  if (!key) return [];
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.filter((p): p is string => typeof p === 'string');
    }
  } catch {
    /* ignore */
  }
  return [];
}

function writeLocal(userId: string | null, list: string[]): void {
  const key = lsKey(userId);
  if (!key) return;
  try {
    localStorage.setItem(key, JSON.stringify(list));
  } catch {
    /* ignore */
  }
}

function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

export interface UseHiddenModulesResult {
  /** Current effective list of hidden NavItem `to` routes. */
  hiddenModules: string[];
  /** Replace the list — updates state + localStorage immediately, syncs to server in background. */
  setHiddenModules: (list: string[]) => void;
  /**
   * True until the server copy has been fetched AND folded into `hiddenModules`
   * (also while signed out or when the fetch failed). `query.isLoading` alone
   * is not enough: it is false for a query that has not started yet, and false
   * in the render where the data lands but the state still holds the empty
   * local cache. Anything that writes a default over the list (the pack menu)
   * must wait for this to turn false.
   */
  isLoading: boolean;
}

export function useHiddenModules(): UseHiddenModulesResult {
  const userEmail = useAuthStore((s) => s.userEmail);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  // Sync initial read — no render flash even when logged in.
  const [hiddenModules, setHiddenModulesState] = useState<string[]>(() =>
    readLocal(userEmail),
  );

  // Re-prime the in-memory list when the user changes (login / logout /
  // account swap on the same browser). This is the per-user isolation
  // half of the fix — the server fetch below is the multi-device half.
  useEffect(() => {
    setHiddenModulesState(readLocal(userEmail));
    setSyncedAt(null);
  }, [userEmail]);

  const queryClient = useQueryClient();
  // `dataUpdatedAt` of the server payload already folded into the state.
  const [syncedAt, setSyncedAt] = useState<number | null>(null);

  const query = useQuery<SidebarPreferencesPayload>({
    queryKey: ['user-sidebar-preferences', userEmail],
    queryFn: () => apiGet<SidebarPreferencesPayload>(ENDPOINT),
    enabled: isAuthenticated && Boolean(userEmail),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  // Reconcile server → local once the query resolves.
  useEffect(() => {
    if (!query.data) return;
    const serverList = query.data.hidden_modules ?? [];
    if (!arraysEqual(serverList, hiddenModules)) {
      setHiddenModulesState(serverList);
      writeLocal(userEmail, serverList);
    }
    setSyncedAt(query.dataUpdatedAt);
    // hiddenModules intentionally omitted to avoid bouncing on local writes;
    // only react to fresh server data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query.data, query.dataUpdatedAt, userEmail]);

  const mutation = useMutation({
    mutationFn: (list: string[]) =>
      apiPut<SidebarPreferencesPayload, SidebarPreferencesPayload>(ENDPOINT, {
        hidden_modules: list,
      }),
    // No onError toast: the optimistic local write is already in effect
    // and the next mount's sync will reconcile. Being loud here would
    // distract the user from work that already visually succeeded.
  });

  const setHiddenModules = useCallback(
    (list: string[]) => {
      setHiddenModulesState(list);
      writeLocal(userEmail, list);
      // Keep the cached server copy in step, or a remount inside staleTime
      // would reconcile the stale payload back over this choice.
      queryClient.setQueryData<SidebarPreferencesPayload>(['user-sidebar-preferences', userEmail], {
        hidden_modules: list,
      });
      if (isAuthenticated && userEmail) {
        mutation.mutate(list);
      }
    },
    [userEmail, isAuthenticated, mutation, queryClient],
  );

  return {
    hiddenModules,
    setHiddenModules,
    isLoading: !(query.isSuccess && syncedAt === query.dataUpdatedAt),
  };
}
