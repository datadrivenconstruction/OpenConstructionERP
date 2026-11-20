// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Hillshade and height tint of a TIN, rasterised on the client from the mesh
 * (surfaces_volumes `GET surfaces/{id}/mesh`). Lambert shading with the light
 * from azimuth 315, altitude 45, the cartographic convention, so slopes facing
 * north-west are lit. Cells outside the TIN stay transparent.
 */

export interface Mesh {
  /** [e, n, z] per vertex. */
  vertices: Array<[number, number, number]>;
  /** Vertex indices per triangle. */
  faces: Array<[number, number, number]>;
}

export interface Raster {
  originE: number;
  originN: number;
  cell: number;
  nx: number;
  ny: number;
  /** Row-major from the north row down (image order); NaN outside the surface. */
  z: Float64Array;
}

/** Height of the mesh on a grid of cell centres; the cell grows so the raster stays within maxCells. */
export function rasterise(mesh: Mesh, maxCells = 250_000): Raster | null {
  const v = mesh.vertices;
  if (!v.length || !mesh.faces.length) return null;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [e, n] of v) {
    x0 = Math.min(x0, e); y0 = Math.min(y0, n); x1 = Math.max(x1, e); y1 = Math.max(y1, n);
  }
  const w = Math.max(x1 - x0, 1e-6), h = Math.max(y1 - y0, 1e-6);
  const cell = Math.max(Math.sqrt((w * h) / maxCells), Math.max(w, h) / 2000);
  const nx = Math.max(1, Math.ceil(w / cell)), ny = Math.max(1, Math.ceil(h / cell));
  const z = new Float64Array(nx * ny).fill(NaN);
  for (const [ia, ib, ic] of mesh.faces) {
    const a = v[ia]!, b = v[ib]!, c = v[ic]!;
    const det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]);
    if (Math.abs(det) < 1e-12) continue;
    const cx0 = Math.max(0, Math.floor((Math.min(a[0], b[0], c[0]) - x0) / cell - 0.5));
    const cx1 = Math.min(nx - 1, Math.ceil((Math.max(a[0], b[0], c[0]) - x0) / cell - 0.5));
    const cy0 = Math.max(0, Math.floor((Math.min(a[1], b[1], c[1]) - y0) / cell - 0.5));
    const cy1 = Math.min(ny - 1, Math.ceil((Math.max(a[1], b[1], c[1]) - y0) / cell - 0.5));
    for (let j = cy0; j <= cy1; j++) {
      const pn = y0 + (j + 0.5) * cell;
      for (let i = cx0; i <= cx1; i++) {
        const pe = x0 + (i + 0.5) * cell;
        const l1 = ((b[1] - c[1]) * (pe - c[0]) + (c[0] - b[0]) * (pn - c[1])) / det;
        const l2 = ((c[1] - a[1]) * (pe - c[0]) + (a[0] - c[0]) * (pn - c[1])) / det;
        const l3 = 1 - l1 - l2;
        if (l1 < -1e-9 || l2 < -1e-9 || l3 < -1e-9) continue;
        z[(ny - 1 - j) * nx + i] = l1 * a[2] + l2 * b[2] + l3 * c[2];
      }
    }
  }
  return { originE: x0, originN: y0, cell, nx, ny, z };
}

/**
 * Lambert shade 0..1 per cell: cos of the angle between the surface normal and
 * the light. Edge cells use one-sided differences; NaN where there is no surface.
 */
export function hillshade(r: Raster, azimuthDeg = 315, altitudeDeg = 45, zFactor = 1): Float64Array {
  const out = new Float64Array(r.nx * r.ny).fill(NaN);
  const az = (azimuthDeg * Math.PI) / 180, alt = (altitudeDeg * Math.PI) / 180;
  // Light direction as a unit vector in (east, north, up).
  const lx = Math.sin(az) * Math.cos(alt), ly = Math.cos(az) * Math.cos(alt), lz = Math.sin(alt);
  const at = (i: number, row: number) => (i < 0 || row < 0 || i >= r.nx || row >= r.ny ? NaN : r.z[row * r.nx + i]!);
  for (let row = 0; row < r.ny; row++) {
    for (let i = 0; i < r.nx; i++) {
      const c = at(i, row);
      if (!Number.isFinite(c)) continue;
      const w = at(i - 1, row), e = at(i + 1, row), nth = at(i, row - 1), s = at(i, row + 1);
      const dzdx = Number.isFinite(e) && Number.isFinite(w) ? (e - w) / (2 * r.cell) : Number.isFinite(e) ? (e - c) / r.cell : Number.isFinite(w) ? (c - w) / r.cell : 0;
      const dzdy = Number.isFinite(nth) && Number.isFinite(s) ? (nth - s) / (2 * r.cell) : Number.isFinite(nth) ? (nth - c) / r.cell : Number.isFinite(s) ? (c - s) / r.cell : 0;
      const nx = -dzdx * zFactor, ny = -dzdy * zFactor, nz = 1;
      const len = Math.hypot(nx, ny, nz);
      out[row * r.nx + i] = Math.max(0, (nx * lx + ny * ly + nz * lz) / len);
    }
  }
  return out;
}

/** Elevation tint stops (low to high), muted so contours and labels stay readable. */
const TINT: Array<[number, number, number]> = [
  [86, 140, 104],
  [168, 186, 120],
  [222, 206, 150],
  [196, 156, 112],
  [170, 140, 128],
];

function tint(t: number): [number, number, number] {
  const x = Math.min(Math.max(t, 0), 1) * (TINT.length - 1);
  const i = Math.min(Math.floor(x), TINT.length - 2);
  const f = x - i;
  const a = TINT[i]!, b = TINT[i + 1]!;
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

/** RGBA pixels (image order) of the tinted hillshade; ready for an ImageData or a jsPDF image. */
export function shadedRelief(r: Raster, opts: { tint?: boolean; azimuthDeg?: number; altitudeDeg?: number } = {}): Uint8ClampedArray {
  const shade = hillshade(r, opts.azimuthDeg ?? 315, opts.altitudeDeg ?? 45);
  let zMin = Infinity, zMax = -Infinity;
  for (const z of r.z) if (Number.isFinite(z)) { zMin = Math.min(zMin, z); zMax = Math.max(zMax, z); }
  const span = zMax - zMin || 1;
  const px = new Uint8ClampedArray(r.nx * r.ny * 4);
  for (let k = 0; k < r.z.length; k++) {
    const s = shade[k]!;
    if (!Number.isFinite(s)) continue;
    const base = opts.tint === false ? [200, 200, 200] : tint((r.z[k]! - zMin) / span);
    // Keep a floor of ambient light so the shadowed side never turns black.
    const light = 0.35 + 0.65 * s;
    px[k * 4] = base[0]! * light;
    px[k * 4 + 1] = base[1]! * light;
    px[k * 4 + 2] = base[2]! * light;
    px[k * 4 + 3] = 255;
  }
  return px;
}
