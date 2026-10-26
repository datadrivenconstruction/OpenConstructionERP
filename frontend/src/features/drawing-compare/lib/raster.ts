// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Ink masks of a rendered sheet and the pixel diff between two of them.
 *
 * Pure array code (no DOM), so it runs the same in the browser and in tests.
 * A sheet is reduced to "ink" (dark enough to be a line or a letter) versus
 * paper; two masks of the same frame are then compared with a tolerance so
 * antialiasing and a pixel or two of misregistration do not read as change.
 */

import { applyAffine, invertAffine, type Affine } from './transform';

export interface InkMask {
  width: number;
  height: number;
  /** 1 = ink, 0 = paper; row-major. */
  data: Uint8Array;
}

/** Pixel classes of a diff, also the palette index of the overlay. */
export const CODE_NONE = 0;
export const CODE_SAME = 1;
export const CODE_REMOVED = 2;
export const CODE_ADDED = 3;

export interface PixelDiff {
  width: number;
  height: number;
  codes: Uint8Array;
  added: number;
  removed: number;
  same: number;
}

/**
 * Ink mask of RGBA pixels. A transparent pixel is paper (pdf.js leaves the
 * background transparent unless asked to paint it); otherwise luminance below
 * `threshold` (0-255) is ink.
 */
export function inkMaskFromRgba(rgba: Uint8ClampedArray, width: number, height: number, threshold = 200): InkMask {
  const data = new Uint8Array(width * height);
  for (let i = 0, p = 0; i < data.length; i++, p += 4) {
    const alpha = rgba[p + 3]! / 255;
    if (alpha < 0.05) continue;
    // Composite on white so a half-transparent grey line still reads as grey.
    const r = 255 - alpha * (255 - rgba[p]!);
    const g = 255 - alpha * (255 - rgba[p + 1]!);
    const b = 255 - alpha * (255 - rgba[p + 2]!);
    if (0.299 * r + 0.587 * g + 0.114 * b < threshold) data[i] = 1;
  }
  return { width, height, data };
}

/** Count of ink pixels. */
export function inkCount(mask: InkMask): number {
  let n = 0;
  for (let i = 0; i < mask.data.length; i++) n += mask.data[i]!;
  return n;
}

/**
 * Resample `src` into a `width` x `height` frame through `m` (src pixel ->
 * frame pixel), nearest neighbour. Pixels that fall outside `src` are paper.
 */
export function warpMask(src: InkMask, m: Affine, width: number, height: number): InkMask {
  const data = new Uint8Array(width * height);
  const inv = invertAffine(m);
  if (!inv) return { width, height, data };
  const [a, b] = inv;
  for (let y = 0; y < height; y++) {
    // Walk a row incrementally: one transform per row, two adds per pixel.
    let [sx, sy] = applyAffine(inv, 0.5, y + 0.5);
    for (let x = 0; x < width; x++) {
      const ix = Math.floor(sx);
      const iy = Math.floor(sy);
      if (ix >= 0 && iy >= 0 && ix < src.width && iy < src.height && src.data[iy * src.width + ix]) {
        data[y * width + x] = 1;
      }
      sx += a;
      sy += b;
    }
  }
  return { width, height, data };
}

/** Grow ink by `radius` pixels (square neighbourhood), as two 1-D passes. */
export function dilate(mask: InkMask, radius: number): Uint8Array {
  const { width: w, height: h, data } = mask;
  if (radius <= 0) return data.slice();
  const tmp = new Uint8Array(w * h);
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const row = y * w;
    let lastInk = -Infinity;
    // Forward pass remembers the last ink to the left, backward pass the next to the right.
    for (let x = 0; x < w; x++) {
      if (data[row + x]) lastInk = x;
      if (x - lastInk <= radius) tmp[row + x] = 1;
    }
    let nextInk = Infinity;
    for (let x = w - 1; x >= 0; x--) {
      if (data[row + x]) nextInk = x;
      if (nextInk - x <= radius) tmp[row + x] = 1;
    }
  }
  for (let x = 0; x < w; x++) {
    let lastInk = -Infinity;
    for (let y = 0; y < h; y++) {
      if (tmp[y * w + x]) lastInk = y;
      if (y - lastInk <= radius) out[y * w + x] = 1;
    }
    let nextInk = Infinity;
    for (let y = h - 1; y >= 0; y--) {
      if (tmp[y * w + x]) nextInk = y;
      if (nextInk - y <= radius) out[y * w + x] = 1;
    }
  }
  return out;
}

/**
 * Classify every pixel of two aligned masks of the same frame.
 *
 * New ink with old ink within `tolerance` px is unchanged; new ink with none
 * is added; old ink with no new ink within `tolerance` is removed.
 */
export function diffMasks(oldMask: InkMask, newMask: InkMask, tolerance: number): PixelDiff {
  if (oldMask.width !== newMask.width || oldMask.height !== newMask.height) {
    throw new Error('masks must share a frame');
  }
  const { width, height } = newMask;
  const near = Math.max(0, Math.round(tolerance));
  const oldNear = dilate(oldMask, near);
  const newNear = dilate(newMask, near);
  const codes = new Uint8Array(width * height);
  let added = 0;
  let removed = 0;
  let same = 0;
  for (let i = 0; i < codes.length; i++) {
    const n = newMask.data[i];
    const o = oldMask.data[i];
    if (n) {
      if (oldNear[i]) {
        codes[i] = CODE_SAME;
        same++;
      } else {
        codes[i] = CODE_ADDED;
        added++;
      }
    } else if (o) {
      if (newNear[i]) {
        codes[i] = CODE_SAME;
        same++;
      } else {
        codes[i] = CODE_REMOVED;
        removed++;
      }
    }
  }
  return { width, height, codes, added, removed, same };
}

/** Overlay colours: unchanged grey, old (removed) red, new (added) blue, paper white. */
export const OVERLAY_RGB: Record<number, [number, number, number]> = {
  [CODE_NONE]: [255, 255, 255],
  [CODE_SAME]: [156, 163, 175],
  [CODE_REMOVED]: [220, 38, 38],
  [CODE_ADDED]: [37, 99, 235],
};

/** RGBA pixels of the overlay image for a diff. */
export function overlayRgba(diff: PixelDiff): Uint8ClampedArray {
  const out = new Uint8ClampedArray(diff.codes.length * 4);
  for (let i = 0, p = 0; i < diff.codes.length; i++, p += 4) {
    const rgb = OVERLAY_RGB[diff.codes[i]!] ?? OVERLAY_RGB[CODE_NONE]!;
    out[p] = rgb[0];
    out[p + 1] = rgb[1];
    out[p + 2] = rgb[2];
    out[p + 3] = 255;
  }
  return out;
}
