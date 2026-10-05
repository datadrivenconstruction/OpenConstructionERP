// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One typed observer on the shared `['system-status']` query.
//
// DemoBanner, PostgresMigrationNotice, SupportUsButton, DashboardPage,
// AgentsPage and PartnerPackApplyDialog each declare their own `useQuery` on
// the same key with the same fetch, `retry: false` and `staleTime: Infinity`.
// This hook repeats that declaration exactly, so it adds an observer and never
// a request. Those callers are deliberately not migrated here.
//
// `/api/system/status` is signed-in only. The hook stays idle until there is
// a session, because a 401 before sign-in would go through the refresh path
// and on to the forced logout redirect. Pre-login screens that need the
// academy flag read `/v1/trainer/public/status/` instead.

import { useQuery } from '@tanstack/react-query';

import { apiGet } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

export const SYSTEM_STATUS_QUERY_KEY = ['system-status'] as const;

/**
 * The fields of `/api/system/status` the frontend reads. The endpoint returns
 * more; everything is optional because older servers and test mocks omit
 * fields, and a missing field must read as "off", never as an error.
 */
export interface SystemStatus {
  api?: { status?: string; version?: string };
  database?: { status?: string; engine?: string };
  demo_mode?: boolean;
  academy_mode?: boolean;
}

/** Fetch `/api/system/status`. Shared by every observer of the key. */
export function fetchSystemStatus(): Promise<SystemStatus> {
  return apiGet<SystemStatus>('/system/status');
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * True only when the status says `academy_mode: true`.
 *
 * Anything else is off: an absent field, `false`, a truthy non-boolean, and a
 * body that is not an object at all (several component tests answer every
 * `apiGet` with `[]`).
 */
export function academyModeFrom(data: unknown): boolean {
  return isPlainObject(data) && data.academy_mode === true;
}

/** True only when the status says `demo_mode: true`. Same rules as above. */
export function demoModeFrom(data: unknown): boolean {
  return isPlainObject(data) && data.demo_mode === true;
}

/**
 * Observe the shared system status. Idle until the user is signed in.
 *
 * @param options.enabled - extra gate on top of the session check.
 */
export function useSystemStatus(options: { enabled?: boolean } = {}) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return useQuery<SystemStatus>({
    queryKey: SYSTEM_STATUS_QUERY_KEY,
    queryFn: fetchSystemStatus,
    retry: false,
    staleTime: Infinity,
    enabled: isAuthenticated && options.enabled !== false,
  });
}
