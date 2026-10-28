// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BcfIssueModal - the "Raise issue here" dialog.
 *
 * Opens over a 3D/BIM view, snapshots the current camera + selection + a PNG
 * of the canvas (once, on open, so the preview and the saved viewpoint match),
 * collects the issue fields, then creates a topic and attaches the viewpoint
 * via {@link useBcfCapture}. The viewer is reached only through the injected
 * {@link BcfViewerBridge}, so this modal never imports the viewer itself.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Box, Camera, ImageOff, Plus } from 'lucide-react';
import clsx from 'clsx';

import {
  Button,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import {
  useBcfCapture,
  type BcfViewerBridge,
  type CapturedContext,
  type RaiseIssueInput,
  type RaiseIssueResult,
} from './useBcfCapture';

/** An assignable user for the assignee dropdown. */
export interface BcfMember {
  id: string;
  name: string;
}

export interface BcfIssueModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Bridge to the live viewer. Memoize it so the preview captures once. */
  bridge: BcfViewerBridge;
  /** Stamped onto the topic so the issue is scoped to a specific model. */
  bimModelId?: string | null;
  /** When provided, the assignee field is a dropdown; otherwise free text. */
  assignees?: BcfMember[];
  /** Fired after a topic (and its viewpoint) are created. */
  onCreated?: (result: RaiseIssueResult) => void;
}

/** BCF `priority` is free-form; these are the common values we offer. */
const PRIORITY_OPTIONS = ['', 'Low', 'Normal', 'High', 'Critical'] as const;

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

interface FormState {
  title: string;
  description: string;
  priority: string;
  assignedTo: string;
  dueDate: string;
  labels: string;
}

const EMPTY_FORM: FormState = {
  title: '',
  description: '',
  priority: '',
  assignedTo: '',
  dueDate: '',
  labels: '',
};

/** Split the comma-separated label input into a clean, de-duplicated list. */
function parseLabels(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(',')) {
    const label = part.trim();
    if (label && !seen.has(label)) {
      seen.add(label);
      out.push(label);
    }
  }
  return out;
}

export function BcfIssueModal({
  open,
  onClose,
  projectId,
  bridge,
  bimModelId,
  assignees,
  onCreated,
}: BcfIssueModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const { raiseIssue, capture } = useBcfCapture(projectId, bridge);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);
  const [captured, setCaptured] = useState<CapturedContext | null>(null);

  // Capture the viewer once per open so the preview and the persisted
  // viewpoint are the same frame. A ref keeps the latest `capture` without
  // re-running the effect when the bridge identity changes each render.
  const captureRef = useRef(capture);
  captureRef.current = capture;
  useEffect(() => {
    if (!open) return;
    setForm(EMPTY_FORM);
    setTouched(false);
    setCaptured(captureRef.current());
  }, [open]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const createMut = useMutation({
    mutationFn: (input: RaiseIssueInput) => raiseIssue(input, captured ?? undefined),
    onSuccess: (result) => {
      if (result.viewpointFailed) {
        addToast({
          type: 'warning',
          title: t('bcf.issue_created_no_view', {
            defaultValue: 'Issue created, but the view could not be saved',
          }),
        });
      } else {
        addToast({
          type: 'success',
          title: t('bcf.issue_created', { defaultValue: 'Issue raised' }),
        });
      }
      onCreated?.(result);
      onClose();
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err.message,
      }),
  });

  const titleError = touched && form.title.trim().length === 0;
  const canSubmit = form.title.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    createMut.mutate({
      title: form.title,
      description: form.description,
      priority: form.priority,
      assignedTo: form.assignedTo,
      dueDate: form.dueDate,
      labels: parseLabels(form.labels),
      bimModelId: bimModelId ?? null,
      topicStatus: 'Open',
    });
  };

  const handleRecapture = () => setCaptured(capture());

  const selectionCount = captured?.guids.length ?? 0;
  const hasCamera = Boolean(captured?.camera);
  const snapshotUrl = captured?.snapshotB64
    ? `data:image/png;base64,${captured.snapshotB64}`
    : null;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={createMut.isPending}
      size="xl"
      title={t('bcf.raise_issue', { defaultValue: 'Raise issue here' })}
      subtitle={t('bcf.raise_issue_subtitle', {
        defaultValue: 'Capture the current view, selection and camera as a BCF issue.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={createMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={createMut.isPending || !canSubmit}
            icon={<Plus size={16} />}
          >
            {t('bcf.create_issue', { defaultValue: 'Create issue' })}
          </Button>
        </>
      }
    >
      {/* ── Captured view preview ─────────────────────────────────────── */}
      <div className="mb-5 flex flex-col gap-3 rounded-xl border border-border-light bg-surface-secondary/40 p-3 sm:flex-row">
        <div className="flex h-40 w-full shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border-light bg-surface-primary sm:w-64">
          {snapshotUrl ? (
            <img
              src={snapshotUrl}
              alt={t('bcf.snapshot_alt', { defaultValue: 'Captured view snapshot' })}
              className="h-full w-full object-contain"
            />
          ) : (
            <div className="flex flex-col items-center gap-1.5 text-content-quaternary">
              <ImageOff size={22} />
              <span className="px-4 text-center text-2xs">
                {t('bcf.no_snapshot', {
                  defaultValue: 'No snapshot captured from this view.',
                })}
              </span>
            </div>
          )}
        </div>
        <div className="flex min-w-0 flex-1 flex-col justify-between gap-2">
          <div className="space-y-1.5 text-xs text-content-secondary">
            <div className="flex items-center gap-1.5">
              <Box size={13} className="shrink-0 text-content-tertiary" />
              <span>
                {t('bcf.selection_count', {
                  defaultValue: '{{count}} element(s) selected',
                  count: selectionCount,
                })}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <Camera size={13} className="shrink-0 text-content-tertiary" />
              <span>
                {hasCamera
                  ? t('bcf.camera_captured', { defaultValue: 'Camera position captured' })
                  : t('bcf.camera_missing', { defaultValue: 'No camera captured' })}
              </span>
            </div>
          </div>
          <div>
            <Button variant="secondary" size="sm" icon={<Camera size={14} />} onClick={handleRecapture}>
              {t('bcf.recapture', { defaultValue: 'Recapture view' })}
            </Button>
          </div>
        </div>
      </div>

      {/* ── Issue fields ──────────────────────────────────────────────── */}
      <WideModalSection columns={2}>
        <WideModalField
          label={t('bcf.field_title', { defaultValue: 'Title' })}
          required
          error={
            titleError
              ? t('bcf.title_required', { defaultValue: 'Title is required' })
              : undefined
          }
          span={2}
          htmlFor="bcf-title"
        >
          <input
            id="bcf-title"
            value={form.title}
            onChange={(e) => {
              set('title', e.target.value);
              setTouched(true);
            }}
            placeholder={t('bcf.title_placeholder', {
              defaultValue: 'e.g. Duct clashes with beam at grid C-4',
            })}
            className={clsx(
              inputCls,
              titleError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
            )}
            autoFocus
          />
        </WideModalField>

        <WideModalField
          label={t('bcf.field_description', { defaultValue: 'Description' })}
          span={2}
          htmlFor="bcf-description"
        >
          <textarea
            id="bcf-description"
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('bcf.description_placeholder', {
              defaultValue: 'Describe what is wrong and what needs to happen.',
            })}
          />
        </WideModalField>

        <WideModalField
          label={t('bcf.field_priority', { defaultValue: 'Priority' })}
          htmlFor="bcf-priority"
        >
          <select
            id="bcf-priority"
            value={form.priority}
            onChange={(e) => set('priority', e.target.value)}
            className={inputCls}
          >
            {PRIORITY_OPTIONS.map((p) => (
              <option key={p || 'none'} value={p}>
                {p
                  ? t(`bcf.priority_${p.toLowerCase()}`, { defaultValue: p })
                  : t('bcf.priority_none', { defaultValue: 'No priority' })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('bcf.field_assigned_to', { defaultValue: 'Assigned to' })}
          htmlFor="bcf-assignee"
        >
          {assignees && assignees.length > 0 ? (
            <select
              id="bcf-assignee"
              value={form.assignedTo}
              onChange={(e) => set('assignedTo', e.target.value)}
              className={inputCls}
            >
              <option value="">{t('bcf.unassigned', { defaultValue: 'Unassigned' })}</option>
              {assignees.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          ) : (
            <input
              id="bcf-assignee"
              value={form.assignedTo}
              onChange={(e) => set('assignedTo', e.target.value)}
              placeholder={t('bcf.assignee_placeholder', { defaultValue: 'Name or email' })}
              className={inputCls}
            />
          )}
        </WideModalField>

        <WideModalField
          label={t('bcf.field_due_date', { defaultValue: 'Due date' })}
          htmlFor="bcf-due"
        >
          <input
            id="bcf-due"
            type="date"
            value={form.dueDate}
            onChange={(e) => set('dueDate', e.target.value)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('bcf.field_labels', { defaultValue: 'Labels' })}
          hint={t('bcf.labels_hint', { defaultValue: 'Comma-separated, e.g. MEP, clash' })}
          htmlFor="bcf-labels"
        >
          <input
            id="bcf-labels"
            value={form.labels}
            onChange={(e) => set('labels', e.target.value)}
            placeholder={t('bcf.labels_placeholder', { defaultValue: 'MEP, clash, level-3' })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
