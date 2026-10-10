// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { TFunction } from 'i18next';
import type { ConfirmOptions } from '@/shared/hooks/useConfirm';
import type { Schedule } from './api';

/** Only the four restorable server states are trusted; old archives become draft. */
export function scheduleRestoreStatus(schedule: Schedule): { status: string; legacy: boolean } {
  const history = schedule.metadata_?._schedule_archive;
  const previous = history && typeof history === 'object' && 'previous_status' in history
    ? history.previous_status : null;
  const known = typeof previous === 'string' && ['draft', 'active', 'completed', 'frozen'].includes(previous);
  return { status: known ? previous : 'draft', legacy: !known };
}

export function scheduleArchiveConfirmation(t: TFunction, schedule: Schedule): ConfirmOptions {
  return {
    title: t('schedule.archive_confirm_title'),
    message: t('schedule.archive_confirm_body', { name: schedule.name }),
    confirmLabel: t('common.archive'),
  };
}

export function scheduleRestoreConfirmation(t: TFunction, schedule: Schedule): ConfirmOptions {
  const previous = scheduleRestoreStatus(schedule);
  return {
    title: t('schedule.restore_confirm_title'),
    message: [t('schedule.restore_confirm_body', {
      name: schedule.name, status: t(`schedule.status_${previous.status}`, { defaultValue: previous.status }),
    }), previous.legacy ? t('schedule.restore_legacy_status') : ''].filter(Boolean).join(' '),
    confirmLabel: t('common.restore'),
  };
}

/**
 * What replacing a schedule's activities does to the contract payment
 * instalments waiting for its milestones: those whose milestone the new plan
 * has again move to it, the rest go back to their contract dates.
 */
export function replaceInstalmentSentences(t: TFunction, relinked = 0, unlinked = 0): string[] {
  const out: string[] = [];
  if (relinked > 0) {
    out.push(
      t('schedule.replace_instalments_relinked', {
        defaultValue: '{{count}} contract payment instalments move to the same milestone in the new plan.',
        count: relinked,
      }),
    );
  }
  if (unlinked > 0) {
    out.push(
      t('schedule.replace_instalments_unlinked', {
        defaultValue:
          '{{count}} contract payment instalments lose their milestone and go back to their contract dates.',
        count: unlinked,
      }),
    );
  }
  return out;
}

/**
 * Why this caller cannot permanently delete the archive, or null when they can.
 *
 * Read before confirmation; permanent deletion requires an archive and the project owner or an admin.
 */
export function scheduleDeleteBlocked(
  t: TFunction,
  impact: { baseline_count?: number; can_delete?: boolean; blocked_reason?: string | null },
): string | null {
  if (impact.can_delete !== false) return null;
  if (impact.blocked_reason === 'schedule_not_archived') return t('schedule.archive_before_purge');
  if (impact.blocked_reason === 'schedule_has_baselines') {
    return t('schedule.error_schedule_has_baselines', {
      defaultValue:
        'This schedule has {{count}} baselines. Deleting the schedule deletes them too, and only an administrator can delete baselines. Ask an administrator to delete the schedule, or to delete its baselines first; then you can delete it.',
      count: impact.baseline_count ?? 0,
    });
  }
  return t('schedule.purge_admin_only');
}

/**
 * What deleting a whole schedule does, from what the server counted.
 *
 * An empty draft gets the short sentence. Anything else (a schedule in use,
 * or one with activities) names its status and how many activities go with
 * it, then the baselines that go too and the contract payment instalments
 * that follow its milestones, which stay and go back to their contract dates.
 */
export function scheduleDeleteConfirmation(
  t: TFunction,
  schedule: { name: string; status: string },
  impact: { activity_count: number; baseline_count?: number; payment_milestone_count?: number },
): ConfirmOptions {
  const activityCount = impact.activity_count;
  const baselineCount = impact.baseline_count ?? 0;
  const paymentCount = impact.payment_milestone_count ?? 0;
  const plain = schedule.status === 'draft' && activityCount === 0;
  const parts = [
    plain
      ? t('schedule.confirm_delete', {
          defaultValue: 'This will permanently delete the schedule and all its activities. This cannot be undone.',
        })
      : t('schedule.confirm_delete_named', {
          defaultValue:
            '"{{name}}" is {{status}} and has {{count}} activities. Deleting it removes the schedule, all its activities and the links between them. This cannot be undone.',
          name: schedule.name,
          status: t(`schedule.status_${schedule.status}`, { defaultValue: schedule.status }),
          count: activityCount,
        }),
  ];
  // Baselines are records kept for later comparison and disputes; deleting
  // the schedule takes them too, and only an administrator may do that.
  if (baselineCount > 0) {
    parts.push(
      t('schedule.confirm_delete_baselines', {
        defaultValue: 'Its {{count}} baselines are deleted with it.',
        count: baselineCount,
      }),
    );
  }
  if (paymentCount > 0) {
    parts.push(
      t('schedule.confirm_delete_payment_milestones', {
        defaultValue:
          '{{count}} contract payment instalments follow its milestones. They stay, and go back to their contract dates.',
        count: paymentCount,
      }),
    );
  }
  return {
    title: t('schedule.confirm_delete_title', { defaultValue: 'Delete schedule?' }),
    message: parts.join(' '),
    confirmLabel: t('schedule.purge'),
  };
}
