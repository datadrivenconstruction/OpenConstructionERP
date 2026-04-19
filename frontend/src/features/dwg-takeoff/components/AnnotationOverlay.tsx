/**
 * Renders DWG takeoff annotations on the 2D canvas.
 *
 * Called from the DxfViewer's render loop — receives the canvas context
 * and draws text pins, arrows, rectangles, distances, and areas on top
 * of the DXF entities.
 */

import type { DwgAnnotation } from '../api';
import type { ViewportState } from '../lib/viewport';
import { worldToScreen } from '../lib/viewport';
import { formatMeasurement } from '../lib/measurement';

/**
 * Compute the effective stroke thickness for a single annotation.
 * Prefer the new fractional ``thickness`` field; fall back to legacy
 * integer ``line_width``; otherwise default to 2 px to match the
 * renderer's historical behaviour. Selection bumps the width by ~50 %
 * so active annotations are distinguishable without obscuring geometry.
 */
function strokeWidth(ann: DwgAnnotation, isSelected: boolean): number {
  const base =
    typeof ann.thickness === 'number' && ann.thickness > 0
      ? ann.thickness
      : typeof ann.line_width === 'number' && ann.line_width > 0
        ? ann.line_width
        : 2;
  return isSelected ? Math.max(base + 1, base * 1.5) : base;
}

/**
 * Scale a persisted measurement value on the fly so changing the scale
 * tab visibly updates every annotation label without a round trip.
 * ``unit`` distinguishes linear (m) from areal (m²) scaling.
 */
function scaleMeasurement(
  value: number,
  unit: string | null | undefined,
  scale: number,
): number {
  if (!Number.isFinite(scale) || scale <= 0 || scale === 1) return value;
  const normalised = (unit ?? '').trim();
  const isArea =
    normalised === 'm²' ||
    normalised === 'm2' ||
    normalised === '\u00B2' ||
    normalised.includes('²');
  return isArea ? value * scale * scale : value * scale;
}

/** Render all annotations onto the provided canvas context. */
export function renderAnnotations(
  ctx: CanvasRenderingContext2D,
  annotations: DwgAnnotation[],
  vp: ViewportState,
  selectedId?: string | null,
  drawingScale: number = 1,
): void {
  for (const ann of annotations) {
    const isSelected = ann.id === selectedId;
    const color = isSelected ? '#3b82f6' : ann.color;
    const width = strokeWidth(ann, isSelected);

    switch (ann.type) {
      case 'text_pin':
        renderTextPin(ctx, ann, vp, color, isSelected);
        break;
      case 'arrow':
        renderArrow(ctx, ann, vp, color, isSelected, width);
        break;
      case 'rectangle':
        renderRectangle(ctx, ann, vp, color, isSelected, width);
        break;
      case 'distance':
      case 'line':
        renderDistance(ctx, ann, vp, color, isSelected, width, drawingScale);
        break;
      case 'area':
        renderArea(ctx, ann, vp, color, isSelected, width, drawingScale);
        break;
      case 'circle':
        renderCircle(ctx, ann, vp, color, isSelected, width, drawingScale);
        break;
      case 'polyline':
        renderPolyline(ctx, ann, vp, color, isSelected, width, drawingScale);
        break;
    }
  }
}

function renderCircle(
  ctx: CanvasRenderingContext2D,
  ann: DwgAnnotation,
  vp: ViewportState,
  color: string,
  _isSelected: boolean,
  width = 2,
  drawingScale = 1,
): void {
  if (ann.points.length < 2) return;
  const center = worldToScreen(ann.points[0]!.x, ann.points[0]!.y, vp);
  const edge = worldToScreen(ann.points[1]!.x, ann.points[1]!.y, vp);
  const dx = edge.x - center.x;
  const dy = edge.y - center.y;
  const radius = Math.sqrt(dx * dx + dy * dy);

  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = `${color}1f`;
  ctx.fill();

  // Area label at centre when measurement is available.
  if (ann.measurement_value != null) {
    const scaled = scaleMeasurement(
      ann.measurement_value,
      ann.measurement_unit,
      drawingScale,
    );
    const label = formatMeasurement(scaled, ann.measurement_unit ?? 'm\u00B2');
    ctx.font = '600 11px ui-monospace, monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = 'rgba(0,0,0,0.75)';
    const tw = ctx.measureText(label).width + 10;
    const th = 18;
    ctx.fillRect(center.x - tw / 2, center.y - th / 2, tw, th);
    ctx.fillStyle = '#fff';
    ctx.fillText(label, center.x, center.y + 1);
  }
}

function renderPolyline(
  ctx: CanvasRenderingContext2D,
  ann: DwgAnnotation,
  vp: ViewportState,
  color: string,
  _isSelected: boolean,
  width = 2,
  drawingScale = 1,
): void {
  if (ann.points.length < 2) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  const first = worldToScreen(ann.points[0]!.x, ann.points[0]!.y, vp);
  ctx.moveTo(first.x, first.y);
  for (let i = 1; i < ann.points.length; i++) {
    const p = worldToScreen(ann.points[i]!.x, ann.points[i]!.y, vp);
    ctx.lineTo(p.x, p.y);
  }
  ctx.stroke();

  // Total length label at the midpoint of the last segment.
  if (ann.measurement_value != null && ann.points.length >= 2) {
    const pA = worldToScreen(
      ann.points[ann.points.length - 2]!.x,
      ann.points[ann.points.length - 2]!.y,
      vp,
    );
    const pB = worldToScreen(
      ann.points[ann.points.length - 1]!.x,
      ann.points[ann.points.length - 1]!.y,
      vp,
    );
    const mx = (pA.x + pB.x) / 2;
    const my = (pA.y + pB.y) / 2;
    const scaled = scaleMeasurement(
      ann.measurement_value,
      ann.measurement_unit,
      drawingScale,
    );
    const label = formatMeasurement(scaled, ann.measurement_unit ?? 'm');
    ctx.font = '600 11px ui-monospace, monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = 'rgba(0,0,0,0.75)';
    const tw = ctx.measureText(label).width + 10;
    const th = 18;
    ctx.fillRect(mx - tw / 2, my - 20 - th / 2, tw, th);
    ctx.fillStyle = '#fff';
    ctx.fillText(label, mx, my - 19);
  }
}

function renderTextPin(
  ctx: CanvasRenderingContext2D,
  ann: DwgAnnotation,
  vp: ViewportState,
  color: string,
  isSelected: boolean,
): void {
  if (ann.points.length < 1) return;
  const pt0 = ann.points[0]!;
  const pos = worldToScreen(pt0.x, pt0.y, vp);

  // Read custom font size from metadata (default 14px — bumped so blank
  // pins show a clearly visible marker).
  const customFontSize =
    ann.metadata && typeof ann.metadata.font_size === 'number'
      ? ann.metadata.font_size
      : 14;

  // Use the annotation's own color (which the popup sets), falling back to the
  // selection highlight / default color passed in.
  const pinColor = isSelected ? color : ann.color || color;

  // Circle marker — min 6px so a blank pin is still obviously visible,
  // and a white halo so dark-coloured pins read against the dark canvas.
  const markerRadius = Math.max(6, customFontSize * 0.5);
  ctx.beginPath();
  ctx.arc(
    pos.x,
    pos.y,
    isSelected ? markerRadius + 3 : markerRadius + 1.5,
    0,
    Math.PI * 2,
  );
  ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
  ctx.fill();
  ctx.beginPath();
  ctx.arc(pos.x, pos.y, isSelected ? markerRadius + 1 : markerRadius, 0, Math.PI * 2);
  ctx.fillStyle = pinColor;
  ctx.globalAlpha = 0.95;
  ctx.fill();
  ctx.globalAlpha = 1;

  // Label
  if (ann.text) {
    ctx.font = `600 ${customFontSize}px Inter, system-ui, sans-serif`;
    ctx.fillStyle = pinColor;
    ctx.textBaseline = 'bottom';

    // Background pill for readability
    const textMetrics = ctx.measureText(ann.text);
    const pillPad = 4;
    const pillW = textMetrics.width + pillPad * 2;
    const pillH = customFontSize + pillPad;
    const pillX = pos.x + markerRadius + 6;
    const pillY = pos.y - customFontSize - pillPad / 2;

    ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
    ctx.beginPath();
    const r = 3;
    ctx.moveTo(pillX + r, pillY);
    ctx.lineTo(pillX + pillW - r, pillY);
    ctx.arcTo(pillX + pillW, pillY, pillX + pillW, pillY + r, r);
    ctx.lineTo(pillX + pillW, pillY + pillH - r);
    ctx.arcTo(pillX + pillW, pillY + pillH, pillX + pillW - r, pillY + pillH, r);
    ctx.lineTo(pillX + r, pillY + pillH);
    ctx.arcTo(pillX, pillY + pillH, pillX, pillY + pillH - r, r);
    ctx.lineTo(pillX, pillY + r);
    ctx.arcTo(pillX, pillY, pillX + r, pillY, r);
    ctx.closePath();
    ctx.fill();

    ctx.fillStyle = pinColor;
    ctx.fillText(ann.text, pillX + pillPad, pillY + pillH - pillPad / 2);
  }

  if (isSelected) {
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, markerRadius + 5, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function renderArrow(
  ctx: CanvasRenderingContext2D,
  ann: DwgAnnotation,
  vp: ViewportState,
  color: string,
  _isSelected: boolean,
  width = 2,
): void {
  if (ann.points.length < 2) return;
  const aPt0 = ann.points[0]!;
  const aPt1 = ann.points[1]!;
  const from = worldToScreen(aPt0.x, aPt0.y, vp);
  const to = worldToScreen(aPt1.x, aPt1.y, vp);

  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(from.x, from.y);
  ctx.lineTo(to.x, to.y);
  ctx.stroke();

  // Arrowhead
  const angle = Math.atan2(to.y - from.y, to.x - from.x);
  const headLen = 12;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(to.x, to.y);
  ctx.lineTo(to.x - headLen * Math.cos(angle - 0.4), to.y - headLen * Math.sin(angle - 0.4));
  ctx.lineTo(to.x - headLen * Math.cos(angle + 0.4), to.y - headLen * Math.sin(angle + 0.4));
  ctx.closePath();
  ctx.fill();
}

function renderRectangle(
  ctx: CanvasRenderingContext2D,
  ann: DwgAnnotation,
  vp: ViewportState,
  color: string,
  isSelected: boolean,
  width = 1.5,
): void {
  if (ann.points.length < 2) return;
  const rPt0 = ann.points[0]!;
  const rPt1 = ann.points[1]!;
  const p1 = worldToScreen(rPt0.x, rPt0.y, vp);
  const p2 = worldToScreen(rPt1.x, rPt1.y, vp);

  const x = Math.min(p1.x, p2.x);
  const y = Math.min(p1.y, p2.y);
  const w = Math.abs(p2.x - p1.x);
  const h = Math.abs(p2.y - p1.y);

  ctx.fillStyle = color;
  ctx.globalAlpha = 0.12;
  ctx.fillRect(x, y, w, h);
  ctx.globalAlpha = 1;

  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.strokeRect(x, y, w, h);

  // Drag handles when selected
  if (isSelected) {
    for (const p of [p1, p2]) {
      ctx.fillStyle = '#3b82f6';
      ctx.fillRect(p.x - 4, p.y - 4, 8, 8);
    }
  }
}

function renderDistance(
  ctx: CanvasRenderingContext2D,
  ann: DwgAnnotation,
  vp: ViewportState,
  color: string,
  _isSelected: boolean,
  width = 1.5,
  drawingScale = 1,
): void {
  if (ann.points.length < 2) return;
  const dPt0 = ann.points[0]!;
  const dPt1 = ann.points[1]!;
  const p1 = worldToScreen(dPt0.x, dPt0.y, vp);
  const p2 = worldToScreen(dPt1.x, dPt1.y, vp);

  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  // Dashed only for the measurement 'distance' tool so user-drawn 'line'
  // primitives stroke solid (more natural for markup).
  if (ann.type === 'distance') {
    ctx.setLineDash([6, 4]);
  }
  ctx.beginPath();
  ctx.moveTo(p1.x, p1.y);
  ctx.lineTo(p2.x, p2.y);
  ctx.stroke();
  ctx.setLineDash([]);

  // Dimension text
  const label =
    ann.measurement_value != null
      ? formatMeasurement(
          scaleMeasurement(ann.measurement_value, ann.measurement_unit, drawingScale),
          ann.measurement_unit ?? 'm',
        )
      : ann.text ?? '';
  if (label) {
    const mx = (p1.x + p2.x) / 2;
    const my = (p1.y + p2.y) / 2;
    ctx.font = 'bold 11px Inter, system-ui, sans-serif';
    ctx.fillStyle = color;
    ctx.textBaseline = 'bottom';
    ctx.textAlign = 'center';
    ctx.fillText(label, mx, my - 4);
    ctx.textAlign = 'start';
  }

  // End markers
  for (const p of [p1, p2]) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
    ctx.fill();
  }
}

function renderArea(
  ctx: CanvasRenderingContext2D,
  ann: DwgAnnotation,
  vp: ViewportState,
  color: string,
  _isSelected: boolean,
  width = 1.5,
  drawingScale = 1,
): void {
  if (ann.points.length < 3) return;
  const screenPts = ann.points.map((p) => worldToScreen(p.x, p.y, vp));
  const first = screenPts[0]!;

  // Fill
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.15;
  ctx.beginPath();
  ctx.moveTo(first.x, first.y);
  for (let i = 1; i < screenPts.length; i++) {
    ctx.lineTo(screenPts[i]!.x, screenPts[i]!.y);
  }
  ctx.closePath();
  ctx.fill();
  ctx.globalAlpha = 1;

  // Outline
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(first.x, first.y);
  for (let i = 1; i < screenPts.length; i++) {
    ctx.lineTo(screenPts[i]!.x, screenPts[i]!.y);
  }
  ctx.closePath();
  ctx.stroke();

  // Area text at centroid
  const cx = screenPts.reduce((s, p) => s + p.x, 0) / screenPts.length;
  const cy = screenPts.reduce((s, p) => s + p.y, 0) / screenPts.length;
  const label =
    ann.measurement_value != null
      ? formatMeasurement(
          scaleMeasurement(ann.measurement_value, ann.measurement_unit, drawingScale),
          ann.measurement_unit ?? 'm\u00B2',
        )
      : ann.text ?? '';
  if (label) {
    ctx.font = 'bold 11px Inter, system-ui, sans-serif';
    ctx.fillStyle = color;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    ctx.fillText(label, cx, cy);
    ctx.textAlign = 'start';
  }
}
