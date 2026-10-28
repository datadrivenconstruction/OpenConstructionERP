// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Affine transforms between two revisions of a sheet.
 *
 * Six numbers in the PDF order: x' = a*x + c*y + e, y' = b*x + d*y + f.
 * The stored matrix maps the OLD sheet onto the NEW one in PDF units (top-left
 * origin); the raster pipeline works in pixels of the new sheet, so it scales
 * the translation part with {@link toPixelSpace}.
 */

export type Affine = [number, number, number, number, number, number];
export type Pt = [number, number];

export const IDENTITY: Affine = [1, 0, 0, 1, 0, 0];

export function applyAffine(m: Affine, x: number, y: number): Pt {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
}

export function invertAffine(m: Affine): Affine | null {
  const [a, b, c, d, e, f] = m;
  const det = a * d - b * c;
  if (!Number.isFinite(det) || Math.abs(det) < 1e-12) return null;
  const ia = d / det;
  const ib = -b / det;
  const ic = -c / det;
  const id = a / det;
  return [ia, ib, ic, id, -(ia * e + ic * f), -(ib * e + id * f)];
}

/** `outer ∘ inner`: first `inner`, then `outer`. */
export function composeAffine(outer: Affine, inner: Affine): Affine {
  const [a1, b1, c1, d1, e1, f1] = outer;
  const [a2, b2, c2, d2, e2, f2] = inner;
  return [
    a1 * a2 + c1 * b2,
    b1 * a2 + d1 * b2,
    a1 * c2 + c1 * d2,
    b1 * c2 + d1 * d2,
    a1 * e2 + c1 * f2 + e1,
    b1 * e2 + d1 * f2 + f1,
  ];
}

/** A PDF-unit transform expressed in pixels of a raster rendered at `scale` px per unit. */
export function toPixelSpace(m: Affine, scale: number): Affine {
  return [m[0], m[1], m[2], m[3], m[4] * scale, m[5] * scale];
}

/** A pixel-space transform (raster at `scale` px per unit) expressed in PDF units. */
export function toPdfSpace(m: Affine, scale: number): Affine {
  return [m[0], m[1], m[2], m[3], m[4] / scale, m[5] / scale];
}

export function scaleAndRotation(m: Affine): { scale: number; rotationDeg: number } {
  return { scale: Math.hypot(m[0], m[1]), rotationDeg: (Math.atan2(m[1], m[0]) * 180) / Math.PI };
}

/**
 * The similarity transform taking two old points onto two new points (the
 * manual two-point alignment). `null` when either pair coincides.
 */
export function similarityFromTwoPoints(oldPts: [Pt, Pt], newPts: [Pt, Pt]): Affine | null {
  const [[ox1, oy1], [ox2, oy2]] = oldPts;
  const [[nx1, ny1], [nx2, ny2]] = newPts;
  const vox = ox2 - ox1;
  const voy = oy2 - oy1;
  const vnx = nx2 - nx1;
  const vny = ny2 - ny1;
  const oldLen = Math.hypot(vox, voy);
  const newLen = Math.hypot(vnx, vny);
  if (oldLen < 1e-9 || newLen < 1e-9) return null;
  const s = newLen / oldLen;
  const angle = Math.atan2(vny, vnx) - Math.atan2(voy, vox);
  const a = s * Math.cos(angle);
  const b = s * Math.sin(angle);
  return [a, b, -b, a, nx1 - (a * ox1 - b * oy1), ny1 - (b * ox1 + a * oy1)];
}
