// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Monitoring points on the plan, coloured and shaped by alert level, with the
 * plan displacement since the baseline as an exaggerated arrow. Points with no
 * position yet are listed under "Not on the plan"; Set position arms the plan
 * and the next click places the mark (or type E/N).
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Crosshair, MapPin } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fmtMm } from '@/features/monitoring/levels';
import type { MapToken } from '../cartography';
import { planColour } from '../cartography';
import { ARROW_SCALES, deviationArrow, mmPerArrowMetre, type ArrowScale } from '../engine/deviationArrows';
import { usePlanConventions } from '../hooks';
import type { GridXY, PlanFeature } from '../types';
import { axisLabelFor, parseDistance } from '../units';
import { monitoringPlanApi, type MonitoringPlanPoint } from '../p3api';
import { PlanSketch, type SketchShape, type SketchStyle } from './PlanSketch';

type Lvl = 'none' | 'ok' | 'alert' | 'action' | 'alarm';
const LEVELS: Lvl[] = ['ok', 'alert', 'action', 'alarm', 'none'];
const LEVEL_STYLE: Record<Lvl, { token: MapToken; shape: SketchShape }> = {
  ok: { token: 'success', shape: 'circle' },
  alert: { token: 'warning', shape: 'diamond' },
  action: { token: 'error', shape: 'triangle' },
  alarm: { token: 'error', shape: 'square' },
  none: { token: 'ink-2', shape: 'cross' },
};
const LEVEL_DEFAULT: Record<Lvl, string> = { ok: 'OK', alert: 'Alert', action: 'Action', alarm: 'Alarm', none: 'No profile' };
const lvl = (l: string): Lvl => (l in LEVEL_STYLE ? (l as Lvl) : 'none');

/** Plan features of the points that have a position; arrows where a plan displacement is known. */
export function monitoringFeatures(items: readonly MonitoringPlanPoint[], scale: number): PlanFeature[] {
  const out: PlanFeature[] = [];
  for (const p of items) {
    if (p.e == null || p.n == null) continue;
    const at: GridXY = [p.e, p.n];
    out.push({ id: `mon:${p.id}`, layer: 'monitoring', geometry: { type: 'Point', coordinates: at }, properties: { role: 'point', level: lvl(p.level), label: p.code }, entityType: 'monitoring_point', entityId: p.id });
    if (p.de_mm == null || p.dn_mm == null) continue;
    const a = deviationArrow(at, [p.e + p.de_mm / 1000, p.n + p.dn_mm / 1000], scale);
    if (!a.head.length) continue;
    out.push({ id: `mon-arrow:${p.id}`, layer: 'monitoring', geometry: { type: 'LineString', coordinates: a.shaft }, properties: { role: 'arrow', level: lvl(p.level) } });
    out.push({ id: `mon-head:${p.id}`, layer: 'monitoring', geometry: { type: 'Polygon', coordinates: [a.head] }, properties: { role: 'head', level: lvl(p.level) } });
  }
  return out;
}

function Glyph({ level }: { level: Lvl }) {
  const { token, shape } = LEVEL_STYLE[level];
  const c = planColour(token);
  const d =
    shape === 'square' ? 'M3,3h8v8h-8Z' : shape === 'diamond' ? 'M7,1.5L12.5,7L7,12.5L1.5,7Z' : shape === 'triangle' ? 'M7,1.5L12.5,12L1.5,12Z' : shape === 'cross' ? 'M3,3L11,11M3,11L11,3' : 'M2.5,7a4.5,4.5 0 1,0 9,0a4.5,4.5 0 1,0 -9,0';
  return (
    <svg width={14} height={14} aria-hidden>
      <path d={d} fill={shape === 'cross' ? 'none' : c} stroke={c} strokeWidth={shape === 'cross' ? 2 : 1} />
    </svg>
  );
}

export function MonitoringMap({ projectId, canWrite, onOpenPoint }: { projectId: string; canWrite: boolean; onOpenPoint?: (id: string) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { conventions: conv } = usePlanConventions(projectId);
  const axes = axisLabelFor(conv.axis);
  const [scale, setScale] = useState<ArrowScale>(100);
  const [placing, setPlacing] = useState<string | null>(null);
  const [typed, setTyped] = useState({ e: '', n: '' });
  const plan = useQuery({ queryKey: ['monitoring', 'plan', projectId], queryFn: () => monitoringPlanApi.plan(projectId) });
  const items = plan.data?.items ?? [];
  const offPlan = items.filter((p) => p.e == null || p.n == null);
  const features = useMemo(() => monitoringFeatures(items, scale), [items, scale]);
  const fit = useMemo(() => features.filter((f) => f.properties.role === 'point'), [features]);

  const place = useMutation({
    mutationFn: ({ id, p }: { id: string; p: GridXY }) => monitoringPlanApi.setPosition(id, p[0], p[1]),
    onSuccess: (pt) => {
      setPlacing(null);
      setTyped({ e: '', n: '' });
      addToast({ type: 'success', title: t('plan.mon.placed', { defaultValue: '{{code}} is on the plan', code: pt.code }) });
      void qc.invalidateQueries({ queryKey: ['monitoring'] });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const demo = useMutation({
    mutationFn: () => monitoringPlanApi.demoPositions(projectId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['monitoring'] }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const styleFor = (f: PlanFeature): SketchStyle | null => {
    const st = LEVEL_STYLE[(f.properties.level as Lvl) ?? 'none'];
    if (f.properties.role === 'point') return { shape: st.shape, size: 5, stroke: st.token, fill: st.shape === 'cross' ? undefined : st.token, label: String(f.properties.label ?? ''), top: true };
    if (f.properties.role === 'arrow') return { stroke: st.token, width: 2 };
    if (f.properties.role === 'head') return { stroke: st.token, fill: st.token, width: 1 };
    return null;
  };
  const counts = LEVELS.map((l) => [l, items.filter((p) => lvl(p.level) === l && p.e != null).length] as const);
  const typedE = parseDistance(typed.e, conv);
  const typedN = parseDistance(typed.n, conv);

  return (
    <div className="grid gap-4 p-3 lg:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]" data-testid="monitoring-map">
      <PlanSketch
        features={features}
        fitTo={fit}
        styleFor={styleFor}
        conventions={conv}
        heightClass="h-[480px]"
        cursor={placing ? 'crosshair' : 'default'}
        onPick={(f) => f.entityId && onOpenPoint?.(f.entityId)}
        onPlanClick={placing ? (p) => place.mutate({ id: placing, p }) : undefined}
        testId="monitoring-plan"
      >
        {!fit.length && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center text-sm text-content-tertiary">
            {t('plan.mon.empty', { defaultValue: 'No point has a position yet. Set positions from the list, or import readings with E and N.' })}
          </div>
        )}
        {placing && (
          <div className="absolute start-3 top-3 rounded-lg border border-border-light bg-surface-primary/95 px-3 py-2 text-xs shadow-md">
            {t('plan.mon.click_to_place', { defaultValue: 'Click the plan where {{code}} is', code: items.find((p) => p.id === placing)?.code ?? '' })}
          </div>
        )}
        <div className="absolute bottom-3 end-3 space-y-1 rounded-lg border border-border-light bg-surface-primary/90 px-2.5 py-2 text-xs text-content-secondary" data-testid="monitoring-legend">
          {counts.map(([l, n]) => (
            <span key={l} className="flex items-center gap-1.5">
              <Glyph level={l} />
              {t(`plan.mon.level.${l}`, { defaultValue: LEVEL_DEFAULT[l] })}
              <span className="font-mono text-content-tertiary">{n}</span>
            </span>
          ))}
          <span className="block border-t border-border-light pt-1 text-content-tertiary">
            {t('plan.stake.scale_legend', { defaultValue: 'Arrows x{{s}}: 1 m of arrow = {{mm}} mm', s: scale, mm: mmPerArrowMetre(scale) })}
          </span>
        </div>
      </PlanSketch>

      <div className="space-y-3">
        <div className="flex h-8 w-fit rounded-lg border border-border-light p-0.5" role="group" aria-label={t('plan.stake.arrows', { defaultValue: 'Arrows' })}>
          {ARROW_SCALES.map((s) => (
            <button key={s} type="button" data-oe-segment aria-pressed={scale === s} onClick={() => setScale(s)}
              className={`rounded-sm px-2 font-mono text-xs ${scale === s ? 'bg-surface-secondary font-medium text-content-primary' : 'text-content-secondary'}`}>
              x{s}
            </button>
          ))}
        </div>
        <section className="rounded-xl border border-border-light p-3" data-testid="off-plan">
          <h3 className="oe-card-title">{t('plan.mon.off_plan', { defaultValue: 'Not on the plan ({{n}})', n: offPlan.length })}</h3>
          {offPlan.length === 0 ? (
            <p className="mt-1 text-xs text-content-tertiary">{t('plan.mon.all_placed', { defaultValue: 'Every point has a position.' })}</p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {offPlan.map((p) => (
                <li key={p.id} className="space-y-1">
                  <div className="flex items-center gap-2 text-sm">
                    <Glyph level={lvl(p.level)} />
                    <span className="font-mono">{p.code}</span>
                    <span className="truncate text-content-tertiary">{p.name}</span>
                    {p.displacement_mm != null && <span className="ms-auto font-mono text-xs">{fmtMm(p.displacement_mm)}</span>}
                  </div>
                  {canWrite && (placing === p.id ? (
                    <div className="flex gap-1">
                      <input className="oe-input-sm w-full font-mono" dir="ltr" placeholder={axes.e} aria-label={axes.e} value={typed.e} onChange={(e) => setTyped((s) => ({ ...s, e: e.target.value }))} />
                      <input className="oe-input-sm w-full font-mono" dir="ltr" placeholder={axes.n} aria-label={axes.n} value={typed.n} onChange={(e) => setTyped((s) => ({ ...s, n: e.target.value }))} />
                      <Button size="sm" disabled={typedE == null || typedN == null} loading={place.isPending}
                        onClick={() => typedE != null && typedN != null && place.mutate({ id: p.id, p: [typedE, typedN] })}>
                        {t('plan.mon.place', { defaultValue: 'Place' })}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setPlacing(null)}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
                    </div>
                  ) : (
                    <Button size="sm" variant="secondary" icon={<Crosshair size={14} />} onClick={() => setPlacing(p.id)}>
                      {t('plan.mon.set_position', { defaultValue: 'Set position' })}
                    </Button>
                  ))}
                </li>
              ))}
            </ul>
          )}
          {canWrite && offPlan.length > 0 && (
            <Button size="sm" variant="ghost" className="mt-2" icon={<MapPin size={14} />} loading={demo.isPending} onClick={() => demo.mutate()}>
              {t('plan.mon.demo_positions', { defaultValue: 'Use the example positions' })}
            </Button>
          )}
        </section>
        {fit.length > 0 && (
          <p className="text-xs text-content-tertiary">
            {t('plan.mon.position_source', { defaultValue: 'Positions come from the newest reading with E and N, else from the mark set on the plan.' })}
          </p>
        )}
      </div>
    </div>
  );
}
