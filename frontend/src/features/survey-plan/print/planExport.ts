// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plan layers to the two outputs: print layers for the PDF and the body of
 * `POST survey_core/projects/{id}/plan.dxf` (one DXF layer per plan layer).
 */

import { fetchWithAuth, triggerDownload } from '@/shared/lib/api';
import type { PlanFeature, PlanLayerSpec } from '../types';
import type { MapPalette, MapToken } from '../cartography';
import type { PlanDxfBody, PlanDxfFeature, PlanDxfLayer } from '../screens/api';
import type { PrintLayer } from './pdfPlan';

/** Print colour token and AutoCAD colour index of each layer; unknown layers print in ink. */
const STYLE: Record<string, { token: MapToken; aci: number; legend: PrintLayer['legend']; fill?: boolean; dashed?: boolean; lineMm?: number }> = {
  parcels: { token: 'parcel', aci: 5, legend: 'swatch', fill: true, lineMm: 0.35 },
  zones: { token: 'zone', aci: 6, legend: 'line', dashed: true, lineMm: 0.35 },
  pads: { token: 'surface', aci: 4, legend: 'line', lineMm: 0.35 },
  contours: { token: 'topo', aci: 8, legend: 'line', lineMm: 0.13 },
  breaklines: { token: 'breakline', aci: 30, legend: 'line', lineMm: 0.18 },
  points: { token: 'ink', aci: 7, legend: 'point' },
  control: { token: 'ink', aci: 1, legend: 'point' },
  heat: { token: 'neutral', aci: 9, legend: 'swatch', fill: true },
  surfaces: { token: 'surface', aci: 4, legend: 'line' },
  sketch: { token: 'ink-2', aci: 7, legend: 'line' },
  traverse: { token: 'accent', aci: 5, legend: 'line', lineMm: 0.35 },
  misclosure: { token: 'misclosure', aci: 6, legend: 'line', lineMm: 0.35 },
  ellipses: { token: 'misclosure', aci: 6, legend: 'line', lineMm: 0.18 },
  alignment: { token: 'accent', aci: 5, legend: 'line', lineMm: 0.5 },
  chainage: { token: 'ink', aci: 7, legend: 'line', lineMm: 0.18 },
  stakes: { token: 'ink', aci: 7, legend: 'point' },
  stake_deviation: { token: 'error', aci: 1, legend: 'line', lineMm: 0.25 },
  monitoring: { token: 'ink', aci: 7, legend: 'point' },
  monitoring_vectors: { token: 'error', aci: 1, legend: 'line', lineMm: 0.25 },
};

export function printLayers(layers: readonly PlanLayerSpec[], palette: MapPalette, title: (l: PlanLayerSpec) => string): PrintLayer[] {
  return [...layers]
    .filter((l) => l.features.length > 0)
    .sort((a, b) => a.order - b.order)
    .map((l) => {
      const s = STYLE[l.id] ?? { token: 'ink' as MapToken, aci: 7, legend: 'line' as const };
      const colour = typeof l.features[0]?.properties.printColour === 'string' ? String(l.features[0]!.properties.printColour) : palette[s.token];
      return { id: l.id, title: title(l), colour, features: l.features, lineMm: s.lineMm, dashed: s.dashed, fill: s.fill, labelPriority: l.labelPriority, legend: s.legend };
    });
}

function dxfFeature(f: PlanFeature): PlanDxfFeature | null {
  const g = f.geometry;
  const label = f.properties.label == null ? '' : String(f.properties.label).slice(0, 200);
  if (g.type === 'Point') return { kind: 'point', coords: [[...g.coordinates]], label };
  if (g.type === 'LineString') return g.coordinates.length >= 2 ? { kind: 'line', coords: g.coordinates.map((p) => [...p]), label } : null;
  const ring = g.coordinates[0] ?? [];
  return ring.length >= 3 ? { kind: 'polygon', coords: ring.map((p) => [...p]), label } : null;
}

export function dxfBody(layers: readonly PlanLayerSpec[], meta: { title: string; drawingNo: string; revision: string; scale: number }): PlanDxfBody {
  const out: PlanDxfLayer[] = [];
  for (const l of layers) {
    const features = l.features.map(dxfFeature).filter((f): f is PlanDxfFeature => f !== null);
    if (features.length) out.push({ id: String(l.id), aci: STYLE[l.id]?.aci ?? 7, features });
  }
  return { title: meta.title, drawing_no: meta.drawingNo, revision: meta.revision, scale: meta.scale, layers: out };
}

export async function downloadPlanDxf(projectId: string, body: PlanDxfBody, filename: string): Promise<void> {
  const res = await fetchWithAuth(`/api/v1/survey-core/projects/${projectId}/plan.dxf`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`DXF ${res.status}`);
  triggerDownload(await res.blob(), filename);
}
