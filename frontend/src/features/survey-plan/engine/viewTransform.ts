// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Grid <-> map view. A georeferenced project uses the backend's 2nd-order
 * polynomial (fitted on a 5x5 lattice, with its residual); a local grid uses a
 * linear pseudo-geographic mapping around the extent centre. The view only
 * draws: every number shown or saved comes from the grid.
 */

import type { GridXY, ViewTransformDTO } from '../types';

/** Metres per degree in the local-grid mapping. */
export const LOCAL_K = 111319.49;
/** Above this residual the status bar warns that the display is approximate. */
export const RESIDUAL_WARN_MM = 1;

export interface ViewTransform {
  kind: 'polynomial' | 'local';
  toView(p: GridXY): [number, number];
  toGrid(lonLat: readonly [number, number]): GridXY;
  residualMm: number;
  /** Map bearing that puts grid north up. */
  gridNorthBearing: number;
  epsg: number | null;
  crsName: string;
}

function poly(c: readonly number[], u: number, v: number): number {
  return c[0]! + c[1]! * u + c[2]! * v + c[3]! * u * u + c[4]! * u * v + c[5]! * v * v;
}

export function localTransform(e0: number, n0: number): ViewTransform {
  return {
    kind: 'local',
    toView: (p) => [(p[0] - e0) / LOCAL_K, (p[1] - n0) / LOCAL_K],
    toGrid: (ll) => [ll[0] * LOCAL_K + e0, ll[1] * LOCAL_K + n0],
    residualMm: 0,
    gridNorthBearing: 0,
    epsg: null,
    crsName: '',
  };
}

export function fromDTO(dto: ViewTransformDTO): ViewTransform {
  if (dto.kind === 'local') return { ...localTransform(dto.e0, dto.n0), crsName: dto.crs_name };
  const fwd = (p: GridXY): [number, number] => {
    const u = (p[0] - dto.e0) / dto.s;
    const v = (p[1] - dto.n0) / dto.s;
    return [poly(dto.lon, u, v), poly(dto.lat, u, v)];
  };
  return {
    kind: 'polynomial',
    toView: fwd,
    toGrid: (ll) => {
      const p = (ll[0] - dto.lon0) / dto.q;
      const r = (ll[1] - dto.lat0) / dto.q;
      let g: GridXY = [poly(dto.e, p, r), poly(dto.n, p, r)];
      // One Newton step on the forward fit makes the round trip exact to the fit.
      const h = 0.01;
      const f0 = fwd(g);
      const fe = fwd([g[0] + h, g[1]]);
      const fn = fwd([g[0], g[1] + h]);
      const j11 = (fe[0] - f0[0]) / h;
      const j12 = (fn[0] - f0[0]) / h;
      const j21 = (fe[1] - f0[1]) / h;
      const j22 = (fn[1] - f0[1]) / h;
      const det = j11 * j22 - j12 * j21;
      if (Math.abs(det) > 0) {
        const dx = ll[0] - f0[0];
        const dy = ll[1] - f0[1];
        g = [g[0] + (j22 * dx - j12 * dy) / det, g[1] + (-j21 * dx + j11 * dy) / det];
      }
      return g;
    },
    residualMm: dto.residual_mm,
    gridNorthBearing: dto.grid_north_bearing,
    epsg: dto.epsg,
    crsName: dto.crs_name,
  };
}

/** Grid metres per screen pixel at a MapLibre zoom (512 px tiles) near latitude `lat`. */
export function metresPerPixel(zoom: number, lat: number, kind: 'polynomial' | 'local'): number {
  const equator = 40075016.686 / (512 * 2 ** zoom);
  return kind === 'local' ? equator : equator * Math.cos((lat * Math.PI) / 180);
}

/** The "1:N" scale at 96 dpi for a ground resolution in metres per pixel. */
export function scaleDenominator(mPerPx: number): number {
  return mPerPx / (0.0254 / 96);
}

/** A round scale bar length (1, 2, 5 x 10^k metres) that fits `maxPx`. */
export function niceBar(mPerPx: number, maxPx = 120): { metres: number; px: number } {
  const raw = mPerPx * maxPx;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [5, 2, 1].map((k) => k * pow).find((m) => m <= raw) ?? pow;
  return { metres: step, px: step / mPerPx };
}
