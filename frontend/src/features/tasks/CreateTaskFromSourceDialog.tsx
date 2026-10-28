// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cross-module "Create task" quick action.
 *
 * Turns an incoming letter (Correspondence), a Request for Information
 * (RFI), or a captured inbound message into an actionable Task in one
 * submit. Prefills the title from the source's subject, a description
 * that links back to the source record, the due date from any
 * response-required-by date, and the assignee when the caller can
 * derive one - then creates the task with a single click.
 *
 * The created task is traceable back to the letter/RFI/message it came
 * from via `metadata.source` / `metadata.source_id` / `metadata.source_label`
 * - the same convention the meeting and inspection flows already use
 * (see TasksPage's "Source / BIM indicators" block), extended with the
 * two new source kinds this dialog introduces (`correspondence`,
 * `inbound_capture`) alongside the existing `rfi`.
 *
 * No backend change: this hits the existing `POST /v1/tasks/` endpoint.
 * The Task model has no dedicated source columns, so the link is carried
 * in the free-form `metadata` JSON column exactly like the DWG takeoff
 * page already does for `dwg_drawing_id` / `dwg_entity_ids`.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Button } from '@/shared/ui/Button';
import { UserSearchInput } from '@/shared/ui/UserSearchInput';
import { useToastStore } from '@/stores/useToastStore';
import { createTask, type Task } from './api';

/** The record kinds this quick action can spawn a task from. */
export type TaskSourceType = 'correspondence' | 'rfi' | 'inbound_capture';

export interface CreateTaskFromSourceDialogProps {
  /** Project the source record (and so the new task) belongs to. */
  projectId: string;
  /** Which module the source record lives in. */
  sourceType: TaskSourceType;
  /** The source record's id - stored on the task for traceability. */
  sourceId: string;
  /** Human label for the source (e.g. "COR-005", "RFI-012"). */
  sourceLabel: string;
  /** Prefilled task title - usually the source's subject. */
  defaultTitle: string;
  /** Prefilled description - usually a back-link line to the source. */
  defaultDescription?: string;
  /** Prefilled due date (YYYY-MM-DD), e.g. a response-required-by date. */
  defaultDueDate?: string | null;
  /** Prefilled assignee UUID, when one can be derived from the source. */
  defaultAssigneeId?: string | null;
  /** Prefilled assignee display name, paired with defaultAssigneeId. */
  defaultAssigneeName?: string | null;
  onClose: () => void;
  onCreated?: (task: Task) => void;
}

const INPUT_CLASS =
  'rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

/** Label shown in the "From" line for each source kind. */
function sourceKindLabel(
  t: (key: string, opts?: Record<string, unknown>) => string,
  sourceType: TaskSourceType,
): string {
  switch (sourceType) {
    case 'rfi':
      return t('tasks.from_source_rfi', { defaultValue: 'RFI' });
    case 'inbound_capture':
      return t('tasks.from_source_inbound', { defaultValue: 'captured message' });
    default:
      return t('tasks.from_source_correspondence', { defaultValue: 'correspondence entry' });
  }
}

export function CreateTaskFromSourceDialog({
  projectId,
  sourceType,
  sourceId,
  sourceLabel,
  defaultTitle,
  defaultDescription,
  defaultDueDate,
  defaultAssigneeId,
  defaultAssigneeName,
  onClose,
  onCreated,
}: CreateTaskFromSourceDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [title, setTitle] = useState(defaultTitle);
  const [description, setDescription] = useState(
    defaultDescription ??
      t('tasks.from_source_desc_default', {
        defaultValue: 'Follow up on {{kind}} {{label}}.',
        kind: sourceKindLabel(t, sourceType),
        label: sourceLabel,
      }),
  );
  const [dueDate, setDueDate] = useState(defaultDueDate ?? '');
  const [assigneeId, setAssigneeId] = useState(defaultAssigneeId ?? '');
  const [assigneeName, setAssigneeName] = useState(defaultAssigneeName ?? '');

  const submitMut = useMutation<Task, Error, void>({
    mutationFn: async () => {
      const metadata: Record<string, unknown> = {
        source: sourceType,
        source_id: sourceId,
        source_label: sourceLabel,
      };
      if (assigneeId && assigneeName) metadata.assignee_name = assigneeName;
      return createTask({
        project_id: projectId,
        title: title.trim(),
        description: description.trim() || undefined,
        task_type: 'task',
        due_date: dueDate || undefined,
        responsible_id: assigneeId || undefined,
        metadata,
      });
    },
    onSuccess: (task) => {
      addToast({
        type: 'success',
        title: t('tasks.from_source_created_title', { defaultValue: 'Task created' }),
        message: t('tasks.from_source_created_msg', {
          defaultValue: 'Linked to {{kind}} {{label}}.',
          kind: sourceKindLabel(t, sourceType),
          label: sourceLabel,
        }),
      });
      onCreated?.(task);
      onClose();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('tasks.from_source_failed', { defaultValue: 'Could not create task' }),
        message: err instanceof Error ? err.message : undefined,
      });
    },
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const canSubmit = Boolean(title.trim()) && Boolean(projectId) && !submitMut.isPending;

  const handleSubmit = useCallback(() => {
    if (!canSubmit) return;
    submitMut.mutate();
  }, [canSubmit, submitMut]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-task-from-source-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="create-task-from-source-dialog"
    >
      <div className="w-full max-w-md rounded-xl bg-surface-primary p-5 shadow-xl">
        <h2
          id="create-task-from-source-title"
          className="text-start text-base font-semibold text-content-primary"
        >
          {t('tasks.from_source_dialog_title', { defaultValue: 'Create task' })}
        </h2>
        <p className="mt-0.5 text-start text-xs text-content-tertiary">
          {t('tasks.from_source_dialog_desc', {
            defaultValue: 'Raise a task tied to this {{kind}}. The new task links back to it.',
            kind: sourceKindLabel(t, sourceType),
          })}
        </p>

        <div className="mt-4 space-y-3">
          <label className="flex flex-col gap-1">
            <span className="text-start text-xs font-medium text-content-secondary">
              {t('tasks.from_source_title_label', { defaultValue: 'Title' })}
            </span>
            <input
              type="text"
              value={title}
              autoFocus
              onChange={(e) => setTitle(e.target.value)}
              className={INPUT_CLASS}
              data-testid="create-task-from-source-title-input"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-start text-xs font-medium text-content-secondary">
              {t('tasks.from_source_description_label', { defaultValue: 'Description' })}
            </span>
            <textarea
              value={description}
              rows={3}
              onChange={(e) => setDescription(e.target.value)}
              className={`${INPUT_CLASS} resize-none`}
              data-testid="create-task-from-source-description-input"
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-start text-xs font-medium text-content-secondary">
                {t('tasks.from_source_due_label', { defaultValue: 'Due date' })}
              </span>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className={INPUT_CLASS}
                data-testid="create-task-from-source-due-input"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-start text-xs font-medium text-content-secondary">
                {t('tasks.from_source_assignee_label', { defaultValue: 'Assignee' })}
              </span>
              <UserSearchInput
                value={assigneeId}
                displayValue={assigneeName}
                onChange={(id, name) => {
                  setAssigneeId(id);
                  setAssigneeName(name);
                }}
                placeholder={t('tasks.from_source_assignee_placeholder', {
                  defaultValue: 'Optional',
                })}
              />
            </label>
          </div>

          {!projectId && (
            <p
              className="text-start text-xs text-semantic-error"
              data-testid="create-task-from-source-no-project"
            >
              {t('tasks.from_source_no_project', {
                defaultValue: 'Open this record inside a project to create a task.',
              })}
            </p>
          )}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} type="button">
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            disabled={!canSubmit}
            loading={submitMut.isPending}
            type="button"
            data-testid="create-task-from-source-submit"
          >
            {t('tasks.from_source_submit', { defaultValue: 'Create task' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default CreateTaskFromSourceDialog;
