/**
 * CreateTaskFromDwgModal — inline "+ New task" flow from the DWG takeoff
 * viewer.
 *
 * Mirrors CreateTaskFromBIMModal — the user clicks "+ New task" inside
 * the Properties tab of a selected DWG entity, this modal opens with the
 * title pre-filled, the user adjusts and clicks Create. POST to /tasks/
 * with the dwg entity ids + drawing id stashed in `metadata` (the tasks
 * backend already accepts free-form metadata JSON, so no schema change
 * is required — consumers can find DWG-linked tasks by filtering
 * `metadata.dwg_entity_ids`).
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { X, ListChecks, Loader2, Plus } from 'lucide-react';
import { createTask, type TaskType, type TaskPriority } from '@/features/tasks/api';
import { useToastStore } from '@/stores/useToastStore';

interface CreateTaskFromDwgModalProps {
  projectId: string;
  /** DWG entity ids the new task will be pinned to. */
  entityIds: string[];
  /** DWG drawing the entities belong to — stored alongside the ids so
   *  consumers know which drawing to navigate to. */
  drawingId: string;
  /** Optional display name shown in the modal header (e.g. the selected
   *  entity's layer or type). Falls back to the entity-count phrasing. */
  entityLabel?: string;
  onClose: () => void;
  /** Called after the task is created — typically the parent invalidates
   *  a relevant query so the new badge appears instantly. */
  onCreated?: () => void;
}

const PRIORITY_COLORS: Record<TaskPriority, string> = {
  low: 'text-content-tertiary',
  normal: 'text-content-secondary',
  high: 'text-amber-600',
  urgent: 'text-rose-600',
};

export default function CreateTaskFromDwgModal({
  projectId,
  entityIds,
  drawingId,
  entityLabel,
  onClose,
  onCreated,
}: CreateTaskFromDwgModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const TASK_TYPES: { value: TaskType; label: string }[] = [
    { value: 'task', label: t('tasks.type_task', { defaultValue: 'Task' }) },
    { value: 'topic', label: t('tasks.type_topic', { defaultValue: 'Topic' }) },
    { value: 'information', label: t('tasks.type_information', { defaultValue: 'Info' }) },
    { value: 'decision', label: t('tasks.type_decision', { defaultValue: 'Decision' }) },
  ];

  const PRIORITIES: { value: TaskPriority; label: string; color: string }[] = [
    { value: 'low', label: t('tasks.priority_low', { defaultValue: 'Low' }), color: PRIORITY_COLORS.low },
    { value: 'normal', label: t('tasks.priority_normal', { defaultValue: 'Normal' }), color: PRIORITY_COLORS.normal },
    { value: 'high', label: t('tasks.priority_high', { defaultValue: 'High' }), color: PRIORITY_COLORS.high },
    { value: 'urgent', label: t('tasks.priority_urgent', { defaultValue: 'Urgent' }), color: PRIORITY_COLORS.urgent },
  ];

  const defaultTitle = entityLabel
    ? t('dwg_takeoff.issue_on_entity', {
        defaultValue: 'Issue on {{name}}',
        name: entityLabel,
      })
    : t('dwg_takeoff.issue_on_entities', {
        defaultValue: 'Issue on {{count}} DWG entity/entities',
        count: entityIds.length,
      });

  const [title, setTitle] = useState(defaultTitle);
  const [description, setDescription] = useState('');
  const [taskType, setTaskType] = useState<TaskType>('task');
  const [priority, setPriority] = useState<TaskPriority>('normal');
  const [dueDate, setDueDate] = useState('');

  const createMut = useMutation({
    mutationFn: () =>
      createTask({
        project_id: projectId,
        title: title.trim(),
        description: description.trim() || undefined,
        task_type: taskType,
        priority,
        due_date: dueDate || undefined,
        // DWG link is stashed in metadata so we don't need a backend schema
        // change; consumers filter by `metadata.dwg_entity_ids`.
        metadata: {
          dwg_drawing_id: drawingId,
          dwg_entity_ids: entityIds,
        },
      }),
    onSuccess: (task) => {
      addToast({
        type: 'success',
        title: t('dwg_takeoff.task_created_title', { defaultValue: 'Task created' }),
        message: t('dwg_takeoff.task_created_msg', {
          defaultValue: '"{{title}}" pinned to {{count}} DWG entity/entities',
          title: task.title,
          count: entityIds.length,
        }),
      });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      onCreated?.();
      onClose();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err.message || String(err),
      });
    },
  });

  const canSubmit = title.trim().length > 0 && !createMut.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="bg-surface-primary rounded-xl shadow-2xl w-full max-w-md flex flex-col border border-border-light"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border-light shrink-0">
          <div className="flex items-center gap-2">
            <ListChecks size={16} className="text-amber-600" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t('dwg_takeoff.create_task_title', {
                defaultValue: 'Create task pinned to DWG entity',
              })}
            </h2>
            <span className="text-[11px] text-content-tertiary">
              {entityIds.length === 1
                ? entityLabel || t('dwg_takeoff.entity', { defaultValue: 'Entity' })
                : t('dwg_takeoff.create_task_bulk', {
                    defaultValue: '{{count}} entities',
                    count: entityIds.length,
                  })}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <div className="p-5 space-y-3">
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
              {t('dwg_takeoff.task_title', { defaultValue: 'Title' })}
              <span className="text-rose-500 ml-0.5">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
              className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
              {t('dwg_takeoff.task_description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder={t('dwg_takeoff.task_description_placeholder', {
                defaultValue: 'What needs to be done?',
              })}
              className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue resize-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
                {t('dwg_takeoff.task_type', { defaultValue: 'Type' })}
              </label>
              <select
                value={taskType}
                onChange={(e) => setTaskType(e.target.value as TaskType)}
                className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              >
                {TASK_TYPES.map((tt) => (
                  <option key={tt.value} value={tt.value}>
                    {tt.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
                {t('dwg_takeoff.task_priority', { defaultValue: 'Priority' })}
              </label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value as TaskPriority)}
                className={`w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue ${
                  PRIORITIES.find((p) => p.value === priority)?.color ?? ''
                }`}
              >
                {PRIORITIES.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
              {t('dwg_takeoff.task_due_date', { defaultValue: 'Due date (optional)' })}
            </label>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
          </div>

          {/* Entity pin info */}
          <div className="rounded-md border border-amber-300/40 bg-amber-50/40 dark:bg-amber-950/20 px-2.5 py-2 text-[11px] text-amber-700 dark:text-amber-300">
            <div className="flex items-start gap-1.5">
              <ListChecks size={11} className="shrink-0 mt-0.5" />
              <span>
                {t('dwg_takeoff.task_pin_note', {
                  defaultValue:
                    'This task will be linked to {{count}} DWG entity/entities. Consumers can locate the drawing and entity via the task metadata.',
                  count: entityIds.length,
                })}
              </span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-content-tertiary hover:text-content-primary px-2"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={() => createMut.mutate()}
            disabled={!canSubmit}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50"
          >
            {createMut.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Plus size={12} />
            )}
            {t('dwg_takeoff.task_create', { defaultValue: 'Create task' })}
          </button>
        </div>
      </div>
    </div>
  );
}
