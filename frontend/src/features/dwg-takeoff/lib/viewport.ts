/**
 * Viewport math utilities for the DXF canvas viewer.
 *
 * All coordinates follow the convention:
 *   screen = canvas pixel coordinates (top-left origin, Y down)
 *   world  = DXF model-space coordinates (bottom-left origin, Y up)
 */

export interface ViewportState {
  offsetX: number;
  offsetY: number;
  scale: number;
}

export interface Extents {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** Convert screen (canvas) coordinates to DXF world coordinates. */
export function screenToWorld(
  sx: number,
  sy: number,
  vp: ViewportState,
): { x: number; y: number } {
  return {
    x: (sx - vp.offsetX) / vp.scale,
    y: -(sy - vp.offsetY) / vp.scale,
  };
}

/** Convert DXF world coordinates to screen (canvas) coordinates. */
export function worldToScreen(
  wx: number,
  wy: number,
  vp: ViewportState,
): { x: number; y: number } {
  return {
    x: wx * vp.scale + vp.offsetX,
    y: -wy * vp.scale + vp.offsetY,
  };
}

/** Compute a viewport that fits the given extents into the canvas with padding. */
export function zoomToFit(
  extents: Extents,
  canvasWidth: number,
  canvasHeight: number,
  padding = 16,
): ViewportState {
  const dw = extents.maxX - extents.minX || 1;
  const dh = extents.maxY - extents.minY || 1;

  const availW = canvasWidth - padding * 2;
  const availH = canvasHeight - padding * 2;

  const scale = Math.min(availW / dw, availH / dh);

  const cx = (extents.minX + extents.maxX) / 2;
  const cy = (extents.minY + extents.maxY) / 2;

  return {
    offsetX: canvasWidth / 2 - cx * scale,
    offsetY: canvasHeight / 2 + cy * scale,
    scale,
  };
}

/** Apply a zoom factor centered at a screen point. */
export function applyZoom(
  vp: ViewportState,
  factor: number,
  centerX: number,
  centerY: number,
): ViewportState {
  const newScale = vp.scale * factor;
  return {
    scale: newScale,
    offsetX: centerX - (centerX - vp.offsetX) * (newScale / vp.scale),
    offsetY: centerY - (centerY - vp.offsetY) * (newScale / vp.scale),
  };
}

/** Apply a pan delta (in screen pixels). */
export function applyPan(vp: ViewportState, dx: number, dy: number): ViewportState {
  return {
    ...vp,
    offsetX: vp.offsetX + dx,
    offsetY: vp.offsetY + dy,
  };
}
