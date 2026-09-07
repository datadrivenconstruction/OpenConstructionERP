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
  createDamageReport,
  updateDamageReport,
  type DamageReport,
  type DamageSeverity,
  type DamageStatus,
  type CreateDamageReportPayload,
  type UpdateDamageReportPayload,
} from '../api';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

interface DamageReportFormModalProps {
  mode: 'create' | 'edit';
  equipmentId: string;
  existing?: DamageReport;
  onClose: () => void;
  onSaved?: () => void;
}

function num(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '';
  return String(v);
}

/**
 * The form state an existing damage report opens with.
 *
 * Exported and pure so the save can rebuild the same baseline the fields were
 * seeded from and send only what the user actually changed. Both sides have to
 * come from one definition: if the baseline were derived any other way, a field
 * nobody touched could still read as changed and get written back.
 */
export function damageReportFormBase(existing?: DamageReport) {
  return {
    occurredAt: existing?.reported_at ?? new Date().toISOString().slice(0, 10),
    severity: (existing?.severity as DamageSeverity) ?? 'minor',
    description: existing?.description ?? '',
    repairCost: num(existing?.repair_cost_estimate),
    currency: existing?.currency ?? '',
    statusValue: (existing?.status as DamageStatus) ?? 'reported',
  };
}

export type DamageReportFormState = ReturnType<typeof damageReportFormBase>;

/**
 * The body of an edit save: only the fields the user actually changed.
 *
 * Writing the whole form back on every save rewrites fields the user never
 * opened with the values they held when this modal was opened, undoing anyone
 * else's edit to them in the meantime without a word. The update route dumps
 * with `exclude_unset=True`, so a field left out of the body is left alone in
 * the database, which is what makes omission the right tool.
 *
 * `occurredAt` is absent because the update payload has no field for it: the
 * occurrence date is fixed once the report is filed.
 */
export function buildDamageReportPatch(
  form: DamageReportFormState,
  base: DamageReportFormState,
): UpdateDamageReportPayload {
  const payload: UpdateDamageReportPayload = {};
  if (form.severity !== base.severity) payload.severity = form.severity;
  if (form.description !== base.description) payload.description = form.description;
  if (form.repairCost !== base.repairCost) {
    // An unparseable figure is left out rather than sent as NaN, which would be
    // serialised as null and wipe a cost the user never meant to clear.
    const parsed = form.repairCost.trim() === '' ? null : parseDecimalInput(form.repairCost);
    if (parsed !== null) payload.repair_cost_estimate = parsed;
  }
  if (form.currency !== base.currency) payload.currency = form.currency.trim() || undefined;
  if (form.statusValue !== base.statusValue) payload.status = form.statusValue;
  return payload;
}

export function DamageReportFormModal({
  mode,
  equipmentId,
  existing,
  onClose,
  onSaved,
}: DamageReportFormModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  // Seeded from the same function the save compares against, so the two can
  // never drift apart. See `damageReportFormBase`.
  const seed = damageReportFormBase(existing);
  const [occurredAt, setOccurredAt] = useState<string>(seed.occurredAt);
  const [severity, setSeverity] = useState<DamageSeverity>(seed.severity);
  const [description, setDescription] = useState<string>(seed.description);
  const [repairCost, setRepairCost] = useState<string>(seed.repairCost);
  const [currency, setCurrency] = useState<string>(seed.currency);
  const [statusValue, setStatusValue] = useState<DamageStatus>(seed.statusValue);
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
    if (!occurredAt) {
      setError(
        t('equipment.damage.date_required', {
          defaultValue: 'Occurrence date is required.',
        }),
      );
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const costNum = repairCost.trim() === '' ? null : parseDecimalInput(repairCost);
      if (isEdit && existing) {
        const payload = buildDamageReportPatch(
          { occurredAt, severity, description, repairCost, currency, statusValue },
          damageReportFormBase(existing),
        );
        await updateDamageReport(existing.id, payload);
        addToast({
          type: 'success',
          title: t('equipment.damage.updated', {
            defaultValue: 'Damage report updated',
          }),
        });
      } else {
        const payload: CreateDamageReportPayload = {
          equipment_id: equipmentId,
          reported_at: occurredAt,
          severity,
          description,
          repair_cost_estimate: costNum ?? undefined,
          currency: currency.trim() || undefined,
        };
        await createDamageReport(payload);
        addToast({
          type: 'success',
          title: t('equipment.damage.created', {
            defaultValue: 'Damage report filed',
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
      aria-labelledby="damage-form-title"
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
      <div
        className="relative w-full max-w-xl max-h-[92vh] overflow-y-auto rounded-xl bg-surface-elevated p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2
            id="damage-form-title"
            className="text-lg font-semibold text-content-primary"
          >
            {isEdit
              ? t('equipment.damage.edit_title', {
                  defaultValue: 'Edit damage report',
                })
              : t('equipment.damage.new_title', {
                  defaultValue: 'Report damage',
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
              {t('equipment.damage.section_event', {
                defaultValue: 'Event',
              })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>
                  {t('equipment.damage.occurred_at', {
                    defaultValue: 'Occurred at',
                  })}{' '}
                  <span className="text-rose-500">*</span>
                </label>
                <input
                  type="date"
                  value={occurredAt}
                  onChange={(e) => setOccurredAt(e.target.value)}
                  className={inputCls}
                  disabled={isEdit}
                  title={
                    isEdit
                      ? t('equipment.damage.date_immutable', {
                          defaultValue:
                            'Occurrence date is fixed once the report is filed.',
                        })
                      : undefined
                  }
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.damage.severity', {
                    defaultValue: 'Severity',
                  })}
                </label>
                <select
                  value={severity}
                  onChange={(e) => setSeverity(e.target.value as DamageSeverity)}
                  className={inputCls}
                >
                  {(['minor', 'major', 'critical'] as DamageSeverity[]).map(
                    (s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ),
                  )}
                </select>
              </div>
              {isEdit && (
                <div>
                  <label className={labelCls}>
                    {t('equipment.damage.status', { defaultValue: 'Status' })}
                  </label>
                  <select
                    value={statusValue}
                    onChange={(e) =>
                      setStatusValue(e.target.value as DamageStatus)
                    }
                    className={inputCls}
                  >
                    {(['reported', 'under_repair', 'repaired'] as DamageStatus[]).map(
                      (s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ),
                    )}
                  </select>
                </div>
              )}
              <div className="sm:col-span-2">
                <label className={labelCls}>
                  {t('equipment.damage.description', {
                    defaultValue: 'Description',
                  })}
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className={clsx(inputCls, 'min-h-[96px] py-2 leading-snug')}
                  placeholder={t('equipment.damage.description_ph', {
                    defaultValue:
                      'Describe what happened, witnesses, immediate actions taken…',
                  })}
                  rows={4}
                  maxLength={10000}
                />
              </div>
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('equipment.damage.section_cost', {
                defaultValue: 'Estimated cost',
              })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>
                  {t('equipment.damage.repair_cost_estimate', {
                    defaultValue: 'Repair cost estimate',
                  })}
                </label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={repairCost}
                  onChange={(e) => setRepairCost(e.target.value)}
                  className={inputCls}
                  placeholder="0"
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.damage.currency', {
                    defaultValue: 'Currency',
                  })}
                </label>
                <input
                  value={currency}
                  onChange={(e) =>
                    setCurrency(e.target.value.toUpperCase().slice(0, 3))
                  }
                  className={inputCls}
                  placeholder="EUR"
                  maxLength={3}
                />
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
