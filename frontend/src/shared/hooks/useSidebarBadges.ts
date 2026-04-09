/**
 * Sidebar badge counts hook.
 *
 * Fetches open-item counts for Tasks, RFIs, and Safety from a single
 * backend endpoint. Caches aggressively (60s staleTime) so the sidebar
 * never triggers excessive network traffic.
 *
 * Returns `{ tasks: number; rfi: number; safety: number }` with 0
 * defaults when no project is selected or the query is still loading.
 */

import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

interface SidebarBadgesResponse {
  tasks_open: number;
  rfi_open: number;
  safety_open: number;
}

export interface SidebarBadgeCounts {
  tasks: number;
  rfi: number;
  safety: number;
}

const EMPTY: SidebarBadgeCounts = { tasks: 0, rfi: 0, safety: 0 };

export function useSidebarBadges(): SidebarBadgeCounts {
  const projectId = useProjectContextStore((s) => s.activeProjectId);

  const { data } = useQuery({
    queryKey: ['sidebar-badges', projectId],
    queryFn: () =>
      apiGet<SidebarBadgesResponse>(
        `/v1/sidebar/badges/?project_id=${encodeURIComponent(projectId!)}`,
      ),
    enabled: !!projectId,
    staleTime: 60_000, // 60 seconds — avoid refetching on every render
    refetchInterval: 120_000, // refresh every 2 minutes in background
    refetchOnWindowFocus: false,
  });

  if (!data) return EMPTY;

  return {
    tasks: data.tasks_open,
    rfi: data.rfi_open,
    safety: data.safety_open,
  };
}
