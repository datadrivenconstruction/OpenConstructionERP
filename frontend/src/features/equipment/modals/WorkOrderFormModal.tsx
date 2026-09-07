// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Plus, Save, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { parseDecimalInput } from '@/shared/lib/parseDecimal';
import {
  createWorkOrder,
  updateWorkOrder,
  type MaintenanceWorkOrder,
  type WorkOrderStatus,
  type CreateWorkOrderPayload,
  type UpdateWorkOrderPayload,
} from '../api';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

interface WorkOrderFormModalProps {
  mode: 'create' | 'edit';
  equipmentId: string;
  existing?: MaintenanceWorkOrder;
  onClose: () => void;
  onSaved?: () => void;
}

function num(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '';
  return String(v);
}

/**
 * The form state an existing work order opens with.
 *
 * Exported and pure so the save can rebuild the same baseline the fields were
 * seeded from and send only what the user actually changed. Both sides have to
 * come from one definition: if the baseline were derived any other way, a field
 * nobody touched could still read as changed and get written back.
 */
export function workOrderFormBase(existing?: MaintenanceWorkOrder) {
  return {
    scheduledFor: existing?.scheduled_for ?? '',
    status: (existing?.status ?? 'scheduled') as WorkOrderStatus,
    technicianId: existing?.technician_id ?? '',
    workSummary: existing?.work_summary ?? '',
    cost: num(existing?.cost),
    currency: existing?.currency ?? '',
  };
}

export type WorkOrderFormState = ReturnType<typeof workOrderFormBase>;

/**
 * The body of an edit save: only the fields the user actually changed.
 *
 * Writing the whole form back on every save rewrites fields the user never
 * opened with the values they held when this modal was opened, undoing anyone
 * else's edit to them in the meantime without a word. The update route dumps
 * with `exclude_unset=True`, so a field left out of the body is left alone in
 * the database, which is what makes omission the right tool.
 *
 * Clearing a text field sends `null` rather than `undefined`: `JSON.stringify`
 * drops an `undefined` key, so the old value would simply survive and the user
 * would watch their deletion have no effect.
 */
export function buildWorkOrderPatch(
  form: WorkOrderFormState,
  base: WorkOrderFormState,
): UpdateWorkOrderPayload {
  const payload: UpdateWorkOrderPayload = {};
  if (form.scheduledFor !== base.scheduledFor) payload.scheduled_for = form.scheduledFor || null;
  if (form.status !== base.status) payload.status = form.status;
  if (form.technicianId !== base.technicianId) {
    payload.technician_id = form.technicianId.trim() || null;
  }
  if (form.workSummary !== base.workSummary) payload.work_summary = form.workSummary.trim() || null;
  if (form.cost !== base.cost) {
    // An unparseable cost is left out rather than sent as NaN, which would be
    // serialised as null and wipe a figure the user never meant to clear.
    const parsed = form.cost.trim() === '' ? null : parseDecimalInput(form.cost);
    if (parsed !== null) payload.cost = parsed;
  }
  if (form.currency !== base.currency) payload.currency = form.currency.trim() || undefined;
  return payload;
}

export function WorkOrderFormModal({
  mode,
  equipmentId,
  existing,
  onClose,
  onSaved,
}: WorkOrderFormModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  // Seeded from the same function the save compares against, so the two can
  // never drift apart. See `workOrderFormBase`.
  const seed = workOrderFormBase(existing);
  const [scheduleId, setScheduleId] = useState<string>(existing?.schedule_id ?? '');
  const [scheduledFor, setScheduledFor] = useState<string>(seed.scheduledFor);
  const [status, setStatus] = useState<WorkOrderStatus>(seed.status);
  const [technicianId, setTechnicianId] = useState<string>(seed.technicianId);
  const [workSummary, setWorkSummary] = useState<string>(seed.workSummary);
  const [cost, setCost] = useState<string>(seed.cost);
  const [currency, setCurrency] = useState<string>(seed.currency);
  const [error, setError] = useState<string | null>(null);

  const isEdit = mode === 'edit';

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', h, { capture: true });
    return () =>
      document.removeEventListener('keydown', h, { capture: true });
  }, [busy, onClose]);

  const submit = async () => {
    if (!workSummary.trim() && !scheduledFor) {
      setError(
        t('equipment.workorder.required', {
          defaultValue: 'Provide either a scheduled date or a description.',
        }),
      );
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const costNum = cost.trim() === '' ? null : parseDecimalInput(cost);
      if (isEdit && existing) {
        const payload = buildWorkOrderPatch(
          { scheduledFor, status, technicianId, workSummary, cost, currency },
          workOrderFormBase(existing),
        );
        await updateWorkOrder(existing.id, payload);
        addToast({
          type: 'success',
          title: t('equipment.workorder.updated', {
            defaultValue: 'Work order updated',
          }),
        });
      } else {
        const payload: CreateWorkOrderPayload = {
          equipment_id: equipmentId,
          schedule_id: scheduleId || null,
          scheduled_for: scheduledFor || null,
          status,
          technician_id: technicianId.trim() || null,
          work_summary: workSummary.trim() || null,
          cost: costNum ?? undefined,
          currency: currency.trim() || undefined,
        };
        await createWorkOrder(payload);
        addToast({
          type: 'success',
          title: t('equipment.workorder.created', {
            defaultValue: 'Work order created',
          }),
        });
      }
      onSaved?.();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-3"
      onClick={() => !busy && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="workorder-form-title"
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
      <div
        className="relative w-full max-w-xl max-h-[92vh] overflow-y-auto rounded-xl bg-surface-elevated p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2
            id="workorder-form-title"
            className="text-lg font-semibold text-content-primary"
          >
            {isEdit
              ? t('equipment.workorder.edit_title', {
                  defaultValue: 'Edit work order',
                })
              : t('equipment.workorder.new_title', {
                  defaultValue: 'New work order',
                })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded p-1 hover:bg-surface-secondary disabled:opacity-50"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4">
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('equipment.workorder.section_schedule', {
                defaultValue: 'Schedule',
              })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {!isEdit && (
                <div className="sm:col-span-2">
                  <label className={labelCls}>
                    {t('equipment.workorder.schedule_id', {
                      defaultValue: 'Linked maintenance schedule (optional)',
                    })}
                  </label>
                  <input
                    value={scheduleId}
                    onChange={(e) => setScheduleId(e.target.value)}
                    className={inputCls}
                    placeholder={t('equipment.workorder.schedule_id_ph', {
                      defaultValue: 'UUID of the parent schedule, or leave blank',
                    })}
                  />
                </div>
              )}
              <div>
                <label className={labelCls}>
                  {t('equipment.workorder.due_date', {
                    defaultValue: 'Scheduled date',
                  })}
                </label>
                <input
                  type="date"
                  value={scheduledFor}
                  onChange={(e) => setScheduledFor(e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.workorder.status', {
                    defaultValue: 'Status',
                  })}
                </label>
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value as WorkOrderStatus)}
                  className={inputCls}
                >
                  {(
                    ['scheduled', 'in_progress', 'completed', 'cancelled'] as WorkOrderStatus[]
                  ).map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('equipment.workorder.section_work', {
                defaultValue: 'Work',
              })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="sm:col-span-2">
                <label className={labelCls}>
                  {t('equipment.workorder.title', {
                    defaultValue: 'Title / description',
                  })}
                </label>
                <textarea
                  value={workSummary}
                  onChange={(e) => setWorkSummary(e.target.value)}
                  className={clsx(inputCls, 'min-h-[72px] py-2 leading-snug')}
                  placeholder={t('equipment.workorder.title_ph', {
                    defaultValue: 'Replace hydraulic filter; top up engine oil',
                  })}
                  rows={3}
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.workorder.assigned_to', {
                    defaultValue: 'Assigned to (technician)',
                  })}
                </label>
                <input
                  value={technicianId}
                  onChange={(e) => setTechnicianId(e.target.value)}
                  className={inputCls}
                  placeholder={t('equipment.workorder.assigned_to_ph', {
                    defaultValue: 'Technician id or name',
                  })}
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.workorder.cost', {
                    defaultValue: 'Estimated cost',
                  })}
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    inputMode="decimal"
                    value={cost}
                    onChange={(e) => setCost(e.target.value)}
                    className={inputCls}
                    placeholder="0"
                  />
                  <input
                    value={currency}
                    onChange={(e) =>
                      setCurrency(e.target.value.toUpperCase().slice(0, 3))
                    }
                    className={clsx(inputCls, 'w-20')}
                    placeholder="EUR"
                    maxLength={3}
                  />
                </div>
              </div>
            </div>
          </section>

          {error && (
            <p className="text-xs text-status-error" role="alert">
              {error}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 mt-5 sticky bottom-0 pt-3 -mx-5 -mb-5 px-5 pb-3 bg-surface-elevated border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={
              busy ? <Loader2 size={14} /> : isEdit ? <Save size={14} /> : <Plus size={14} />
            }
          >
            {isEdit
              ? t('common.save', { defaultValue: 'Save changes' })
              : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
