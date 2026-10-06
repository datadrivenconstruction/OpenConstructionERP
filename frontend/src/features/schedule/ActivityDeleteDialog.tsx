// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Trash2 } from 'lucide-react';
import { ConfirmDialog } from '@/shared/ui';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';

/** The activity about to be deleted and how many sit under it. */
export interface ActivityDeleteTarget {
  id: string;
  name: string;
  /** Activities directly under it: they move up one level when kept. */
  childCount: number;
  /** Activities under it at every depth: they all go when deleted with it. */
  descendantCount: number;
}

/**
 * Work out the delete target for an activity from the schedule's activities.
 */
export function activityDeleteTarget(
  activity: { id: string; name: string },
  activities: ReadonlyArray<{ id: string; parent_id?: string | null }>,
): ActivityDeleteTarget {
  const children = new Map<string, string[]>();
  for (const a of activities) {
    if (!a.parent_id) continue;
    const list = children.get(a.parent_id) ?? [];
    list.push(a.id);
    children.set(a.parent_id, list);
  }
  const seen = new Set<string>([activity.id]);
  const queue = [...(children.get(activity.id) ?? [])];
  while (queue.length) {
    const id = queue.shift() as string;
    if (seen.has(id)) continue;
    seen.add(id);
    queue.push(...(children.get(id) ?? []));
  }
  return {
    id: activity.id,
    name: activity.name,
    childCount: (children.get(activity.id) ?? []).length,
    descendantCount: seen.size - 1,
  };
}

/**
 * Asks before an activity is deleted.
 *
 * An activity with nothing under it gets the plain confirmation. A summary
 * offers the two things a planner may mean: delete it with every activity
 * under it, or delete only the summary and keep its activities, which move
 * up one level under the summary's own parent.
 */
export function ActivityDeleteDialog({
  target,
  loading = false,
  onCancel,
  onDelete,
}: {
  target: ActivityDeleteTarget | null;
  loading?: boolean;
  onCancel: () => void;
  onDelete: (cascade: boolean) => void;
}) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);
  const open = !!target && target.childCount > 0;

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onCancel();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, onCancel]);
  useFocusTrap(dialogRef, open);

  if (!target) return null;
  if (target.childCount === 0) {
    return (
      <ConfirmDialog
        open
        loading={loading}
        title={t('schedule.confirm_delete_activity_title', { defaultValue: 'Delete activity?' })}
        message={t('schedule.confirm_delete_activity', {
          defaultValue: 'Delete "{{name}}" and its links to other activities? This cannot be undone.',
          name: target.name,
        })}
        onCancel={onCancel}
        onConfirm={() => onDelete(false)}
      />
    );
  }

  const title = t('schedule.confirm_delete_activity_title', { defaultValue: 'Delete activity?' });
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in" onMouseDown={onCancel} />
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        aria-describedby="activity-delete-message"
        tabIndex={-1}
        className="relative z-10 w-full max-w-md mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in focus:outline-none"
      >
        <div className="px-6 pt-6 pb-4">
          <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full mb-4 bg-semantic-error/10 text-semantic-error">
            <Trash2 size={20} />
          </div>
          <h2 className="text-base font-semibold text-content-primary text-center">{title}</h2>
          <p id="activity-delete-message" className="mt-2 text-sm text-content-secondary text-center leading-relaxed">
            {t('schedule.confirm_delete_section', {
              defaultValue:
                '"{{name}}" holds {{count}} activities. Delete them with it, or keep them: they move up one level. This cannot be undone.',
              name: target.name,
              count: target.descendantCount,
            })}
          </p>
        </div>
        <div className="flex flex-col gap-2 px-6 pb-6">
          <button
            type="button"
            disabled={loading}
            data-testid="activity-delete-with-children"
            onClick={() => onDelete(true)}
            className="inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium text-content-inverse bg-semantic-error hover:opacity-90 disabled:opacity-40 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-semantic-error focus-visible:ring-offset-2"
          >
            {loading && <Loader2 size={14} className="animate-spin" />}
            {t('schedule.delete_section_with_children', {
              defaultValue: 'Delete with its {{count}} activities',
              count: target.descendantCount,
            })}
          </button>
          <button
            type="button"
            disabled={loading}
            data-testid="activity-delete-keep-children"
            onClick={() => onDelete(false)}
            className="rounded-lg px-4 py-2.5 text-sm font-medium border border-border bg-surface-primary text-content-primary hover:bg-surface-secondary disabled:opacity-40 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2"
          >
            {t('schedule.delete_section_keep_children', {
              defaultValue: 'Keep the activities (they move up a level)',
            })}
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={onCancel}
            className="rounded-lg px-4 py-2.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-40 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2"
          >
            {t('confirm_dialog.cancel', { defaultValue: 'Cancel' })}
          </button>
        </div>
      </div>
    </div>
  );
}
