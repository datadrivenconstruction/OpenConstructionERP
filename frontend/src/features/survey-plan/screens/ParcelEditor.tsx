// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Parcel plan editor: parcels with side bearings and distances and areas in
 * the project units, corner coordinates and marks edited in place with the
 * parcel checks (PAR-001..006) running on every keystroke, the boundary
 * point register, and computed against registered area. Saving writes the
 * corners through the parcel API; the server checks are the record.
 */

import { useMemo, useState, type ComponentType } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Printer, RotateCcw, Save, Sparkles } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import type { PlanCanvasProps } from '../types';
import { usePlanConventions } from '../hooks';
import { axisLabelFor, formatArea, formatCoord, fromDisplayOrder, inputDistance, parseDistance, toDisplayOrder } from '../units/linear';
import { parcelFindings, zoneFindings } from '../engine/ringChecks';
import { PrintDialog } from '../print/PrintDialog';
import { PlanFrame } from './PlanFrame';
import { p2Api, p2Keys, type GridCorner } from './api';
import { areaComparison, checkSettings, cornersOf, parcelLayers, type CornerEdits } from './parcelLayers';

interface ProfileMarks { marks?: Array<{ key: string; monumented: boolean }> }

export interface ParcelEditorProps {
  projectId: string;
  canWrite: boolean;
  canvas?: ComponentType<PlanCanvasProps>;
}

export function ParcelEditor({ projectId, canWrite, canvas }: ParcelEditorProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { conventions: conv } = usePlanConventions(projectId);
  const grid = useQuery({ queryKey: p2Keys.grid(projectId), queryFn: () => p2Api.surveyGrid(projectId) });
  const register = useQuery({ queryKey: p2Keys.points(projectId), queryFn: () => p2Api.boundaryPoints(projectId) });
  const profile = useQuery({
    queryKey: ['land-parcels', 'profile', projectId],
    queryFn: async () => (await import('@/features/land-parcels/api')).getProfile(projectId) as Promise<ProfileMarks>,
  });
  const [edits, setEdits] = useState<CornerEdits>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [printing, setPrinting] = useState(false);

  const layers = useMemo(() => (grid.data ? parcelLayers(grid.data, edits, conv) : []), [grid.data, edits, conv]);
  const findings = useMemo(() => {
    const feats = layers.flatMap((l) => l.features);
    return [...parcelFindings(feats, checkSettings(grid.data)), ...zoneFindings(feats)];
  }, [layers, grid.data]);
  const areas = useMemo(() => (grid.data ? areaComparison(grid.data, edits) : []), [grid.data, edits]);

  const parcelId = selected?.startsWith('parcel:') ? selected.slice(7) : null;
  const parcel = grid.data?.parcels.find((p) => p.id === parcelId) ?? null;
  const corners = parcel ? cornersOf(parcel, edits) : [];
  const dirty = Object.keys(edits);
  const marks = profile.data?.marks ?? [];
  const axes = axisLabelFor(conv.axis);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: p2Keys.grid(projectId) });
    void qc.invalidateQueries({ queryKey: p2Keys.points(projectId) });
    void qc.invalidateQueries({ queryKey: ['land-parcels'] });
  };
  const save = useMutation({
    mutationFn: async () => {
      for (const id of dirty) await p2Api.setParcelPoints(id, edits[id]!);
    },
    onSuccess: () => {
      setEdits({});
      refresh();
      addToast({ type: 'success', title: t('plan.parcel.saved', { defaultValue: 'Parcel boundaries saved' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const demo = useMutation({
    mutationFn: () => p2Api.loadDemo(projectId),
    onSuccess: (r) => {
      refresh();
      addToast({ type: 'success', title: t('plan.parcel.demo_loaded', { defaultValue: 'Demo parcels loaded: {{n}}', n: r.parcels }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const setCorner = (i: number, patch: Partial<GridCorner>) => {
    if (!parcel) return;
    const next = corners.map((c, k) => (k === i ? { ...c, ...patch } : c));
    setEdits((e) => ({ ...e, [parcel.id]: next }));
  };
  const setCoord = (i: number, which: 0 | 1, text: string) => {
    const c = corners[i];
    const v = parseDistance(text, conv);
    if (!c || v == null) return;
    const shown = toDisplayOrder(c.e, c.n, conv.axis);
    shown[which] = v;
    const [e, n] = fromDisplayOrder(shown[0], shown[1], conv.axis);
    setCorner(i, { e, n });
  };

  const toolbar = (
    <>
      {canWrite && grid.data && grid.data.parcels.length === 0 && (
        <Button variant="secondary" size="sm" icon={<Sparkles size={14} />} loading={demo.isPending} onClick={() => demo.mutate()} data-testid="plan-parcel-demo">
          {t('plan.parcel.load_demo', { defaultValue: 'Load riverside demo' })}
        </Button>
      )}
      {dirty.length > 0 && (
        <Button variant="ghost" size="sm" icon={<RotateCcw size={14} />} onClick={() => setEdits({})}>
          {t('plan.parcel.discard', { defaultValue: 'Discard changes' })}
        </Button>
      )}
      {canWrite && (
        <Button variant="primary" size="sm" icon={<Save size={14} />} disabled={!dirty.length} loading={save.isPending} onClick={() => save.mutate()} data-testid="plan-parcel-save">
          {t('plan.parcel.save', { defaultValue: 'Save boundaries' })}
        </Button>
      )}
      <Button variant="secondary" size="sm" icon={<Printer size={14} />} disabled={!layers.some((l) => l.features.length)} onClick={() => setPrinting(true)} data-testid="plan-parcel-print">
        {t('plan.print.action', { defaultValue: 'Print plan' })}
      </Button>
    </>
  );

  const side = parcel ? (
    <section data-testid="plan-parcel-corners">
      <h3 className="mb-1 font-semibold text-content-primary">
        {t('plan.parcel.corners_of', { defaultValue: 'Corners of {{ref}}', ref: parcel.ref })}
      </h3>
      <table className="w-full text-xs">
        <thead className="text-content-tertiary">
          <tr>
            <th className="text-left font-medium">{t('plan.parcel.point_no', { defaultValue: 'Point' })}</th>
            <th className="text-right font-medium">{axes.e}</th>
            <th className="text-right font-medium">{axes.n}</th>
            <th className="text-left font-medium">{t('plan.parcel.mark', { defaultValue: 'Mark' })}</th>
          </tr>
        </thead>
        <tbody>
          {corners.map((c, i) => {
            const shown = toDisplayOrder(c.e, c.n, conv.axis);
            return (
              <tr key={i}>
                <td className="pr-1">{c.label || `#${i + 1}`}</td>
                {([0, 1] as const).map((k) => (
                  <td key={k} className="px-0.5">
                    <input
                      className="oe-input w-full px-1 py-0.5 text-right tabular-nums"
                      defaultValue={inputDistance(shown[k], conv)}
                      key={`${parcel.id}:${i}:${k}:${shown[k]}`}
                      disabled={!canWrite}
                      onBlur={(e) => setCoord(i, k, e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') setCoord(i, k, (e.target as HTMLInputElement).value); }}
                      aria-label={`${c.label || i + 1} ${k === 0 ? axes.e : axes.n}`}
                    />
                  </td>
                ))}
                <td className="pl-1">
                  <select className="oe-input w-full px-1 py-0.5" value={c.mark} disabled={!canWrite} onChange={(e) => setCorner(i, { mark: e.target.value })}>
                    <option value="">-</option>
                    {marks.map((m) => (
                      <option key={m.key} value={m.key}>{t(`plan.parcel.mark_${m.key}`, { defaultValue: m.key })}</option>
                    ))}
                  </select>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  ) : (
    <p className="text-xs text-content-secondary">{t('plan.parcel.select_hint', { defaultValue: 'Select a parcel to edit its corners and marks' })}</p>
  );

  return (
    <div className="space-y-4">
      <PlanFrame projectId={projectId} layers={layers} findings={findings} selected={selected} onSelect={setSelected} toolbar={toolbar} side={side} canvas={canvas} testId="plan-parcels" />

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="overflow-auto rounded-lg border border-border-light p-3" data-testid="plan-area-comparison">
          <h3 className="mb-2 text-sm font-semibold">{t('plan.parcel.area_title', { defaultValue: 'Computed against registered area' })}</h3>
          <table className="w-full text-xs tabular-nums">
            <thead className="text-content-tertiary">
              <tr>
                <th className="text-left font-medium">{t('plan.parcel.parcel', { defaultValue: 'Parcel' })}</th>
                <th className="text-right font-medium">{t('plan.parcel.area_computed', { defaultValue: 'Computed' })}</th>
                <th className="text-right font-medium">{t('plan.parcel.area_registered', { defaultValue: 'Registered' })}</th>
                <th className="text-right font-medium">{t('plan.parcel.area_diff', { defaultValue: 'Difference' })}</th>
                <th className="text-right font-medium">{t('plan.parcel.area_tolerance', { defaultValue: 'Tolerance' })}</th>
              </tr>
            </thead>
            <tbody>
              {areas.map((r) => (
                <tr key={r.id} className={r.within === false ? 'text-semantic-error' : ''}>
                  <td className="text-left">{r.ref}</td>
                  <td className="text-right">{formatArea(r.computed, conv)}</td>
                  <td className="text-right">{r.registered != null ? formatArea(r.registered, conv) : '-'}</td>
                  <td className="text-right">{r.diff != null ? `${r.diff > 0 ? '+' : ''}${formatArea(r.diff, conv)}` : '-'}</td>
                  <td className="text-right">{r.tolerance != null ? formatArea(r.tolerance, conv) : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="overflow-auto rounded-lg border border-border-light p-3" data-testid="plan-boundary-register">
          <h3 className="mb-1 text-sm font-semibold">{t('plan.parcel.register_title', { defaultValue: 'Boundary point register' })}</h3>
          {register.data && (
            <p className="mb-2 text-xs text-content-secondary">
              {t('plan.parcel.register_summary', {
                defaultValue: '{{total}} points, {{monumented}} monumented, {{unmarked}} unmarked, {{conflicts}} with conflicting marks',
                total: register.data.total, monumented: register.data.monumented, unmarked: register.data.unmarked, conflicts: register.data.conflicts,
              })}
            </p>
          )}
          <table className="w-full text-xs tabular-nums">
            <thead className="text-content-tertiary">
              <tr>
                <th className="text-left font-medium">{t('plan.parcel.point_no', { defaultValue: 'Point' })}</th>
                <th className="text-right font-medium">{axes.e}</th>
                <th className="text-right font-medium">{axes.n}</th>
                <th className="text-left font-medium">{t('plan.parcel.mark', { defaultValue: 'Mark' })}</th>
                <th className="text-left font-medium">{t('plan.parcel.parcels', { defaultValue: 'Parcels' })}</th>
              </tr>
            </thead>
            <tbody>
              {(register.data?.items ?? []).map((r) => {
                const [a, b] = toDisplayOrder(r.e, r.n, conv.axis);
                return (
                  <tr key={r.point_no} className={r.mark_conflict ? 'text-semantic-error' : r.monumented === false ? 'text-amber-700' : ''}>
                    <td>{r.point_no}</td>
                    <td className="text-right">{formatCoord(a, conv)}</td>
                    <td className="text-right">{formatCoord(b, conv)}</td>
                    <td>{r.mark ? t(`plan.parcel.mark_${r.mark}`, { defaultValue: r.mark }) : '-'}</td>
                    <td>{fmtList(r.parcels)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      </div>

      {printing && (
        <PrintDialog
          open={printing}
          onClose={() => setPrinting(false)}
          projectId={projectId}
          layers={layers}
          conventions={conv}
          defaultTitle={t('plan.parcel.print_title', { defaultValue: 'Land parcel plan' })}
        />
      )}
    </div>
  );
}

export default ParcelEditor;
