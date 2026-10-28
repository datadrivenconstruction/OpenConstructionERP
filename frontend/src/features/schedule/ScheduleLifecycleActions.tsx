// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Archive, RotateCcw, Trash2 } from 'lucide-react';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { Button, ConfirmDialog } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { scheduleApi, type Schedule } from './api';
import { scheduleErrorMessage } from './errors';
import {
  scheduleArchiveConfirmation, scheduleRestoreConfirmation,
  scheduleDeleteBlocked, scheduleDeleteConfirmation, scheduleDeleteNeedsArchiveConfirmation,
} from './confirmations';

/** Shared by cards and detail: archive is never a disguised permanent delete. */
export function ScheduleLifecycleActions({ schedule, onChanged, compact = false }: {
  schedule: Schedule; onChanged?: () => void; compact?: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const canArchive = useHasPermission('schedule.delete');
  const isPurgeAdmin = useHasPermission('schedule.purge');
  const [busy, setBusy] = useState(false);
  const { confirm, ...confirmProps } = useConfirm();
  const archived = schedule.status === 'archived';
  // The project owner may delete an archive too; the server knows who owns it,
  // so ask it rather than offer a Delete it would refuse.
  const impact = useQuery({
    queryKey: ['schedule-delete-impact', schedule.id],
    queryFn: () => scheduleApi.getDeleteImpact(schedule.id),
    enabled: archived && canArchive && !isPurgeAdmin,
    staleTime: 60_000,
  });
  const canPurge = archived && (isPurgeAdmin || impact.data?.can_delete === true
    || impact.data?.blocked_reason === 'schedule_has_baselines');

  // ``delete_active`` is Delete pressed on a schedule that is still in use:
  // it cannot be deleted directly, so the dialog says why and offers the
  // archive that has to come first.
  const purgeBlocked = !canPurge && impact.data ? scheduleDeleteBlocked(t, impact.data) : null;

  const act = async (action: 'archive' | 'restore' | 'purge' | 'delete_active') => {
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
      } else if (action === 'delete_active') {
        confirmed = await confirm(scheduleDeleteNeedsArchiveConfirmation(t, schedule));
      } else {
        confirmed = await confirm(action === 'archive'
          ? scheduleArchiveConfirmation(t, schedule) : scheduleRestoreConfirmation(t, schedule));
      }
      if (!confirmed) return;
      if (action === 'archive' || action === 'delete_active') {
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
      await queryClient.invalidateQueries({ queryKey: ['schedule-delete-impact', schedule.id] });
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
      title={archived ? t('common.restore') : t('schedule.archive_then_delete_hint', {
        defaultValue: 'Archive this schedule. Once archived, the project owner can delete it permanently.',
      })}
      icon={archived ? <RotateCcw size={14} /> : <Archive size={14} />}
      onClick={() => void act(archived ? 'restore' : 'archive')}>
      {!compact && t(archived ? 'common.restore' : 'common.archive')}
    </Button>}
    {/* Delete is always where people look for it. On a schedule still in use
        it explains that archiving comes first, says who may delete the
        archive, and offers the archiving. */}
    {canArchive && !archived && <Button variant="ghost" size="sm" disabled={busy}
      aria-label={t('schedule.delete_named', { defaultValue: 'Delete {{name}}', name: schedule.name })}
      title={t('schedule.delete_needs_archive_title', { defaultValue: 'Deleting starts with archiving' })}
      icon={<Trash2 size={14} />} onClick={() => void act('delete_active')}>
      {!compact && t('common.delete', { defaultValue: 'Delete' })}
    </Button>}
    {archived && canPurge && <Button variant="ghost" size="sm" disabled={busy}
      aria-label={t('schedule.purge_named', { name: schedule.name })} title={t('schedule.purge')}
      icon={<Trash2 size={14} />} onClick={() => void act('purge')}>
      {!compact && t('schedule.purge')}
    </Button>}
    {/* An archive this caller may not delete keeps a Delete, switched off,
        with the reason in words beside it: a tooltip is not there on touch. */}
    {archived && canArchive && purgeBlocked && <>
      <Button variant="ghost" size="sm" disabled
        aria-label={t('schedule.purge_named', { name: schedule.name })} title={purgeBlocked}
        icon={<Trash2 size={14} />}>
        {!compact && t('schedule.purge')}
      </Button>
      <span className="basis-full text-xs text-content-tertiary" data-testid="schedule-purge-blocked">
        {purgeBlocked}
      </span>
    </>}
    <ConfirmDialog {...confirmProps} />
  </div>;
}
