// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A milestone reaches the client portal only when someone ticks this box.
// Internal milestones ("pay the steel supplier") stay internal by default,
// the same rule the progress reports follow.

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Eye, Loader2 } from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { scheduleApi, type Activity } from './api';

export function MilestoneClientToggle({ scheduleId, activity }: { scheduleId: string; activity: Activity }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const checked = !!activity.client_visible;

  const mut = useMutation({
    mutationFn: (next: boolean) => scheduleApi.updateActivity(activity.id, { client_visible: next }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('schedule.client_visible_failed', { defaultValue: 'Could not change what the client sees.' }),
        message: getErrorMessage(err),
      }),
  });

  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border-light p-3">
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4 accent-oe-blue"
        checked={checked}
        disabled={mut.isPending}
        onChange={(e) => mut.mutate(e.target.checked)}
      />
      <span className="flex flex-col gap-0.5">
        <span className="flex items-center gap-1.5 text-sm font-medium text-content-primary">
          {mut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />}
          {t('schedule.client_visible_label', { defaultValue: 'Show this milestone to the client' })}
        </span>
        <span className="text-xs text-content-tertiary">
          {t('schedule.client_visible_hint', {
            defaultValue:
              'The client sees its name and expected date in the portal when it is due within two weeks or running late.',
          })}
        </span>
      </span>
    </label>
  );
}
