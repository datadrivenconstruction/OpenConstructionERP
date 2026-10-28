// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SiteLogEditor — structured Workforce Log and Equipment Log editors for a
 * saved field report.
 *
 * These drive the dedicated, richer-than-JSON endpoints
 *   POST/GET/DELETE /v1/fieldreports/reports/{id}/workforce/
 *   POST/GET/DELETE /v1/fieldreports/reports/{id}/equipment/
 * which are the PREFERRED input for the labour-cost rollup (the coarse
 * JSON `workforce` column on the report itself is only the fallback). The
 * full CRUD already exists on the backend with IDOR guards; before this
 * component nothing on the frontend ever called it, so company / overtime /
 * WBS / cost-category and equipment operational/standby/breakdown hours were
 * unreachable. This wires them up for real.
 *
 * Only rendered when editing an already-saved report (we need the report id
 * to attach rows to). Mirrors the per-report pattern of ReportAttachments.
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { HardHat, Loader2, Plus, Trash2, Truck } from 'lucide-react';
import { WideModalSection, WideModalField } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchWorkforceLogs,
  createWorkforceLog,
  deleteWorkforceLog,
  fetchEquipmentLogs,
  createEquipmentLog,
  deleteEquipmentLog,
  type SiteWorkforceLogPayload,
  type SiteEquipmentLogPayload,
} from './api';

const inputCls =
  'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary';

const EQUIPMENT_TYPES = [
  'crane',
  'excavator',
  'loader',
  'pump',
  'dumper',
  'compactor',
  'generator',
  'scaffold',
  'other',
];

/* ── Workforce log editor ──────────────────────────────────────────────── */

function emptyWorkforceDraft(reportId: string): SiteWorkforceLogPayload {
  return {
    field_report_id: reportId,
    worker_type: '',
    company: '',
    headcount: 0,
    hours_worked: '8',
    overtime_hours: '0',
    wbs_id: '',
    cost_category: '',
  };
}

function WorkforceLogEditor({
  reportId,
  disabled,
}: {
  reportId: string;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [draft, setDraft] = useState<SiteWorkforceLogPayload>(() => emptyWorkforceDraft(reportId));
  const [busy, setBusy] = useState(false);

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['fieldreports', 'workforce-log', reportId],
    queryFn: () => fetchWorkforceLogs(reportId),
    enabled: !!reportId,
  });

  const invalidate = useCallback(
    () =>
      qc.invalidateQueries({ queryKey: ['fieldreports', 'workforce-log', reportId] }),
    [qc, reportId],
  );

  const handleAdd = useCallback(async () => {
    if (!draft.worker_type.trim()) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: t('fieldreports.workforce_type_required', {
          defaultValue: 'A worker type / trade is required.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await createWorkforceLog(reportId, draft);
      setDraft(emptyWorkforceDraft(reportId));
      await invalidate();
    } catch (err: unknown) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message:
          err instanceof Error
            ? err.message
            : t('fieldreports.workforce_add_failed', { defaultValue: 'Failed to add workforce entry' }),
      });
    } finally {
      setBusy(false);
    }
  }, [draft, reportId, addToast, t, invalidate]);

  const handleDelete = useCallback(
    async (id: string) => {
      setBusy(true);
      try {
        await deleteWorkforceLog(id);
        await invalidate();
      } catch (err: unknown) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message:
            err instanceof Error
              ? err.message
              : t('fieldreports.delete_failed', { defaultValue: 'Delete failed' }),
        });
      } finally {
        setBusy(false);
      }
    },
    [invalidate, addToast, t],
  );

  return (
    <WideModalSection
      title={t('fieldreports.workforce_log', { defaultValue: 'Workforce Log (detailed)' })}
      description={t('fieldreports.workforce_log_help', {
        defaultValue:
          'Structured per-trade rows with company, overtime, WBS and cost category. These feed the labour-cost rollup more accurately than the simple workforce summary above.',
      })}
      columns={1}
    >
      <WideModalField
        label={t('fieldreports.workforce_log', { defaultValue: 'Workforce Log (detailed)' })}
        className="sm:[&>label]:hidden"
      >
        <div className="w-full space-y-3">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-content-tertiary">
              <Loader2 size={14} className="animate-spin" />
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          ) : rows.length === 0 ? (
            <p className="flex items-center gap-1.5 text-xs text-content-tertiary">
              <HardHat size={12} />
              {t('fieldreports.no_workforce_log', {
                defaultValue: 'No detailed workforce entries yet.',
              })}
            </p>
          ) : (
            <ul className="space-y-1">
              {rows.map((r) => (
                <li
                  key={r.id}
                  className="flex items-center justify-between gap-2 rounded-lg border border-border-light px-3 py-1.5 text-sm"
                >
                  <span className="min-w-0 flex-1 truncate text-content-primary">
                    <span className="font-medium">{r.worker_type}</span>
                    {r.company ? <span className="text-content-tertiary"> · {r.company}</span> : null}
                    <span className="text-content-tertiary">
                      {' '}
                      · {r.headcount} {t('fieldreports.workers', { defaultValue: 'workers' })} ·{' '}
                      {r.hours_worked}h
                      {Number(r.overtime_hours) > 0
                        ? ` (+${r.overtime_hours} ${t('fieldreports.overtime', { defaultValue: 'OT' })})`
                        : ''}
                    </span>
                  </span>
                  {!disabled && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => handleDelete(r.id)}
                      className="rounded p-1 text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error disabled:opacity-50"
                      title={t('common.delete', { defaultValue: 'Delete' })}
                      aria-label={t('common.delete', { defaultValue: 'Delete' })}
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {!disabled && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <input
                type="text"
                value={draft.worker_type}
                onChange={(e) => setDraft((d) => ({ ...d, worker_type: e.target.value }))}
                placeholder={t('fieldreports.worker_type', { defaultValue: 'Worker type / trade' })}
                aria-label={t('fieldreports.worker_type', { defaultValue: 'Worker type / trade' })}
                className={inputCls}
              />
              <input
                type="text"
                value={draft.company ?? ''}
                onChange={(e) => setDraft((d) => ({ ...d, company: e.target.value }))}
                placeholder={t('fieldreports.company', { defaultValue: 'Company' })}
                aria-label={t('fieldreports.company', { defaultValue: 'Company' })}
                className={inputCls}
              />
              <input
                type="number"
                min={0}
                value={draft.headcount || ''}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, headcount: parseInt(e.target.value, 10) || 0 }))
                }
                placeholder={t('fieldreports.headcount', { defaultValue: 'Headcount' })}
                aria-label={t('fieldreports.headcount', { defaultValue: 'Headcount' })}
                className={inputCls}
              />
              <input
                type="number"
                min={0}
                step={0.5}
                value={draft.hours_worked ?? ''}
                onChange={(e) => setDraft((d) => ({ ...d, hours_worked: e.target.value }))}
                placeholder={t('fieldreports.hours', { defaultValue: 'Hours' })}
                aria-label={t('fieldreports.hours_worked', { defaultValue: 'Hours worked' })}
                className={inputCls}
              />
              <input
                type="number"
                min={0}
                step={0.5}
                value={draft.overtime_hours ?? ''}
                onChange={(e) => setDraft((d) => ({ ...d, overtime_hours: e.target.value }))}
                placeholder={t('fieldreports.overtime_hours', { defaultValue: 'Overtime hours' })}
                aria-label={t('fieldreports.overtime_hours', { defaultValue: 'Overtime hours' })}
                className={inputCls}
              />
              <input
                type="text"
                value={draft.wbs_id ?? ''}
                onChange={(e) => setDraft((d) => ({ ...d, wbs_id: e.target.value }))}
                placeholder={t('fieldreports.wbs_id', { defaultValue: 'WBS id' })}
                aria-label={t('fieldreports.wbs_id', { defaultValue: 'WBS id' })}
                className={inputCls}
              />
              <input
                type="text"
                value={draft.cost_category ?? ''}
                onChange={(e) => setDraft((d) => ({ ...d, cost_category: e.target.value }))}
                placeholder={t('fieldreports.cost_category', { defaultValue: 'Cost category' })}
                aria-label={t('fieldreports.cost_category', { defaultValue: 'Cost category' })}
                className={inputCls}
              />
              <button
                type="button"
                disabled={busy}
                onClick={handleAdd}
                className="flex items-center justify-center gap-1.5 rounded-lg border border-border-light px-3 py-2 text-sm text-content-secondary hover:bg-surface-secondary disabled:opacity-50 transition-colors"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                {t('fieldreports.add_workforce', { defaultValue: 'Add entry' })}
              </button>
            </div>
          )}
        </div>
      </WideModalField>
    </WideModalSection>
  );
}

/* ── Equipment log editor ──────────────────────────────────────────────── */

function emptyEquipmentDraft(reportId: string): SiteEquipmentLogPayload {
  return {
    field_report_id: reportId,
    equipment_description: '',
    equipment_type: '',
    hours_operational: '0',
    hours_standby: '0',
    hours_breakdown: '0',
    operator_name: '',
  };
}

function EquipmentLogEditor({
  reportId,
  disabled,
}: {
  reportId: string;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [draft, setDraft] = useState<SiteEquipmentLogPayload>(() => emptyEquipmentDraft(reportId));
  const [busy, setBusy] = useState(false);

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['fieldreports', 'equipment-log', reportId],
    queryFn: () => fetchEquipmentLogs(reportId),
    enabled: !!reportId,
  });

  const invalidate = useCallback(
    () => qc.invalidateQueries({ queryKey: ['fieldreports', 'equipment-log', reportId] }),
    [qc, reportId],
  );

  const handleAdd = useCallback(async () => {
    if (!draft.equipment_description.trim()) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: t('fieldreports.equipment_desc_required', {
          defaultValue: 'An equipment description is required.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await createEquipmentLog(reportId, draft);
      setDraft(emptyEquipmentDraft(reportId));
      await invalidate();
    } catch (err: unknown) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message:
          err instanceof Error
            ? err.message
            : t('fieldreports.equipment_add_failed', { defaultValue: 'Failed to add equipment entry' }),
      });
    } finally {
      setBusy(false);
    }
  }, [draft, reportId, addToast, t, invalidate]);

  const handleDelete = useCallback(
    async (id: string) => {
      setBusy(true);
      try {
        await deleteEquipmentLog(id);
        await invalidate();
      } catch (err: unknown) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message:
            err instanceof Error
              ? err.message
              : t('fieldreports.delete_failed', { defaultValue: 'Delete failed' }),
        });
      } finally {
        setBusy(false);
      }
    },
    [invalidate, addToast, t],
  );

  return (
    <WideModalSection
      title={t('fieldreports.equipment_log', { defaultValue: 'Equipment Log (detailed)' })}
      description={t('fieldreports.equipment_log_help', {
        defaultValue:
          'Per-machine rows with operational, standby and breakdown hours plus operator. Appears in the PDF and Excel exports.',
      })}
      columns={1}
    >
      <WideModalField
        label={t('fieldreports.equipment_log', { defaultValue: 'Equipment Log (detailed)' })}
        className="sm:[&>label]:hidden"
      >
        <div className="w-full space-y-3">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-content-tertiary">
              <Loader2 size={14} className="animate-spin" />
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          ) : rows.length === 0 ? (
            <p className="flex items-center gap-1.5 text-xs text-content-tertiary">
              <Truck size={12} />
              {t('fieldreports.no_equipment_log', {
                defaultValue: 'No detailed equipment entries yet.',
              })}
            </p>
          ) : (
            <ul className="space-y-1">
              {rows.map((r) => (
                <li
                  key={r.id}
                  className="flex items-center justify-between gap-2 rounded-lg border border-border-light px-3 py-1.5 text-sm"
                >
                  <span className="min-w-0 flex-1 truncate text-content-primary">
                    <span className="font-medium">{r.equipment_description}</span>
                    {r.equipment_type ? (
                      <span className="text-content-tertiary"> · {r.equipment_type}</span>
                    ) : null}
                    <span className="text-content-tertiary">
                      {' '}
                      · {r.hours_operational}h {t('fieldreports.operational', { defaultValue: 'op.' })}
                      {Number(r.hours_standby) > 0 ? ` · ${r.hours_standby}h ${t('fieldreports.standby', { defaultValue: 'standby' })}` : ''}
                      {Number(r.hours_breakdown) > 0 ? ` · ${r.hours_breakdown}h ${t('fieldreports.breakdown', { defaultValue: 'breakdown' })}` : ''}
                    </span>
                  </span>
                  {!disabled && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => handleDelete(r.id)}
                      className="rounded p-1 text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error disabled:opacity-50"
                      title={t('common.delete', { defaultValue: 'Delete' })}
                      aria-label={t('common.delete', { defaultValue: 'Delete' })}
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {!disabled && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <input
                type="text"
                value={draft.equipment_description}
                onChange={(e) => setDraft((d) => ({ ...d, equipment_description: e.target.value }))}
                placeholder={t('fieldreports.equipment_description', { defaultValue: 'Equipment / model' })}
                aria-label={t('fieldreports.equipment_description', { defaultValue: 'Equipment / model' })}
                className={`${inputCls} col-span-2 sm:col-span-1`}
              />
              <select
                value={draft.equipment_type ?? ''}
                onChange={(e) => setDraft((d) => ({ ...d, equipment_type: e.target.value }))}
                aria-label={t('fieldreports.equipment_type', { defaultValue: 'Equipment type' })}
                className={inputCls}
              >
                <option value="">
                  {t('fieldreports.equipment_type', { defaultValue: 'Equipment type' })}
                </option>
                {EQUIPMENT_TYPES.map((et) => (
                  <option key={et} value={et}>
                    {t(`fieldreports.equiptype_${et}`, { defaultValue: et })}
                  </option>
                ))}
              </select>
              <input
                type="text"
                value={draft.operator_name ?? ''}
                onChange={(e) => setDraft((d) => ({ ...d, operator_name: e.target.value }))}
                placeholder={t('fieldreports.operator', { defaultValue: 'Operator' })}
                aria-label={t('fieldreports.operator', { defaultValue: 'Operator' })}
                className={inputCls}
              />
              <input
                type="number"
                min={0}
                step={0.5}
                value={draft.hours_operational ?? ''}
                onChange={(e) => setDraft((d) => ({ ...d, hours_operational: e.target.value }))}
                placeholder={t('fieldreports.hours_operational', { defaultValue: 'Operational h' })}
                aria-label={t('fieldreports.hours_operational', { defaultValue: 'Operational hours' })}
                className={inputCls}
              />
              <input
                type="number"
                min={0}
                step={0.5}
                value={draft.hours_standby ?? ''}
                onChange={(e) => setDraft((d) => ({ ...d, hours_standby: e.target.value }))}
                placeholder={t('fieldreports.hours_standby', { defaultValue: 'Standby h' })}
                aria-label={t('fieldreports.hours_standby', { defaultValue: 'Standby hours' })}
                className={inputCls}
              />
              <input
                type="number"
                min={0}
                step={0.5}
                value={draft.hours_breakdown ?? ''}
                onChange={(e) => setDraft((d) => ({ ...d, hours_breakdown: e.target.value }))}
                placeholder={t('fieldreports.hours_breakdown', { defaultValue: 'Breakdown h' })}
                aria-label={t('fieldreports.hours_breakdown', { defaultValue: 'Breakdown hours' })}
                className={inputCls}
              />
              <button
                type="button"
                disabled={busy}
                onClick={handleAdd}
                className="col-span-2 flex items-center justify-center gap-1.5 rounded-lg border border-border-light px-3 py-2 text-sm text-content-secondary hover:bg-surface-secondary disabled:opacity-50 transition-colors sm:col-span-3"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                {t('fieldreports.add_equipment', { defaultValue: 'Add equipment' })}
              </button>
            </div>
          )}
        </div>
      </WideModalField>
    </WideModalSection>
  );
}

/* ── Combined editor ───────────────────────────────────────────────────── */

export function SiteLogEditor({
  reportId,
  disabled = false,
}: {
  reportId: string;
  disabled?: boolean;
}) {
  return (
    <>
      <WorkforceLogEditor reportId={reportId} disabled={disabled} />
      <EquipmentLogEditor reportId={reportId} disabled={disabled} />
    </>
  );
}
