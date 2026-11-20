// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Surface layers: contours (index lines labelled with their height), the
 * shaded relief raster, and height-difference grids (stockpile height,
 * cut/fill) as coloured cells.
 */

import type { GridXYZ, PlanFeature, PlanLayerSpec } from '../types';
import type { PlanConventions } from '../units/conventions';
import { formatDistance } from '../units/linear';
import { layer } from '../planLayers';
import { rasterise, shadedRelief, type Mesh } from '../engine/hillshade';
import type { Contours, HeatGrid } from './api';

export function contourFeatures(c: Contours, conv: PlanConventions, prefix = 'contour'): PlanFeature[] {
  return c.lines.map((l, i) => ({
    id: `${prefix}:${i}`,
    layer: 'contours',
    geometry: l.closed && l.coords.length >= 3
      ? { type: 'Polygon' as const, coordinates: [l.coords.map((p) => [p[0], p[1]] as GridXYZ)] }
      : { type: 'LineString' as const, coordinates: l.coords.map((p) => [p[0], p[1]] as GridXYZ) },
    properties: { z: l.z, index: l.index, label: l.index ? formatDistance(l.z, conv, false) : undefined, colour: 'var(--oe-map-topo)', fill: 'none' },
  }));
}

export function contourLayer(c: Contours | undefined, conv: PlanConventions): PlanLayerSpec {
  return layer('contours', c ? contourFeatures(c, conv) : [], { labelPriority: 30 });
}

/** The relief as a PNG data URL and its grid bounds; null without a DOM canvas (tests, SSR). */
export function reliefImage(mesh: Mesh | undefined, maxCells = 160_000): { dataUrl: string; bounds: [number, number, number, number] } | null {
  if (!mesh || typeof document === 'undefined') return null;
  const r = rasterise(mesh, maxCells);
  if (!r) return null;
  const canvas = document.createElement('canvas');
  canvas.width = r.nx;
  canvas.height = r.ny;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const img = ctx.createImageData(r.nx, r.ny);
  img.data.set(shadedRelief(r));
  ctx.putImageData(img, 0, 0);
  return { dataUrl: canvas.toDataURL('image/png'), bounds: [r.originE, r.originN, r.originE + r.nx * r.cell, r.originN + r.ny * r.cell] };
}

/** Diverging cut/fill classes: dh > 0 is material above the base (fill on a pile, cut in a pit period). */
export const DH_CLASSES: Array<{ min: number; token: string }> = [
  { min: 2, token: 'cut-3' },
  { min: 0.5, token: 'cut-2' },
  { min: 0.05, token: 'cut-1' },
  { min: -0.05, token: 'neutral' },
  { min: -0.5, token: 'fill-1' },
  { min: -2, token: 'fill-2' },
  { min: -Infinity, token: 'fill-3' },
];

export function dhToken(dh: number): string {
  return DH_CLASSES.find((c) => dh >= c.min)!.token;
}

/**
 * Cells of a height-difference grid merged per row into runs of the same
 * class, so a 200 x 200 grid becomes a few thousand rectangles, not 40 000.
 */
export function heatFeatures(h: HeatGrid, prefix = 'heat', skipNeutral = true): PlanFeature[] {
  const out: PlanFeature[] = [];
  for (let j = 0; j < h.ny; j++) {
    let i = 0;
    while (i < h.nx) {
      const v = h.dh[j * h.nx + i];
      if (v == null) { i++; continue; }
      const token = dhToken(v);
      let k = i + 1;
      while (k < h.nx) {
        const w = h.dh[j * h.nx + k];
        if (w == null || dhToken(w) !== token) break;
        k++;
      }
      if (!(skipNeutral && token === 'neutral')) {
        const e0 = h.origin_e + i * h.cell, e1 = h.origin_e + k * h.cell;
        const n0 = h.origin_n + j * h.cell, n1 = n0 + h.cell;
        out.push({
          id: `${prefix}:${j}:${i}`,
          layer: 'heat',
          geometry: { type: 'Polygon', coordinates: [[[e0, n0], [e1, n0], [e1, n1], [e0, n1]]] },
          properties: { token, fill: `var(--oe-map-${token})`, colour: `var(--oe-map-${token})` },
        });
      }
      i = k;
    }
  }
  return out;
}
