// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { TFunction } from 'i18next';
import { ApiError, getErrorMessage } from '@/shared/lib/api';

/**
 * A refusal the schedule endpoints send as ``{detail: {error, message, ...}}``.
 *
 * ``error`` is a stable code and the rest are the values its sentence needs.
 * The English ``message`` is for API clients; the screen says it in the
 * reader's language from the code.
 */
export interface ScheduleErrorDetail {
  error: string;
  message?: string;
  [param: string]: unknown;
}

/** The coded detail of a schedule API error, or ``null`` when it carries none. */
export function scheduleErrorDetail(err: unknown): ScheduleErrorDetail | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null | undefined;
  const detail = body?.detail;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  const code = (detail as Record<string, unknown>).error;
  return typeof code === 'string' && code.length > 0 ? (detail as ScheduleErrorDetail) : null;
}

/**
 * Say a schedule API error in the reader's language.
 *
 * Coded refusals map to their own sentence; anything else falls back to the
 * shared message (which already prefers the server's detail).
 */
export function scheduleErrorMessage(err: unknown, t: TFunction): string {
  const detail = scheduleErrorDetail(err);
  switch (detail?.error) {
    case 'schedule_not_archived':
      return t('schedule.archive_before_purge');
    case 'schedule_restore_status_mismatch':
      return t('schedule.restore_previous_first');
    case 'schedule_has_activities':
      return t('schedule.error_schedule_has_activities', {
        defaultValue: 'This schedule already has {{count}} activities.',
        count: Number(detail.activity_count ?? 0),
      });
    case 'boq_not_found':
      return t('schedule.error_boq_not_found', {
        defaultValue: 'This BOQ was not found in this project. It may have been deleted; pick another one.',
      });
    case 'boq_has_no_positions':
      return t('schedule.error_boq_has_no_positions', {
        defaultValue:
          'This BOQ has no positions with work in them yet, so there is nothing to schedule. Add positions to its sections first.',
      });
    case 'schedule_generation_failed':
      return t('schedule.error_generation_failed', {
        defaultValue:
          'The schedule could not be generated from this BOQ. Please try again; if it keeps failing, contact support and quote reference {{reference}}.',
        reference: String(detail.reference ?? ''),
      });
    case 'schedule_dependency_self':
      return t('schedule.error_dependency_self', { defaultValue: 'An activity cannot depend on itself.' });
    case 'schedule_dependency_cycle':
      return t('schedule.error_dependency_cycle', {
        defaultValue: 'This link would make the schedule loop back on itself, so it was not added.',
      });
    case 'schedule_activity_not_in_schedule':
      return t('schedule.error_activity_not_in_schedule', {
        defaultValue: 'Both activities must belong to this schedule.',
      });
    case 'schedule_has_baselines':
      return t('schedule.error_schedule_has_baselines', {
        defaultValue:
          'This schedule has {{count}} baselines. Deleting the schedule deletes them too, and only an administrator can delete baselines. Ask an administrator to delete the schedule, or to delete its baselines first; then you can delete it.',
        count: Number(detail.baseline_count ?? 0),
      });
    case 'relationship_not_found':
      return t('schedule.error_relationship_not_found', {
        defaultValue: 'This link is no longer there. The chart shows the links as they are now.',
      });
    default:
      // A refusal by role carries no code of its own; say it in the reader's
      // language rather than show the server's English.
      if (!detail && err instanceof ApiError && err.status === 403) {
        return t('schedule.error_missing_permission', {
          defaultValue: 'Your role does not allow this. Ask an editor or an administrator.',
        });
      }
      return getErrorMessage(err);
  }
}
