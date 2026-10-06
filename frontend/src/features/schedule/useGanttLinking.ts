// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The schedule page's side of drag-to-link on the Gantt.
 *
 * The chart reports "link A to B as FS" or "remove the link A to B"; this turns
 * that into the same relationship calls the dependency form makes, reschedules
 * so the bars move, and refetches the edges and the bars (the arrows are drawn
 * from the bars' dependency mirror, so both keys go stale together).
 *
 * Three rules, each from a review finding:
 * - a role that cannot edit the schedule gets no callbacks, so the chart draws
 *   no handles and no arrow menu instead of offering actions the server refuses;
 * - removal goes by the (predecessor, successor) pair. Searching the listed
 *   relationships missed links past the server's page of 200;
 * - nothing fails silently and nothing rejects: the chart calls these as
 *   `void onCreateLink(...)`, so a rejection would surface as an unhandled
 *   error and leave the chart unrefreshed.
 */
import { useCallback, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import type { GanttLinkType } from '@/shared/ui/Gantt';
import { ApiError } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { scheduleApi } from './api';
import { scheduleErrorDetail, scheduleErrorMessage } from './errors';

export interface GanttLinking {
  onCreateLink?: (fromId: string, toId: string, type: GanttLinkType) => Promise<void>;
  onDeleteLink?: (fromId: string, toId: string) => Promise<void>;
}

export function useGanttLinking(scheduleId: string, canEdit: boolean): GanttLinking {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const refetch = useCallback(async () => {
    await Promise.allSettled([
      queryClient.invalidateQueries({ queryKey: ['schedule-relationships', scheduleId] }),
      queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] }),
    ]);
  }, [queryClient, scheduleId]);

  // After a change that did land: move the bars, then refetch whatever the
  // reschedule did. The edge is already stored, so a failed reschedule is a
  // warning about the dates, not an error about the link.
  const afterChange = useCallback(async (): Promise<boolean> => {
    let rescheduled = true;
    try {
      await scheduleApi.reschedule(scheduleId);
    } catch (error) {
      rescheduled = false;
      addToast({
        type: 'warning',
        title: t('schedule.link_reschedule_failed', {
          defaultValue:
            'The link was saved, but the dates could not be recalculated. Recalculate the schedule to update them.',
        }),
        message: scheduleErrorMessage(error, t),
      });
    }
    await refetch();
    return rescheduled;
  }, [scheduleId, refetch, addToast, t]);

  const onCreateLink = useCallback(
    async (fromId: string, toId: string, type: GanttLinkType) => {
      try {
        await scheduleApi.createRelationship(scheduleId, {
          predecessor_id: fromId,
          successor_id: toId,
          relationship_type: type,
          lag_days: 0,
        });
      } catch (error) {
        // A cycle (400) or an activity from another schedule (404) comes back
        // coded; scheduleErrorMessage says it in the reader's language.
        addToast({ type: 'error', title: scheduleErrorMessage(error, t) });
        await refetch();
        return;
      }
      if (await afterChange()) {
        addToast({ type: 'success', title: t('schedule.dep_added', { defaultValue: 'Dependency added' }) });
      }
    },
    [scheduleId, afterChange, refetch, addToast, t],
  );

  const onDeleteLink = useCallback(
    async (fromId: string, toId: string) => {
      try {
        await scheduleApi.deleteRelationshipBetween(scheduleId, fromId, toId);
      } catch (error) {
        // The pair route answers 404 `relationship_not_found` when the link is
        // already gone (another tab, another user). A 404 with a different code
        // (an activity outside this schedule) is a real error and says so.
        const code = scheduleErrorDetail(error)?.error;
        const gone =
          error instanceof ApiError &&
          error.status === 404 &&
          (code === undefined || code === 'relationship_not_found');
        addToast({
          type: gone ? 'info' : 'error',
          title: gone
            ? t('schedule.link_not_found', {
                defaultValue: 'That link no longer exists. The chart has been refreshed.',
              })
            : scheduleErrorMessage(error, t),
        });
        await refetch();
        return;
      }
      if (await afterChange()) {
        addToast({ type: 'success', title: t('schedule.dep_removed', { defaultValue: 'Dependency removed' }) });
      }
    },
    [scheduleId, afterChange, refetch, addToast, t],
  );

  return useMemo(
    () => (canEdit ? { onCreateLink, onDeleteLink } : {}),
    [canEdit, onCreateLink, onDeleteLink],
  );
}
