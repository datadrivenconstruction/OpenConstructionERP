// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * useProjectWidgetsRollup — single React Query that fetches all
 * project-detail widget payloads for /projects/:id in ONE round-trip.
 *
 * Replaces the per-widget ``useGracefulQuery`` fan-out that ProjectWidgets
 * used to do (~8 parallel HTTP calls on every project-page load). Now:
 * exactly one call to ``GET /api/v1/dashboard/rollup/?widgets=…&project_ids=<id>``.
 *
 * staleTime is 30s — the rollup payload mixes data that some widgets
 * want fresher than others (compliance docs change rarely, RFI inbox
 * may shift minute-to-minute). 30s is the lowest sensible default that
 * still kills the refetch-on-mount thrash. The server already sends
 * ``Cache-Control: max-age=60`` so two consecutive mounts within a
 * minute will be a 304 anyway.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet, ApiError } from '@/shared/lib/api';
import {
  PROJECT_DETAIL_WIDGET_IDS,
  type DashboardRollupResponse,
  type ProjectDetailWidgetId,
  type ProjectDetailPayloadMap,
} from '@/shared/api/dashboardRollup';

export interface UseProjectWidgetsRollupOptions {
  /** The project id to scope the rollup to (sent as ``project_ids=<id>``). */
  projectId: string;
  /** Restrict to these widget ids. Defaults to all 8 project-detail widgets. */
  widgets?: readonly ProjectDetailWidgetId[];
  /** Disable the query entirely (e.g. while auth is still loading). */
  enabled?: boolean;
}

export function useProjectWidgetsRollup(options: UseProjectWidgetsRollupOptions) {
  const { projectId, enabled = true } = options;
  const widgets = options.widgets ?? PROJECT_DETAIL_WIDGET_IDS;
  const widgetsCsv = widgets.slice().sort().join(',');

  const query = useQuery({
    queryKey: ['project-widgets-rollup', projectId, widgetsCsv],
    queryFn: async (): Promise<DashboardRollupResponse> => {
      const params = new URLSearchParams();
      params.set('widgets', widgetsCsv);
      params.set('project_ids', projectId);
      try {
        return await apiGet<DashboardRollupResponse>(
          `/v1/dashboard/rollup/?${params.toString()}`,
        );
      } catch (err) {
        // Graceful degradation: the page must keep rendering even if
        // the rollup endpoint is offline. Widgets will fall back to
        // their own per-widget useGracefulQuery (kept in tree for
        // exactly this reason).
        if (err instanceof ApiError) return {};
        return {};
      }
    },
    enabled: Boolean(projectId) && enabled,
    retry: false,
    // Mixed-shelf-life payload; 30s is the sensible compromise. See the
    // module docstring for the rationale.
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const byWidget = useMemo(
    () =>
      <K extends ProjectDetailWidgetId>(id: K): ProjectDetailPayloadMap[K] | null => {
        const data = query.data;
        if (!data) return null;
        return (data[id] as ProjectDetailPayloadMap[K] | undefined) ?? null;
      },
    [query.data],
  );

  return {
    ...query,
    byWidget,
  };
}
