// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Create an RFI (Request for Information) straight from a takeoff
 * measurement. Prefills a subject and question from the measurement's
 * group / type / value / page, lets the user tweak them and pick a
 * priority, then:
 *
 *   1. creates the RFI (attaching the source drawing when known), and
 *   2. records a cross-module link back to the measurement via the
 *      generic file-reference primitive (file_kind 'takeoff' ->
 *      target_type 'rfi', relation 'spawned-from').
 *
 * No backend change: both calls hit existing endpoints. The measurement
 * must already be synced (it needs a durable ``serverId`` to be the
 * "file" side of the reference) - the host gates on that before opening.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Button } from '@/shared/ui/Button';
import { openLink } from '@/shared/lib/desktop';
import { useToastStore } from '@/stores/useToastStore';
import { createRFI, type RFI, type RFIPriority } from '@/features/rfi/api';
import { useCreateReference } from '@/features/file-references/hooks';
import type { Measurement } from '../lib/takeoff-types';

export interface CreateRfiFromMeasurementDialogProps {
  measurement: Measurement;
  /** Project the takeoff document (and so the new RFI) belongs to. */
  projectId: string;
  /** Stable document UUID, attached to the RFI as a linked drawing when set. */
  documentId: string | null;
  /** Human file name of the drawing, woven into the prefilled question. */
  documentName: string | null;
  onClose: () => void;
  onCreated?: (rfi: RFI) => void;
}

/** Priorities offered here (the RFI model also has 'critical', kept out of
 *  this quick-create flow to keep the choice simple). */
const PRIORITIES: readonly RFIPriority[] = ['low', 'normal', 'high'];

/** Compact quantity formatter mirroring the ledger so the prefilled text
 *  reads naturally (metric, as stored). */
function formatQty(value: number): string {
  if (!Number.isFinite(value) || value === 0) return '0';
  const abs = Math.abs(value);
  if (abs < 1) return value.toFixed(3);
  if (abs < 100) return value.toFixed(2);
  return value.toFixed(1);
}

const INPUT_CLASS =
  'rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

export function CreateRfiFromMeasurementDialog({
  measurement,
  projectId,
  documentId,
  documentName,
  onClose,
  onCreated,
}: CreateRfiFromMeasurementDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  // Durable server id - the "file" side of the reference. The host only
  // opens this dialog once the measurement is synced, so this is set; the
  // fallback keeps types honest and disables submit if it is ever missing.
  const serverId = measurement.serverId ?? '';

  const group = measurement.group || t('takeoff_crosslink.default_group', { defaultValue: 'General' });
  const annotation =
    measurement.annotation ||
    t('takeoff_crosslink.no_annotation', { defaultValue: 'no label' });
  const doc =
    documentName || t('takeoff_crosslink.this_drawing', { defaultValue: 'this drawing' });

  const [subject, setSubject] = useState(() =>
    t('takeoff_crosslink.rfi_subject_default', {
      defaultValue: '{{group}} {{type}} on page {{page}}',
      group,
      type: measurement.type,
      page: measurement.page,
    }),
  );
  const [question, setQuestion] = useState(() =>
    t('takeoff_crosslink.rfi_question_default', {
      defaultValue:
        'Please confirm the measured {{type}} of {{value}} {{unit}} ({{annotation}}) on page {{page}} of {{doc}}.',
      type: measurement.type,
      value: formatQty(measurement.value),
      unit: measurement.unit || '',
      annotation,
      page: measurement.page,
      doc,
    }),
  );
  const [priority, setPriority] = useState<RFIPriority>('normal');

  const createRefMut = useCreateReference({
    projectId,
    kind: 'takeoff',
    fileId: serverId,
  });

  const submitMut = useMutation<RFI, Error, void>({
    mutationFn: async () => {
      const rfi = await createRFI({
        project_id: projectId,
        subject: subject.trim(),
        question: question.trim(),
        linked_drawing_ids: documentId ? [documentId] : [],
        priority,
      });
      // Record the cross-module link (idempotent server-side). Runs through
      // the hook so the "referenced in" query for this measurement refreshes.
      await createRefMut.mutateAsync({
        project_id: projectId,
        file_kind: 'takeoff',
        file_id: serverId,
        target_type: 'rfi',
        target_id: rfi.id,
        relation: 'spawned-from',
        target_label: rfi.rfi_number,
      });
      return rfi;
    },
    onSuccess: (rfi) => {
      addToast({
        type: 'success',
        title: t('takeoff_crosslink.rfi_created_title', {
          defaultValue: 'RFI {{number}} created',
          number: rfi.rfi_number,
        }),
        message: t('takeoff_crosslink.rfi_created_msg', {
          defaultValue: 'Linked to this measurement.',
        }),
        action: {
          label: t('takeoff_crosslink.rfi_view', { defaultValue: 'View RFI' }),
          onClick: () => openLink(`/rfi/${rfi.id}`),
        },
      });
      onCreated?.(rfi);
      onClose();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('takeoff_crosslink.rfi_failed', {
          defaultValue: 'Could not create RFI',
        }),
        message: err instanceof Error ? err.message : undefined,
      });
    },
  });

  // Dismiss on Escape, like the app's other lightweight dialogs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const canSubmit =
    Boolean(subject.trim()) &&
    Boolean(question.trim()) &&
    Boolean(projectId) &&
    Boolean(serverId) &&
    !submitMut.isPending;

  const handleSubmit = useCallback(() => {
    if (!canSubmit) return;
    submitMut.mutate();
  }, [canSubmit, submitMut]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="takeoff-rfi-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="takeoff-rfi-dialog"
    >
      <div className="w-full max-w-md rounded-xl bg-surface-primary p-5 shadow-xl">
        <h2
          id="takeoff-rfi-modal-title"
          className="text-start text-base font-semibold text-content-primary"
        >
          {t('takeoff_crosslink.rfi_dialog_title', {
            defaultValue: 'Create RFI from measurement',
          })}
        </h2>
        <p className="mt-0.5 text-start text-xs text-content-tertiary">
          {t('takeoff_crosslink.rfi_dialog_desc', {
            defaultValue:
              'Raise a request for information tied to this measurement. The drawing is attached and the new RFI links back to the measurement.',
          })}
        </p>

        <div className="mt-4 space-y-3">
          <label className="flex flex-col gap-1">
            <span className="text-start text-xs font-medium text-content-secondary">
              {t('takeoff_crosslink.rfi_subject_label', { defaultValue: 'Subject' })}
            </span>
            <input
              type="text"
              value={subject}
              autoFocus
              onChange={(e) => setSubject(e.target.value)}
              className={INPUT_CLASS}
              data-testid="takeoff-rfi-subject"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-start text-xs font-medium text-content-secondary">
              {t('takeoff_crosslink.rfi_question_label', { defaultValue: 'Question' })}
            </span>
            <textarea
              value={question}
              rows={4}
              onChange={(e) => setQuestion(e.target.value)}
              className={`${INPUT_CLASS} resize-none`}
              data-testid="takeoff-rfi-question"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-start text-xs font-medium text-content-secondary">
              {t('takeoff_crosslink.rfi_priority_label', { defaultValue: 'Priority' })}
            </span>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as RFIPriority)}
              className={INPUT_CLASS}
              data-testid="takeoff-rfi-priority"
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {t(`takeoff_crosslink.priority_${p}`, {
                    defaultValue: p.charAt(0).toUpperCase() + p.slice(1),
                  })}
                </option>
              ))}
            </select>
          </label>

          {!projectId && (
            <p
              className="text-start text-xs text-semantic-error"
              data-testid="takeoff-rfi-no-project"
            >
              {t('takeoff_crosslink.rfi_no_project', {
                defaultValue: 'Open this drawing inside a project to raise an RFI.',
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
            data-testid="takeoff-rfi-submit"
          >
            {t('takeoff_crosslink.rfi_submit', { defaultValue: 'Create RFI' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default CreateRfiFromMeasurementDialog;
