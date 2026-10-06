// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Archive, RotateCcw, Trash2 } from 'lucide-react';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { Button, ConfirmDialog } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { scheduleApi, type Schedule } from './api';
import { scheduleErrorMessage } from './errors';
import {
  scheduleArchiveConfirmation, scheduleRestoreConfirmation,
  scheduleDeleteBlocked, scheduleDeleteConfirmation,
} from './confirmations';

/** Shared by cards and detail: archive is never a disguised permanent delete. */
export function ScheduleLifecycleActions({ schedule, onChanged, compact = false }: {
  schedule: Schedule; onChanged?: () => void; compact?: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const canArchive = useHasPermission('schedule.delete');
  const canPurge = useHasPermission('schedule.purge');
  const [busy, setBusy] = useState(false);
  const { confirm, ...confirmProps } = useConfirm();
  const archived = schedule.status === 'archived';

  const act = async (action: 'archive' | 'restore' | 'purge') => {
    if (busy) return;
    setBusy(true);
    try {
      let confirmed: boolean;
      if (action === 'purge') {
        const impact = await scheduleApi.getDeleteImpact(schedule.id);
        const blocked = scheduleDeleteBlocked(t, impact);
        if (blocked) {
          toast({ type: 'warning', title: t('schedule.delete_blocked_title'), message: blocked });
          return;
        }
        confirmed = await confirm(scheduleDeleteConfirmation(t, schedule, impact));
      } else {
        confirmed = await confirm(action === 'archive'
          ? scheduleArchiveConfirmation(t, schedule) : scheduleRestoreConfirmation(t, schedule));
      }
      if (!confirmed) return;
      if (action === 'archive') {
        await scheduleApi.archiveSchedule(schedule.id);
        toast({ type: 'success', title: t('schedule.archived') });
      } else if (action === 'restore') {
        const restored = await scheduleApi.restoreSchedule(schedule.id);
        const history = restored.metadata_?._schedule_archive;
        const legacy = history && typeof history === 'object' && 'restore_used_fallback' in history
          && history.restore_used_fallback === true;
        toast({ type: 'success', title: t('schedule.restored', {
          status: t(`schedule.status_${restored.status}`, { defaultValue: restored.status }),
        }), message: legacy ? t('schedule.restore_legacy_status') : undefined });
      } else {
        await scheduleApi.purgeSchedule(schedule.id);
        toast({ type: 'success', title: t('schedule.deleted') });
      }
      await queryClient.invalidateQueries({ queryKey: ['schedules'] });
      onChanged?.();
    } catch (error) {
      toast({ type: 'error', title: t('toasts.error'), message: scheduleErrorMessage(error, t) });
    } finally {
      setBusy(false);
    }
  };

  return <div className="flex shrink-0 flex-wrap items-center gap-1" onClick={(event) => event.stopPropagation()}>
    {canArchive && <Button variant="ghost" size="sm" disabled={busy}
      aria-label={t(archived ? 'schedule.restore_named' : 'schedule.archive_named', { name: schedule.name })}
      title={t(archived ? 'common.restore' : 'common.archive')}
      icon={archived ? <RotateCcw size={14} /> : <Archive size={14} />}
      onClick={() => void act(archived ? 'restore' : 'archive')}>
      {!compact && t(archived ? 'common.restore' : 'common.archive')}
    </Button>}
    {archived && canPurge && <Button variant="ghost" size="sm" disabled={busy}
      aria-label={t('schedule.purge_named', { name: schedule.name })} title={t('schedule.purge')}
      icon={<Trash2 size={14} />} onClick={() => void act('purge')}>
      {!compact && t('schedule.purge')}
    </Button>}
    <ConfirmDialog {...confirmProps} />
  </div>;
}
