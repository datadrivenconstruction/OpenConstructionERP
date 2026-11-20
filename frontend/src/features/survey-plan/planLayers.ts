// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The layer registry: fixed ids with their title, draw order and defaults.
 * A screen declares which layers exist by passing `layers`; work from other
 * packages plugs in through `extraLayers`. Neither redefines a known id.
 */

import type { KnownPlanLayerId, PlanFeature, PlanLayerSpec } from './types';

interface LayerMeta {
  titleKey: string;
  defaultTitle: string;
  order: number;
  snappable: boolean;
  selectable: boolean;
  labelPriority: number;
}

const m = (key: string, title: string, order: number, snappable = true, selectable = true, labelPriority = 40): LayerMeta => ({
  titleKey: `plan.layer.${key}`,
  defaultTitle: title,
  order,
  snappable,
  selectable,
  labelPriority,
});

export const LAYER_META: Record<KnownPlanLayerId, LayerMeta> = {
  heat: m('heat', 'Cut/fill', 10, false, false),
  pointcloud_heat: m('pointcloud_heat', 'Point cloud deviation', 15, false, false),
  surfaces: m('surfaces', 'Surfaces', 20, true, false),
  tin: m('tin', 'TIN', 30, false, false),
  contours: m('contours', 'Contours', 40, false, false),
  zones: m('zones', 'Work zones', 50),
  pads: m('pads', 'Design pads', 55),
  parcels: m('parcels', 'Parcels', 60, true, true, 80),
  breaklines: m('breaklines', 'Breaklines', 70),
  linework: m('linework', 'Linework', 80),
  sketch: m('sketch', 'Sketch', 90),
  alignment: m('alignment', 'Alignment', 100),
  sections: m('sections', 'Sections', 110),
  traverse: m('traverse', 'Traverse', 120, true, true, 90),
  ellipses: m('ellipses', 'Error ellipses', 125, false, false),
  stakes: m('stakes', 'Stakes', 130, true, true, 60),
  monitoring: m('monitoring', 'Monitoring', 140, true, true, 70),
  points: m('points', 'Points', 150, true, true, 40),
  control: m('control', 'Control', 160, true, true, 100),
  measure: m('measure', 'Measure', 200, false, false),
};

export function isKnownLayer(id: string): id is KnownPlanLayerId {
  return id in LAYER_META;
}

/** A layer spec with the registry defaults filled in. */
export function layer(id: KnownPlanLayerId, features: PlanFeature[], over: Partial<PlanLayerSpec> = {}): PlanLayerSpec {
  const meta = LAYER_META[id];
  return {
    id,
    titleKey: meta.titleKey,
    defaultTitle: meta.defaultTitle,
    order: meta.order,
    snappable: meta.snappable,
    selectable: meta.selectable,
    labelPriority: meta.labelPriority,
    features,
    ...over,
  };
}

/** Screen layers plus extra layers, by draw order. A known id from `extraLayers` never replaces the screen's. */
export function mergeLayers(layers: readonly PlanLayerSpec[], extra: readonly PlanLayerSpec[] = []): PlanLayerSpec[] {
  const byId = new Map<string, PlanLayerSpec>();
  for (const l of layers) byId.set(l.id, l);
  for (const l of extra) if (!byId.has(l.id)) byId.set(l.id, l);
  return [...byId.values()].sort((a, b) => a.order - b.order);
}
