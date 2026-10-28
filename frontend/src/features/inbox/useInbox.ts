// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shared React Query hook for the unified inbox.
 *
 * Both the dashboard widget (``InboxPanel``) and the full ``/inbox`` page read
 * the same ``GET /api/v1/dashboard/inbox/`` payload. Centralising the query
 * config here means the page (which needs the raw items to build its filter
 * controls + counts) and the panel (which renders + filters the list) share a
 * single cache entry and a single network request - React Query dedupes by the
 * ``['inbox', limit]`` key - instead of drifting apart with copy-pasted
 * options. No new endpoint: this only wraps the existing client.
 */
import { useQuery } from '@tanstack/react-query';
import { fetchInbox } from './api';

/**
 * Root of every inbox query key. Acting on a row invalidates this prefix rather
 * than one cap, so the widget (limit 8) and the page (limit 50) never disagree
 * about what is still in the list.
 */
export const INBOX_QUERY_ROOT = 'inbox';

/** Query key for the unified inbox at a given cap. */
export function inboxQueryKey(limit: number): (string | number)[] {
  return [INBOX_QUERY_ROOT, limit];
}

/** Fetch the unified inbox, shared across the widget and the full page. */
export function useInboxQuery(limit: number) {
  return useQuery({
    queryKey: inboxQueryKey(limit),
    queryFn: () => fetchInbox(limit),
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });
}
