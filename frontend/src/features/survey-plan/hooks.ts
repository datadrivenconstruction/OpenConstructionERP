// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** React hooks of the plan canvas: conventions, code library, view transform. */

import { useMemo, useSyncExternalStore } from 'react';
import { useQuery } from '@tanstack/react-query';
import { planApi, planKeys } from './api';
import { resolveConventions, type PlanConventions } from './units/conventions';

const USER_KEY = 'oe.plan.conventions';
const listeners = new Set<() => void>();
let userCache: string | null | undefined;

function readUser(): string | null {
  if (userCache !== undefined) return userCache;
  try {
    userCache = typeof localStorage !== 'undefined' ? localStorage.getItem(USER_KEY) : null;
  } catch {
    userCache = null;
  }
  return userCache;
}

/** The user's own display overrides (this browser), layered over the project's conventions. */
export function setUserConventions(over: Partial<PlanConventions> | null): void {
  const text = over && Object.keys(over).length ? JSON.stringify(over) : null;
  try {
    if (text) localStorage.setItem(USER_KEY, text);
    else localStorage.removeItem(USER_KEY);
  } catch {
    /* private mode: keep it for the session */
  }
  userCache = text;
  listeners.forEach((l) => l());
}

export function useUserConventions(): Partial<PlanConventions> {
  const raw = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    readUser,
    () => null,
  );
  return useMemo(() => {
    try {
      return raw ? (JSON.parse(raw) as Partial<PlanConventions>) : {};
    } catch {
      return {};
    }
  }, [raw]);
}

/** Effective conventions: country default < project setting < user override < explicit prop. */
export function usePlanConventions(projectId: string | null | undefined, explicit?: Partial<PlanConventions>) {
  const settings = useQuery({
    queryKey: planKeys.settings(projectId ?? ''),
    queryFn: () => planApi.settings(projectId!),
    enabled: !!projectId,
    staleTime: 5 * 60_000,
  });
  const user = useUserConventions();
  const conventions = useMemo(
    () => resolveConventions(settings.data?.conventions, user, explicit),
    [settings.data, user, explicit],
  );
  return { conventions, csf: settings.data?.csf ?? null, settings };
}

export function useCodeLibrary(projectId: string | null | undefined) {
  return useQuery({
    queryKey: planKeys.codes(projectId ?? ''),
    queryFn: () => planApi.codes(projectId!),
    enabled: !!projectId,
    staleTime: 5 * 60_000,
  });
}

export function useViewTransform(projectId: string | null | undefined) {
  return useQuery({
    queryKey: planKeys.viewTransform(projectId ?? ''),
    queryFn: () => planApi.viewTransform(projectId!),
    enabled: !!projectId,
    staleTime: 10 * 60_000,
  });
}
