// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A stockpile on the plan: height above the base as a coloured map, the toe
 * (where the pile rises 0.1 m above the base) and the crest, the pile's
 * contours and the survey's stored volume and tonnes. A survey picker steps
 * through the pile's history.
 */

import { useMemo, useState, type ComponentType } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import type { GridXYZ, PlanCanvasProps, PlanFeature, PlanLayerSpec } from '../types';
import { usePlanConventions } from '../hooks';
import { formatArea, formatDistance } from '../units/linear';
import { layer } from '../planLayers';
import { SurfaceView } from './SurfaceView';
import { p2Api, p2Keys, type StockpilePlan } from './api';
import { heatFeatures } from './surfaceLayers';

function ringFeature(id: string, layerId: string, ring: Array<[number, number]>, label: string, token: string): PlanFeature {
  return {
    id,
    layer: layerId,
    geometry: { type: 'Polygon', coordinates: [ring.map((p) => [p[0], p[1]] as GridXYZ)] },
    properties: { label, colour: `var(--oe-map-${token})`, fill: 'none' },
  };
}

export function stockpileLayers(p: StockpilePlan, labels: { toe: string; crest: string }): PlanLayerSpec[] {
  const outline: PlanFeature[] = [];
  if (p.toe.length >= 3) outline.push(ringFeature(`toe:${p.stockpile_id}`, 'stock_outline', p.toe, labels.toe, 'ink'));
  if (p.crest.length >= 3) outline.push(ringFeature(`crest:${p.stockpile_id}`, 'stock_outline', p.crest, labels.crest, 'breakline'));
  return [
    layer('heat', p.heat ? heatFeatures(p.heat, `pile:${p.stockpile_id}`) : [], { titleKey: 'plan.tin.layer_pile_height', defaultTitle: 'Height above base' }),
    { id: 'stock_outline', titleKey: 'plan.tin.layer_toe_crest', defaultTitle: 'Toe and crest', order: 58, features: outline, snappable: true, selectable: true, labelPriority: 70 },
  ];
}

export interface StockpilePlanViewProps {
  projectId: string;
  stockpileId: string;
  canvas?: ComponentType<PlanCanvasProps>;
}

export function StockpilePlanView({ projectId, stockpileId, canvas }: StockpilePlanViewProps) {
  const { t } = useTranslation();
  const { conventions: conv } = usePlanConventions(projectId);
  const [surveyId, setSurveyId] = useState<string | null>(null);
  const plan = useQuery({ queryKey: p2Keys.stockpile(stockpileId, surveyId), queryFn: () => p2Api.stockpilePlan(stockpileId, surveyId) });
  const p = plan.data;
  const layers = useMemo(
    () => (p ? stockpileLayers(p, { toe: t('plan.tin.toe', { defaultValue: 'Toe' }), crest: t('plan.tin.crest', { defaultValue: 'Crest' }) }) : []),
    [p, t],
  );
  if (!p) return null;
  const surfaces = [
    ...(p.pile_surface_id ? [{ id: p.pile_surface_id, name: t('plan.tin.pile_surface', { defaultValue: 'Pile surface' }) }] : []),
    ...(p.base_surface_id ? [{ id: p.base_surface_id, name: t('plan.tin.base_surface', { defaultValue: 'Base surface' }) }] : []),
  ];
  if (!p.survey_id) {
    return <p className="text-sm text-content-secondary">{t('plan.tin.pile_no_survey', { defaultValue: 'No survey of this pile yet.' })}</p>;
  }
  if (!p.base_surface_id || !p.pile_surface_id) {
    return <p className="text-sm text-content-secondary">{t('plan.tin.pile_no_surfaces', { defaultValue: 'This survey has a typed volume only: add a pile surface and a base surface to see it on the plan.' })}</p>;
  }

  const side = (
    <section className="space-y-1 text-xs" data-testid="plan-stockpile-facts">
      <h3 className="text-sm font-semibold text-content-primary">{p.code} {p.name}</h3>
      <select className="oe-input w-full py-1" value={p.survey_id ?? ''} onChange={(e) => setSurveyId(e.target.value || null)} aria-label={t('plan.tin.pile_survey', { defaultValue: 'Survey' })}>
        {p.surveys.map((s) => <option key={s.id} value={s.id}>{s.surveyed_on}</option>)}
      </select>
      <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5 tabular-nums">
        <dt className="text-content-tertiary">{t('plan.tin.pile_volume', { defaultValue: 'Volume' })}</dt>
        <dd className="text-right font-medium">{p.volume_m3 ?? '-'} m³</dd>
        <dt className="text-content-tertiary">{t('plan.tin.pile_tonnes', { defaultValue: 'Tonnes' })}</dt>
        <dd className="text-right">{p.tonnes ?? '-'} t</dd>
        <dt className="text-content-tertiary">{t('plan.tin.pile_height', { defaultValue: 'Highest point above base' })}</dt>
        <dd className="text-right">{formatDistance(p.max_height_m, conv)}</dd>
        <dt className="text-content-tertiary">{t('plan.tin.pile_footprint', { defaultValue: 'Footprint inside the toe' })}</dt>
        <dd className="text-right">{formatArea(p.footprint_m2, conv)}</dd>
      </dl>
    </section>
  );

  return (
    <SurfaceView projectId={projectId} surfaces={surfaces} surfaceId={p.pile_surface_id} extraLayers={layers} side={side} canvas={canvas}
      printTitle={t('plan.tin.pile_print_title', { defaultValue: 'Stockpile {{code}} survey {{date}}', code: p.code, date: p.surveyed_on })} testId="plan-stockpile" />
  );
}

export default StockpilePlanView;
