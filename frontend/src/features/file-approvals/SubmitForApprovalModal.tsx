// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Modal launched from the preview pane action: select a stamp template,
// add 1+ approval steps (ordered list of approvers), optional notes,
// then submit.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2, GripVertical } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { UserSearchInput } from '@/shared/ui/UserSearchInput';
import {
  WideModal,
  WideModalSection,
} from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';

import { StampPicker } from './StampPicker';
import { StampTemplateEditor } from './StampTemplateEditor';
import { useSubmitForApproval } from './hooks';
import type {
  ApprovalStepPayload,
  ApprovalWorkflowCreatePayload,
  FileKind,
} from './types';

interface SubmitForApprovalModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  fileKind: FileKind;
  fileId: string;
  fileVersion?: string | null;
  fileLabel?: string;
  onSubmitted?: (workflowId: string) => void;
}

interface StepDraft extends ApprovalStepPayload {
  uid: string;
  approverName: string;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function SubmitForApprovalModal({
  open,
  onClose,
  projectId,
  fileKind,
  fileId,
  fileVersion,
  fileLabel,
  onSubmitted,
}: SubmitForApprovalModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const submit = useSubmitForApproval();

  const [stampId, setStampId] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [steps, setSteps] = useState<StepDraft[]>([]);
  const [editorOpen, setEditorOpen] = useState(false);

  function addStep() {
    setSteps((prev) => [
      ...prev,
      { uid: uid(), approver_id: '', role_label: '', approverName: '' },
    ]);
  }

  function updateStep(uid_: string, patch: Partial<StepDraft>) {
    setSteps((prev) =>
      prev.map((s) => (s.uid === uid_ ? { ...s, ...patch } : s)),
    );
  }

  function removeStep(uid_: string) {
    setSteps((prev) => prev.filter((s) => s.uid !== uid_));
  }

  function moveStep(uid_: string, direction: -1 | 1) {
    setSteps((prev) => {
      const idx = prev.findIndex((s) => s.uid === uid_);
      if (idx === -1) return prev;
      const target = idx + direction;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[target]] = [next[target] as StepDraft, next[idx] as StepDraft];
      return next;
    });
  }

  async function handleSubmit() {
    const valid = steps.filter((s) => s.approver_id);
    if (valid.length === 0) {
      addToast({
        type: 'error',
        title: t('files.approvals.need_step', {
          defaultValue: 'Add at least one approver',
        }),
      });
      return;
    }
    const payload: ApprovalWorkflowCreatePayload = {
      project_id: projectId,
      file_kind: fileKind,
      file_id: fileId,
      file_version_snapshot: fileVersion ?? null,
      stamp_template_id: stampId,
      notes: notes.trim() || null,
      steps: valid.map((s) => ({
        approver_id: s.approver_id,
        role_label: s.role_label?.trim() || null,
      })),
    };
    try {
      const wf = await submit.mutateAsync(payload);
      addToast({
        type: 'success',
        title: t('files.approvals.submitted', {
          defaultValue: 'Submitted for approval',
        }),
      });
      onSubmitted?.(wf.id);
      // Reset for next time.
      setStampId(null);
      setNotes('');
      setSteps([]);
      onClose();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('files.approvals.submit_failed', {
          defaultValue: 'Submit failed',
        }),
        message: err instanceof Error ? err.message : undefined,
      });
    }
  }

  return (
    <>
      <WideModal
        open={open}
        onClose={onClose}
        title={t('files.approvals.modal_title', {
          defaultValue: 'Submit for approval',
        })}
        subtitle={fileLabel ?? `${fileKind} · ${fileId}`}
        size="lg"
        busy={submit.isPending}
        footer={
          <>
            <Button variant="secondary" onClick={onClose} disabled={submit.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              onClick={handleSubmit}
              loading={submit.isPending}
              disabled={steps.filter((s) => s.approver_id).length === 0}
            >
              {t('files.approvals.submit', { defaultValue: 'Submit' })}
            </Button>
          </>
        }
      >
        <WideModalSection
          title={t('files.approvals.stamp_section', {
            defaultValue: 'Stamp on final approval',
          })}
          columns={1}
        >
          <StampPicker
            projectId={projectId}
            value={stampId}
            onChange={setStampId}
            onCreateCustom={() => setEditorOpen(true)}
          />
        </WideModalSection>

        <WideModalSection
          title={t('files.approvals.steps_section', {
            defaultValue: 'Approval steps',
          })}
          description={t('files.approvals.steps_help', {
            defaultValue:
              'Approvers act in order. Each must approve before the next can act.',
          })}
          columns={1}
        >
          {steps.length === 0 ? (
            <p className="text-sm text-content-tertiary py-4 text-center border border-dashed border-border rounded-md">
              {t('files.approvals.no_steps', {
                defaultValue: 'No approvers yet. Click "Add step" to begin.',
              })}
            </p>
          ) : (
            <ul className="space-y-2">
              {steps.map((s, idx) => (
                <li
                  key={s.uid}
                  className={clsx(
                    'flex items-center gap-2 p-2 rounded-md border border-border-light',
                    'bg-surface-secondary/30',
                  )}
                >
                  <div className="flex flex-col items-center gap-0.5">
                    <button
                      type="button"
                      className="text-content-tertiary hover:text-content-primary disabled:opacity-30"
                      onClick={() => moveStep(s.uid, -1)}
                      disabled={idx === 0}
                      aria-label={t('common.move_up', { defaultValue: 'Move up' })}
                    >
                      ▲
                    </button>
                    <span className="text-xs font-mono text-content-tertiary">
                      #{idx + 1}
                    </span>
                    <button
                      type="button"
                      className="text-content-tertiary hover:text-content-primary disabled:opacity-30"
                      onClick={() => moveStep(s.uid, +1)}
                      disabled={idx === steps.length - 1}
                      aria-label={t('common.move_down', {
                        defaultValue: 'Move down',
                      })}
                    >
                      ▼
                    </button>
                  </div>
                  <GripVertical
                    size={14}
                    className="text-content-tertiary shrink-0"
                  />
                  <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-2">
                    <UserSearchInput
                      value={s.approver_id}
                      displayValue={s.approverName}
                      onChange={(id, name) =>
                        updateStep(s.uid, {
                          approver_id: id,
                          approverName: name,
                        })
                      }
                      placeholder={t('files.approvals.pick_approver', {
                        defaultValue: 'Pick approver…',
                      })}
                    />
                    <input
                      type="text"
                      value={s.role_label ?? ''}
                      onChange={(e) =>
                        updateStep(s.uid, { role_label: e.target.value })
                      }
                      placeholder={t('files.approvals.role_label', {
                        defaultValue: 'Role (e.g. Architect)',
                      })}
                      maxLength={64}
                      className="h-9 px-3 rounded-md border border-border bg-surface-primary text-sm"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => removeStep(s.uid)}
                    className="text-content-tertiary hover:text-semantic-error transition-colors shrink-0"
                    aria-label={t('common.remove', { defaultValue: 'Remove' })}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Button
            variant="secondary"
            onClick={addStep}
            icon={<Plus size={14} />}
          >
            {t('files.approvals.add_step', { defaultValue: 'Add step' })}
          </Button>
        </WideModalSection>

        <WideModalSection
          title={t('files.approvals.notes_section', { defaultValue: 'Notes' })}
          columns={1}
        >
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            maxLength={4000}
            className="px-3 py-2 rounded-md border border-border bg-surface-primary text-sm resize-y w-full"
            placeholder={t('files.approvals.notes_placeholder', {
              defaultValue: 'Optional context for approvers.',
            })}
          />
        </WideModalSection>
      </WideModal>

      <StampTemplateEditor
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        projectId={projectId}
        onCreated={(id) => setStampId(id)}
      />
    </>
  );
}
