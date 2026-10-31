// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Typed bar bending schedule: pick a standard shape code (BS 8666 or IS 2502), enter only the
 * dimensions that shape needs, and get cut length and weight per bar mark plus totals by diameter.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Download, Trash2 } from 'lucide-react';
import { Badge, Button, Card, EmptyState } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  BBS_DIAMETERS,
  createBbsEntry,
  deleteBbsEntry,
  downloadBbsCsv,
  fetchBbs,
  fetchBbsValidation,
  fetchShapeCodes,
  type BbsInput,
  type DimKey,
  type ShapeStandard,
} from './bbsApi';

const inputCls =
  'w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

export function BarBendingSchedulePanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [f, setF] = useState({
    member: '',
    bar_mark: '',
    standard: 'BS8666' as ShapeStandard,
    shape_code: '',
    diameter_mm: 12,
    members_count: '1',
    bars_per_member: '1',
    dims: {} as Partial<Record<DimKey, string>>,
  });

  const codesQ = useQuery({ queryKey: ['rebar-bbs', 'shape-codes'], queryFn: fetchShapeCodes, staleTime: Infinity });
  const bbsQ = useQuery({ queryKey: ['rebar-bbs', 'list', projectId], queryFn: () => fetchBbs(projectId) });
  const valQ = useQuery({ queryKey: ['rebar-bbs', 'validation', projectId], queryFn: () => fetchBbsValidation(projectId) });

  const codes = useMemo(() => (codesQ.data ?? []).filter((c) => c.standard === f.standard), [codesQ.data, f.standard]);
  const shape = codes.find((c) => c.code === f.shape_code) ?? null;
  const needed = shape ? shape.dimensions.map((d) => `dim_${d.toLowerCase()}` as DimKey) : [];

  const refresh = () => qc.invalidateQueries({ queryKey: ['rebar-bbs'] });
  const onError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('rebar_schedule.bbs_save_failed', { defaultValue: 'Could not save' }),
      message: getErrorMessage(e),
    });
  const add = useMutation({
    mutationFn: () => {
      const body: BbsInput = {
        project_id: projectId,
        member: f.member.trim(),
        bar_mark: f.bar_mark.trim(),
        diameter_mm: f.diameter_mm,
        shape_standard: f.standard,
        shape_code: f.shape_code,
        members_count: Math.max(1, Number(f.members_count) || 1),
        bars_per_member: Math.max(1, Number(f.bars_per_member) || 1),
      };
      needed.forEach((k) => {
        const v = f.dims[k]?.trim();
        if (v) body[k] = v;
      });
      return createBbsEntry(body);
    },
    onSuccess: () => {
      setF({ ...f, bar_mark: '', dims: {} });
      refresh();
    },
    onError,
  });
  const del = useMutation({ mutationFn: (id: string) => deleteBbsEntry(id), onSuccess: refresh, onError });

  const ready =
    f.member.trim() && f.bar_mark.trim() && shape && needed.every((k) => (f.dims[k] ?? '').trim() !== '');
  const items = bbsQ.data?.items ?? [];
  const failed = (valQ.data?.results ?? []).filter((r) => !r.passed);

  return (
    <div className="space-y-4" data-testid="bbs-panel">
      <p className="text-xs text-content-tertiary">
        {t('rebar_schedule.bbs_explainer', {
          defaultValue:
            'Type the bars of a member by standard shape code. Cut length, weight and totals per diameter are worked out for you.',
        })}
      </p>

      <Card padding="sm">
        <div className="grid gap-3 sm:grid-cols-4 lg:grid-cols-8">
          <label className="flex flex-col gap-1 text-xs text-content-secondary sm:col-span-2">
            <span>{t('rebar_schedule.bbs_member', { defaultValue: 'Member' })}</span>
            <input className={inputCls} value={f.member} onChange={(e) => setF({ ...f, member: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-content-secondary">
            <span>{t('rebar_schedule.bbs_bar_mark', { defaultValue: 'Bar mark' })}</span>
            <input className={inputCls} dir="ltr" value={f.bar_mark} onChange={(e) => setF({ ...f, bar_mark: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-content-secondary">
            <span>{t('rebar_schedule.bbs_standard', { defaultValue: 'Standard' })}</span>
            <select
              className={inputCls}
              value={f.standard}
              onChange={(e) => setF({ ...f, standard: e.target.value as ShapeStandard, shape_code: '', dims: {} })}
            >
              <option value="BS8666">BS 8666</option>
              <option value="IS2502">IS 2502</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-content-secondary">
            <span>{t('rebar_schedule.bbs_shape', { defaultValue: 'Shape code' })}</span>
            <select className={inputCls} dir="ltr" value={f.shape_code} onChange={(e) => setF({ ...f, shape_code: e.target.value, dims: {} })}>
              <option value="" />
              {codes.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code} {c.description}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-content-secondary">
            <span>{t('rebar_schedule.bbs_diameter', { defaultValue: 'Dia (mm)' })}</span>
            <select className={inputCls} dir="ltr" value={f.diameter_mm} onChange={(e) => setF({ ...f, diameter_mm: Number(e.target.value) })}>
              {BBS_DIAMETERS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-content-secondary">
            <span>{t('rebar_schedule.bbs_members_count', { defaultValue: 'Members' })}</span>
            <input type="number" min={1} dir="ltr" className={inputCls} value={f.members_count} onChange={(e) => setF({ ...f, members_count: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-content-secondary">
            <span>{t('rebar_schedule.bbs_bars_per_member', { defaultValue: 'Bars each' })}</span>
            <input type="number" min={1} dir="ltr" className={inputCls} value={f.bars_per_member} onChange={(e) => setF({ ...f, bars_per_member: e.target.value })} />
          </label>
        </div>
        {shape && (
          <div className="mt-3 flex flex-wrap items-end gap-3">
            {needed.map((k) => (
              <label key={k} className="flex w-24 flex-col gap-1 text-xs text-content-secondary">
                <span dir="ltr">{k.slice(4).toUpperCase()} (mm)</span>
                <input
                  type="number"
                  step="any"
                  dir="ltr"
                  className={inputCls}
                  value={f.dims[k] ?? ''}
                  onChange={(e) => setF({ ...f, dims: { ...f.dims, [k]: e.target.value } })}
                />
              </label>
            ))}
            <p className="text-2xs text-content-tertiary" dir="ltr">
              {t('rebar_schedule.bbs_formula', { defaultValue: 'Cut length' })}: {shape.formula}
            </p>
          </div>
        )}
        <div className="mt-3 flex justify-end">
          <Button variant="primary" size="sm" disabled={!ready || add.isPending} onClick={() => add.mutate()}>
            {t('rebar_schedule.bbs_add', { defaultValue: 'Add bar' })}
          </Button>
        </div>
      </Card>

      {failed.length > 0 && (
        <Card padding="sm" data-testid="bbs-findings">
          <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-content-primary">
            <AlertTriangle size={14} className="text-semantic-warning" />
            {t('rebar_schedule.bbs_findings', { defaultValue: 'Findings' })}
          </h3>
          <ul className="space-y-1 text-xs">
            {failed.map((r, i) => (
              <li key={`${r.rule_id}-${r.element_ref ?? ''}-${i}`} className="flex items-start gap-2">
                <Badge variant={r.severity === 'error' ? 'error' : 'warning'} size="sm">
                  {r.severity}
                </Badge>
                <span className="text-content-secondary">{r.message}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {items.length === 0 ? (
        <EmptyState
          title={t('rebar_schedule.bbs_empty', { defaultValue: 'No bars yet' })}
          description={t('rebar_schedule.bbs_empty_desc', { defaultValue: 'Add the first bar above.' })}
        />
      ) : (
        <>
          <div className="flex justify-end">
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={14} />}
              onClick={() => void downloadBbsCsv(projectId).catch((e) => onError(e))}
            >
              {t('rebar_schedule.bbs_csv', { defaultValue: 'Download CSV' })}
            </Button>
          </div>
          <Card padding="none">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light text-2xs uppercase text-content-tertiary">
                    <th className="px-3 py-2 text-start">{t('rebar_schedule.bbs_member', { defaultValue: 'Member' })}</th>
                    <th className="px-3 py-2 text-start">{t('rebar_schedule.bbs_bar_mark', { defaultValue: 'Bar mark' })}</th>
                    <th className="px-3 py-2 text-start">{t('rebar_schedule.bbs_shape', { defaultValue: 'Shape code' })}</th>
                    <th className="px-3 py-2 text-end">{t('rebar_schedule.bbs_diameter', { defaultValue: 'Dia (mm)' })}</th>
                    <th className="px-3 py-2 text-end">{t('rebar_schedule.bbs_count', { defaultValue: 'Bars' })}</th>
                    <th className="px-3 py-2 text-end">{t('rebar_schedule.bbs_cut_length', { defaultValue: 'Cut length (mm)' })}</th>
                    <th className="px-3 py-2 text-end">{t('rebar_schedule.bbs_total_length', { defaultValue: 'Total length (m)' })}</th>
                    <th className="px-3 py-2 text-end">{t('rebar_schedule.bbs_weight', { defaultValue: 'Weight (kg)' })}</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((b) => (
                    <tr key={b.id} className="border-b border-border-light">
                      <td className="px-3 py-2">{b.member}</td>
                      <td className="px-3 py-2" dir="ltr">{b.bar_mark}</td>
                      <td className="px-3 py-2" dir="ltr">{b.shape_code}</td>
                      <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{b.diameter_mm}</td>
                      <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{b.members_count * b.bars_per_member}</td>
                      <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{b.cut_length_mm}</td>
                      <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{b.total_length_m}</td>
                      <td className="px-3 py-2 text-end font-medium tabular-nums" dir="ltr">{b.weight_kg}</td>
                      <td className="px-3 py-2 text-end">
                        <button
                          type="button"
                          className="p-1.5 text-content-tertiary hover:text-semantic-error"
                          aria-label={t('common.delete', { defaultValue: 'Delete' })}
                          onClick={() => del.mutate(b.id)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card padding="sm">
            <h3 className="mb-2 text-sm font-semibold text-content-primary">
              {t('rebar_schedule.bbs_totals', { defaultValue: 'Totals by diameter' })}
            </h3>
            <table className="w-full text-sm">
              <tbody>
                {(bbsQ.data?.totals_by_diameter ?? []).map((d) => (
                  <tr key={d.diameter_mm} className="border-b border-border-light">
                    <td className="py-1 tabular-nums" dir="ltr">{'Ø'}{d.diameter_mm}</td>
                    <td className="py-1 text-end tabular-nums" dir="ltr">{d.bar_count}</td>
                    <td className="py-1 text-end tabular-nums" dir="ltr">{d.total_length_m} m</td>
                    <td className="py-1 text-end tabular-nums" dir="ltr">{d.weight_kg} kg</td>
                  </tr>
                ))}
                <tr className="font-semibold">
                  <td className="py-1" colSpan={3}>{t('rebar_schedule.bbs_total_weight', { defaultValue: 'Total weight' })}</td>
                  <td className="py-1 text-end tabular-nums" dir="ltr">{bbsQ.data?.total_weight_kg} kg</td>
                </tr>
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}
