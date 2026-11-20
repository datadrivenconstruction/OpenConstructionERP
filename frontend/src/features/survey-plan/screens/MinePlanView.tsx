// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The mine on the plan: pit and bench contours of the period's latest
 * surface, blast block outlines from the design collars, and the period's
 * reconciliation as a cut/fill map (base minus compare surface of the
 * measured volume) beside the plan against measured table.
 */

import { useMemo, useState, type ComponentType } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';
import type { GridXYZ, PlanCanvasProps, PlanFeature, PlanLayerSpec } from '../types';
import { layer } from '../planLayers';
import { SurfaceView } from './SurfaceView';
import { p2Api, p2Keys, type HeatGrid, type MinePlan } from './api';
import { DH_CLASSES, heatFeatures } from './surfaceLayers';

export function blastLayer(plan: MinePlan): PlanLayerSpec {
  const features: PlanFeature[] = [];
  for (const b of plan.blast_blocks) {
    if (b.ring.length >= 3) {
      features.push({
        id: `blast:${b.pattern_id}`,
        layer: 'blast_blocks',
        geometry: { type: 'Polygon', coordinates: [b.ring.map((p) => [p[0], p[1]] as GridXYZ)] },
        properties: { label: b.code, colour: 'var(--oe-map-warning)', fill: 'none' },
      });
    }
    b.holes.forEach((h, i) => {
      features.push({ id: `hole:${b.pattern_id}:${i}`, layer: 'blast_blocks', geometry: { type: 'Point', coordinates: [h[0], h[1]] }, properties: { colour: 'var(--oe-map-ink-2)' } });
    });
  }
  return { id: 'blast_blocks', titleKey: 'plan.tin.layer_blast', defaultTitle: 'Blast blocks', order: 57, features, snappable: true, selectable: true, labelPriority: 60 };
}

export interface MinePlanViewProps {
  projectId: string;
  canvas?: ComponentType<PlanCanvasProps>;
}

export function MinePlanView({ projectId, canvas }: MinePlanViewProps) {
  const { t } = useTranslation();
  const [periodId, setPeriodId] = useState<string | null>(null);
  const [volumeId, setVolumeId] = useState<string | null>(null);
  const plan = useQuery({ queryKey: p2Keys.mine(projectId, periodId), queryFn: () => p2Api.minePlan(projectId, periodId) });
  const p = plan.data;
  const rows = (p?.reconciliation ?? []).filter((r) => r.volume_id);
  const vid = volumeId && rows.some((r) => r.volume_id === volumeId) ? volumeId : rows[0]?.volume_id ?? null;
  const heat = useQuery({
    queryKey: ['survey-plan', 'p2', 'volume-heat', vid],
    queryFn: () => apiGet<{ heat: HeatGrid | null }>(`/v1/surfaces-volumes/volumes/${vid}/heat`),
    enabled: !!vid,
  });
  const layers = useMemo(() => {
    if (!p) return [];
    const cutFill = heat.data?.heat ? heatFeatures(heat.data.heat, `cf:${vid}`) : [];
    return [layer('heat', cutFill), blastLayer(p)];
  }, [p, heat.data, vid]);

  if (!p) return null;
  const row = rows.find((r) => r.volume_id === vid);
  const surfaces = [
    ...(p.pit_surface_id ? [{ id: p.pit_surface_id, name: t('plan.tin.pit_surface', { defaultValue: 'Pit surface, end of period' }) }] : []),
    ...(row?.base_surface_id && row.base_surface_id !== p.pit_surface_id ? [{ id: row.base_surface_id, name: t('plan.tin.period_start_surface', { defaultValue: 'Surface at period start' }) }] : []),
  ];

  const side = (
    <section className="space-y-2 text-xs" data-testid="plan-mine-reconciliation">
      <select className="oe-input w-full py-1" value={p.period_id ?? ''} onChange={(e) => setPeriodId(e.target.value || null)} aria-label={t('plan.tin.period', { defaultValue: 'Period' })}>
        {p.periods.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
      </select>
      <table className="w-full tabular-nums">
        <thead className="text-content-tertiary">
          <tr>
            <th className="text-left font-medium">{t('plan.tin.unit', { defaultValue: 'Unit' })}</th>
            <th className="text-right font-medium">{t('plan.tin.planned', { defaultValue: 'Plan, m³' })}</th>
            <th className="text-right font-medium">{t('plan.tin.cut', { defaultValue: 'Cut, m³' })}</th>
            <th className="text-right font-medium">{t('plan.tin.fill', { defaultValue: 'Fill, m³' })}</th>
          </tr>
        </thead>
        <tbody>
          {p.reconciliation.map((r) => (
            <tr key={r.entry_id} className={r.volume_id === vid ? 'bg-surface-secondary' : r.volume_id ? 'cursor-pointer hover:bg-surface-secondary' : 'text-content-tertiary'}
              onClick={() => r.volume_id && setVolumeId(r.volume_id)}>
              <td>{r.unit_code}</td>
              <td className="text-right">{r.plan_m3}</td>
              <td className="text-right">{r.cut_m3 ?? '-'}</td>
              <td className="text-right">{r.fill_m3 ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex flex-wrap gap-1" aria-label={t('plan.tin.cutfill_legend', { defaultValue: 'Cut and fill depth' })}>
        {DH_CLASSES.map((c) => (
          <span key={c.token} className="inline-flex items-center gap-1">
            <span className="inline-block h-2.5 w-3 rounded-sm" style={{ background: `var(--oe-map-${c.token})` }} />
            <span className="text-[10px] text-content-tertiary">{Number.isFinite(c.min) ? `${c.min > 0 ? '+' : ''}${c.min}` : ''}</span>
          </span>
        ))}
      </div>
      {!rows.length && <p className="text-content-secondary">{t('plan.tin.no_measured', { defaultValue: 'No measured volume in this period yet: link a volume calculation to a unit to see its cut and fill here.' })}</p>}
    </section>
  );

  if (!surfaces.length && !layers.some((l) => l.features.length)) {
    return <p className="text-sm text-content-secondary">{t('plan.tin.mine_empty', { defaultValue: 'Nothing to draw yet: add a blast pattern or a measured volume to a period.' })}</p>;
  }
  return (
    <SurfaceView projectId={projectId} surfaces={surfaces} extraLayers={layers} side={side} canvas={canvas}
      printTitle={t('plan.tin.mine_print_title', { defaultValue: 'Pit plan and period reconciliation' })} testId="plan-mine" />
  );
}

export default MinePlanView;
