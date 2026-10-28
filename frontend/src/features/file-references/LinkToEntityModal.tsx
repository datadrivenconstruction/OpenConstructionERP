// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Modal that lets the user link the current file to any target entity.
 *
 * The target_id is a free-form string here — host pages are expected
 * to provide their own typeahead source when the user picks a target
 * type. For now the modal renders a select for the type and a plain
 * text field for the id (alongside an optional human label), which is
 * sufficient for the v1 ship: the file manager's link button always
 * has a known target id (the user is "linking *to* this RFI" coming
 * from the RFI page).
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Button } from '@/shared/ui/Button';
import { useToastStore } from '@/stores/useToastStore';
import { useCreateReference } from './hooks';
import type { FileKind, TargetType } from './types';

const TARGET_TYPES: ReadonlyArray<{ value: TargetType; label: string }> = [
  { value: 'rfi', label: 'RFI' },
  { value: 'issue', label: 'Issue' },
  { value: 'task', label: 'Task' },
  { value: 'submittal', label: 'Submittal' },
  { value: 'punch_item', label: 'Punch item' },
  { value: 'change_order', label: 'Change order' },
  { value: 'meeting', label: 'Meeting' },
  { value: 'field_report', label: 'Field report' },
  { value: 'tender_package', label: 'Tender package' },
  { value: 'bid', label: 'Bid' },
  { value: 'contract', label: 'Contract' },
  { value: 'transmittal', label: 'Transmittal' },
  { value: 'inspection', label: 'Inspection' },
  { value: 'ncr', label: 'NCR' },
  { value: 'bcf_topic', label: 'BCF topic' },
  { value: 'boq_position', label: 'BOQ position' },
  { value: 'project', label: 'Project' },
  { value: 'clash_run', label: 'Clash run' },
];

export interface LinkToEntityModalProps {
  open: boolean;
  projectId: string;
  fileKind: FileKind;
  fileId: string;
  /** Optional preselect to skip the type chooser. */
  initialTargetType?: TargetType;
  onClose: () => void;
  onCreated?: (referenceId: string) => void;
}

export function LinkToEntityModal({
  open,
  projectId,
  fileKind,
  fileId,
  initialTargetType,
  onClose,
  onCreated,
}: LinkToEntityModalProps) {
  const { t } = useTranslation();
  const [targetType, setTargetType] = useState<TargetType>(
    initialTargetType ?? 'rfi',
  );
  const [targetId, setTargetId] = useState('');
  const [targetLabel, setTargetLabel] = useState('');
  const [relation, setRelation] = useState('references');
  const addToast = useToastStore((s) => s.addToast);
  const createMut = useCreateReference({ projectId, kind: fileKind, fileId });

  const reset = useCallback(() => {
    setTargetType(initialTargetType ?? 'rfi');
    setTargetId('');
    setTargetLabel('');
    setRelation('references');
  }, [initialTargetType]);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [onClose, reset]);

  const handleSubmit = useCallback(() => {
    if (!targetId.trim()) return;
    createMut.mutate(
      {
        project_id: projectId,
        file_kind: fileKind,
        file_id: fileId,
        target_type: targetType,
        target_id: targetId.trim(),
        relation: relation.trim() || 'references',
        target_label: targetLabel.trim() || null,
      },
      {
        onSuccess: (ref) => {
          addToast({
            type: 'success',
            title: t('files.link.created', {
              defaultValue: 'File linked',
            }),
          });
          onCreated?.(ref.id);
          handleClose();
        },
        onError: (err) => {
          addToast({
            type: 'error',
            title: t('files.link.failed', {
              defaultValue: 'Could not link file',
            }),
            message: err instanceof Error ? err.message : undefined,
          });
        },
      },
    );
  }, [
    targetId,
    createMut,
    projectId,
    fileKind,
    fileId,
    targetType,
    relation,
    targetLabel,
    addToast,
    t,
    onCreated,
    handleClose,
  ]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="link-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
      data-testid="link-to-entity-modal"
    >
      <div
        className={clsx(
          'w-full max-w-md rounded-xl bg-surface-primary p-5 shadow-xl',
        )}
      >
        <h2
          id="link-modal-title"
          className="text-base font-semibold text-content-primary"
        >
          {t('files.link.title', { defaultValue: 'Link file to entity' })}
        </h2>
        <p className="mt-0.5 text-xs text-content-tertiary">
          {t('files.link.desc', {
            defaultValue:
              'Connect this file to an RFI, task, submittal, or other project entity.',
          })}
        </p>

        <div className="mt-4 space-y-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-content-secondary">
              {t('files.link.target_type', { defaultValue: 'Entity type' })}
            </span>
            <select
              value={targetType}
              onChange={(e) => setTargetType(e.target.value as TargetType)}
              className="rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              data-testid="link-target-type"
            >
              {TARGET_TYPES.map((tt) => (
                <option key={tt.value} value={tt.value}>
                  {tt.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-content-secondary">
              {t('files.link.target_id', {
                defaultValue: 'Entity ID',
              })}
            </span>
            <input
              type="text"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              placeholder="00000000-0000-0000-0000-000000000000"
              className="rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              data-testid="link-target-id"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-content-secondary">
              {t('files.link.target_label', {
                defaultValue: 'Display label (optional)',
              })}
            </span>
            <input
              type="text"
              value={targetLabel}
              onChange={(e) => setTargetLabel(e.target.value)}
              placeholder="RFI-142"
              className="rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              data-testid="link-target-label"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-content-secondary">
              {t('files.link.relation', { defaultValue: 'Relation' })}
            </span>
            <input
              type="text"
              value={relation}
              onChange={(e) => setRelation(e.target.value)}
              placeholder="references"
              maxLength={32}
              className="rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
          </label>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={handleClose} type="button">
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            disabled={!targetId.trim() || createMut.isPending}
            loading={createMut.isPending}
            type="button"
            data-testid="link-submit"
          >
            {t('files.link.submit', { defaultValue: 'Create link' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
