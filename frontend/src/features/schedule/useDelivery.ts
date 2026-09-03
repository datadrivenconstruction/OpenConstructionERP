// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The schedule page's one source of delivery data, and the only writes the
 * schedule makes into the delivery modules.
 *
 * Both reads are optional. A module that is not installed answers 404, and a
 * 404 here is not an error to show the user - it is "this deployment does not
 * have that module", so the query resolves to `null` and every surface that
 * depends on it renders nothing at all. The schedule keeps working exactly as
 * it did before the column existed. A real failure (500, a network drop) also
 * resolves to `null` for the same reason: a chip column that cannot be trusted
 * is worse absent than wrong.
 */

import { useCallback, useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { scheduleApi, type Activity } from './api';
import {
  buildDeliveryIndex,
  doneStageIds,
  linkedTaskIds,
  TASK_IDS_META_KEY,
  type DeliveryIndex,
} from './delivery';
import {
  createStandupTask,
  fetchDepartments,
  fetchProjectRequests,
  fetchStandupBoard,
  linkRequestToActivity,
  todayIso,
  type DeliveryBoard,
  type DeliveryDepartment,
  type DeliveryRequest,
  type StandupTaskWrite,
} from './deliveryApi';

/** Resolve to `null` instead of throwing - see the module note above. */
async function optional<T>(fn: () => Promise<T>): Promise<T | null> {
  try {
    return await fn();
  } catch {
    return null;
  }
}

export interface DeliveryData {
  /** Nothing attached anywhere and no module answered - hide every surface. */
  enabled: boolean;
  requestsAvailable: boolean;
  standupAvailable: boolean;
  index: DeliveryIndex;
  requests: DeliveryRequest[];
  board: DeliveryBoard | null;
  departmentColour: (key: string) => string | undefined;
  today: string;
  refresh: () => void;
}

export function useDeliveryData(
  projectId: string,
  activities: Array<Pick<Activity, 'id' | 'metadata'>>,
): DeliveryData {
  const queryClient = useQueryClient();
  const today = todayIso();

  const requestsQuery = useQuery({
    queryKey: ['schedule-delivery', 'requests', projectId],
    queryFn: () => optional(() => fetchProjectRequests(projectId)),
    enabled: !!projectId,
    staleTime: 60_000,
    retry: false,
  });

  const deptQuery = useQuery({
    queryKey: ['schedule-delivery', 'departments'],
    queryFn: () => optional(() => fetchDepartments()),
    enabled: !!projectId,
    staleTime: 300_000,
    retry: false,
  });

  const boardQuery = useQuery({
    queryKey: ['schedule-delivery', 'board', today],
    queryFn: () => optional(() => fetchStandupBoard(today)),
    enabled: !!projectId,
    staleTime: 60_000,
    retry: false,
  });

  const requests = requestsQuery.data ?? [];
  const board = boardQuery.data ?? null;

  const index = useMemo(
    () =>
      buildDeliveryIndex({
        activities,
        requests,
        tasks: (board?.tasks ?? []).filter((t) => t.project_id === projectId),
        doneStages: doneStageIds(board, projectId),
        today,
      }),
    [activities, requests, board, projectId, today],
  );

  const colourByDept = useMemo(() => {
    const map: Record<string, string> = {};
    for (const d of (deptQuery.data ?? []) as DeliveryDepartment[]) {
      if (d.colour) map[d.key] = d.colour;
    }
    return map;
  }, [deptQuery.data]);

  const departmentColour = useCallback((key: string) => colourByDept[key], [colourByDept]);

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['schedule-delivery'] });
  }, [queryClient]);

  const requestsAvailable = requestsQuery.data !== null && requestsQuery.data !== undefined;
  const standupAvailable = board !== null;

  return {
    enabled: requestsAvailable || standupAvailable,
    requestsAvailable,
    standupAvailable,
    index,
    requests,
    board,
    departmentColour,
    today,
    refresh,
  };
}

/* ── Writes ───────────────────────────────────────────────────────────── */

/** Add or drop a standup task id on an activity's own metadata. */
function nextTaskIds(activity: Pick<Activity, 'metadata'>, taskId: string, attach: boolean): string[] {
  const ids = linkedTaskIds(activity);
  if (attach) return ids.includes(taskId) ? ids : [...ids, taskId];
  return ids.filter((id) => id !== taskId);
}

export interface DeliveryWrites {
  linkRequest: (requestId: string, activityId: string | null) => Promise<unknown>;
  linkTask: (activity: Activity, taskId: string, attach: boolean) => Promise<unknown>;
  createTaskForActivity: (activity: Activity, task: StandupTaskWrite) => Promise<unknown>;
  pending: boolean;
}

export function useDeliveryWrites(scheduleId: string, onDone: () => void): DeliveryWrites {
  const queryClient = useQueryClient();

  const settle = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ['schedule-delivery'] });
    await queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
    onDone();
  }, [queryClient, scheduleId, onDone]);

  const linkRequestMutation = useMutation({
    mutationFn: ({ requestId, activityId }: { requestId: string; activityId: string | null }) =>
      linkRequestToActivity(requestId, activityId),
    onSuccess: settle,
  });

  // The activity's metadata column is shallow-merged server-side, so sending
  // just this key keeps every sibling key (BOQ provenance, duration source).
  const linkTaskMutation = useMutation({
    mutationFn: ({
      activity,
      taskId,
      attach,
    }: {
      activity: Activity;
      taskId: string;
      attach: boolean;
    }) =>
      scheduleApi.updateActivity(activity.id, {
        metadata: { [TASK_IDS_META_KEY]: nextTaskIds(activity, taskId, attach) },
      } as Partial<Activity>),
    onSuccess: settle,
  });

  const createTaskMutation = useMutation({
    mutationFn: async ({ activity, task }: { activity: Activity; task: StandupTaskWrite }) => {
      const made = await createStandupTask(task);
      const created = made?.[0];
      // A board that created the task but returned nothing usable leaves it
      // unlinked rather than guessing an id - it is still on the board.
      if (!created?.id) return made;
      await scheduleApi.updateActivity(activity.id, {
        metadata: { [TASK_IDS_META_KEY]: nextTaskIds(activity, created.id, true) },
      } as Partial<Activity>);
      return made;
    },
    onSuccess: settle,
  });

  return {
    linkRequest: (requestId, activityId) =>
      linkRequestMutation.mutateAsync({ requestId, activityId }),
    linkTask: (activity, taskId, attach) =>
      linkTaskMutation.mutateAsync({ activity, taskId, attach }),
    createTaskForActivity: (activity, task) => createTaskMutation.mutateAsync({ activity, task }),
    pending:
      linkRequestMutation.isPending ||
      linkTaskMutation.isPending ||
      createTaskMutation.isPending,
  };
}
