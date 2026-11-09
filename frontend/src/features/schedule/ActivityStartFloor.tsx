import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Anchor, Loader2 } from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate } from '@/shared/lib/formatters';
import { scheduleApi, type Activity } from './api';

/**
 * Shows the "start no earlier than" floor a dragged bar leaves behind and lets
 * the planner clear it, so the bar follows its predecessors again.
 */
export function ActivityStartFloor({ scheduleId, activity }: { scheduleId: string; activity: Activity }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const clear = useMutation({
    mutationFn: () => scheduleApi.updateActivity(activity.id, { constraint_type: null, constraint_date: null }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('schedule.start_floor_clear_failed', { defaultValue: 'Could not clear the start constraint.' }),
        message: getErrorMessage(err),
      }),
  });

  if (activity.constraint_type !== 'start_no_earlier' || !activity.constraint_date) return null;

  return (
    <div
      data-testid="activity-start-floor"
      className="flex items-start justify-between gap-3 rounded-lg border border-border-light p-3"
    >
      <span className="flex flex-col gap-0.5">
        <span className="flex items-center gap-1.5 text-sm font-medium text-content-primary">
          <Anchor size={14} />
          {t('schedule.start_floor_label', {
            defaultValue: 'Start no earlier than {{date}}',
            date: fmtDate(activity.constraint_date, { day: '2-digit', month: 'short', year: 'numeric' }),
          })}
        </span>
        <span className="text-xs text-content-tertiary">
          {t('schedule.start_floor_hint', {
            defaultValue:
              'Set when this bar was moved later. Rescheduling keeps it from starting before this date and its successors follow.',
          })}
        </span>
      </span>
      <button
        type="button"
        data-testid="activity-start-floor-clear"
        disabled={clear.isPending}
        onClick={() => clear.mutate()}
        className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border-light px-2 py-1 text-xs font-medium text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue"
      >
        {clear.isPending && <Loader2 size={12} className="animate-spin" />}
        {t('schedule.start_floor_clear', { defaultValue: 'Clear' })}
      </button>
    </div>
  );
}
