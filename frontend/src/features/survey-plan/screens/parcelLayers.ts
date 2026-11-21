// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Parcels and work zones as plan layers. Every side carries its length and
 * bearing, every parcel its reference and area, all in the project
 * conventions (units module), never formatted by hand.
 */

import type { GridXYZ, PlanFeature, PlanLayerSpec } from '../types';
import type { PlanConventions } from '../units/conventions';
import { azimuthOf, formatDirection } from '../units/angles';
import { formatArea, formatDistance } from '../units/linear';
import { layer } from '../planLayers';
import { ringAreaM2, type ParcelCheckSettings } from '../engine/ringChecks';
import type { GridCorner, GridParcel, GridZone, SurveyGrid } from './api';

/** Working copy of a parcel's corners while it is edited (parcel id -> corners). */
export type CornerEdits = Record<string, GridCorner[]>;

export function cornersOf(p: GridParcel, edits: CornerEdits): GridCorner[] {
  return edits[p.id] ?? p.points;
}

export function sideLabel(a: readonly [number, number], b: readonly [number, number], conv: PlanConventions): string {
  const d = Math.hypot(b[0] - a[0], b[1] - a[1]);
  return `${formatDirection(azimuthOf(a, b), conv)}  ${formatDistance(d, conv)}`;
}

export function parcelFeature(p: GridParcel, corners: GridCorner[], conv: PlanConventions): PlanFeature {
  const ring: GridXYZ[] = corners.map((c) => [c.e, c.n]);
  return {
    id: `parcel:${p.id}`,
    layer: 'parcels',
    entityType: 'parcel',
    entityId: p.id,
    geometry: { type: 'Polygon', coordinates: [ring] },
    properties: {
      ref: p.ref,
      status: p.status,
      legal_area: p.legal_area,
      label: ring.length >= 3 ? `${p.ref}  ${formatArea(ringAreaM2(ring), conv)}` : p.ref,
      fill: `var(--oe-map-${p.status === 'acquired' ? 'success' : p.status === 'needed' ? 'warning' : 'parcel'})`,
    },
  };
}

export function zoneFeature(z: GridZone, ring?: Array<[number, number]>): PlanFeature {
  return {
    id: `zone:${z.id}`,
    layer: 'zones',
    entityType: 'work_zone',
    entityId: z.id,
    geometry: { type: 'Polygon', coordinates: [(ring ?? z.ring).map((p) => [p[0], p[1]] as GridXYZ)] },
    properties: { name: z.name, label: z.name },
  };
}

/** Side dimensions of the parcels as short lines carrying "bearing  distance". */
export function dimensionFeatures(parcels: readonly GridParcel[], edits: CornerEdits, conv: PlanConventions): PlanFeature[] {
  const out: PlanFeature[] = [];
  const seen = new Set<string>();
  for (const p of parcels) {
    const c = cornersOf(p, edits);
    for (let i = 0; i < c.length && c.length >= 3; i++) {
      const a = c[i]!, b = c[(i + 1) % c.length]!;
      // A shared side is labelled once.
      const key = [a.e.toFixed(3), a.n.toFixed(3), b.e.toFixed(3), b.n.toFixed(3)];
      const k1 = key.join(','), k2 = [key[2], key[3], key[0], key[1]].join(',');
      if (seen.has(k1) || seen.has(k2)) continue;
      seen.add(k1);
      out.push({
        id: `dim:${p.id}:${i}`,
        layer: 'parcel_dims',
        geometry: { type: 'LineString', coordinates: [[a.e, a.n], [b.e, b.n]] },
        properties: { label: sideLabel([a.e, a.n], [b.e, b.n], conv), colour: 'var(--oe-map-ink-2)' },
      });
    }
  }
  return out;
}

export function cornerFeatures(parcels: readonly GridParcel[], edits: CornerEdits): PlanFeature[] {
  const seen = new Map<string, PlanFeature>();
  for (const p of parcels) {
    for (const c of cornersOf(p, edits)) {
      const key = c.label || `${c.e.toFixed(3)},${c.n.toFixed(3)}`;
      if (!seen.has(key)) {
        seen.set(key, {
          id: `corner:${key}`,
          layer: 'points',
          geometry: { type: 'Point', coordinates: [c.e, c.n] },
          properties: { label: c.label, mark: c.mark, colour: c.mark && c.mark !== 'unmarked' ? 'var(--oe-map-ink)' : 'var(--oe-map-warning)' },
        });
      }
    }
  }
  return [...seen.values()];
}

export function parcelLayers(grid: SurveyGrid, edits: CornerEdits, conv: PlanConventions, zoneEdits: Record<string, Array<[number, number]>> = {}): PlanLayerSpec[] {
  const parcels = grid.parcels.map((p) => parcelFeature(p, cornersOf(p, edits), conv));
  return [
    layer('parcels', parcels, { editable: true }),
    layer('zones', grid.zones.map((z) => zoneFeature(z, zoneEdits[z.id]))),
    {
      id: 'parcel_dims',
      titleKey: 'plan.parcel.layer_dims',
      defaultTitle: 'Side bearings and distances',
      order: 65,
      features: dimensionFeatures(grid.parcels, edits, conv),
      snappable: false,
      selectable: false,
      labelPriority: 50,
    },
    layer('points', cornerFeatures(grid.parcels, edits)),
  ];
}

/** Settings of the live checks from the server's grid answer. */
export function checkSettings(grid: SurveyGrid | undefined): ParcelCheckSettings {
  const tol = new Map<string, number>();
  for (const p of grid?.parcels ?? []) if (p.legal_area != null && p.tolerance_m2 != null) tol.set(String(Number(p.legal_area)), Number(p.tolerance_m2));
  return {
    gapToleranceM: Number(grid?.gap_tolerance_m ?? 0) || 0,
    areaTolerance: (legal) => tol.get(String(legal)) ?? null,
    idPattern: grid?.id_pattern ?? '',
  };
}

export interface AreaRow {
  id: string;
  ref: string;
  computed: number;
  registered: number | null;
  diff: number | null;
  tolerance: number | null;
  within: boolean | null;
}

/** Computed against registered area per parcel, with the tolerance the server resolved (pack or neutral default). */
export function areaComparison(grid: SurveyGrid, edits: CornerEdits): AreaRow[] {
  return grid.parcels.map((p) => {
    const computed = ringAreaM2(cornersOf(p, edits).map((c) => [c.e, c.n] as GridXYZ));
    const registered = p.legal_area != null ? Number(p.legal_area) : null;
    const tolerance = p.tolerance_m2 != null ? Number(p.tolerance_m2) : null;
    const diff = registered != null ? computed - registered : null;
    return { id: p.id, ref: p.ref, computed, registered, diff, tolerance, within: diff != null && tolerance != null ? Math.abs(diff) <= tolerance : null };
  });
}
