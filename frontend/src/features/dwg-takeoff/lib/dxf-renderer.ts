/**
 * Canvas2D rendering functions for DXF entities.
 *
 * Each entity type is rendered via a dedicated function that receives the
 * 2D context, the entity data, and the current viewport state.
 */

import type { DxfEntity } from '../api';
import type { ViewportState } from './viewport';
import { worldToScreen } from './viewport';

/* ── AutoCAD Color Index → CSS hex ─────────────────────────────────────── */

const ACI_TABLE: Record<number, string> = {
  0: '#000000', // ByBlock
  1: '#FF0000', // Red
  2: '#FFFF00', // Yellow
  3: '#00FF00', // Green
  4: '#00FFFF', // Cyan
  5: '#0000FF', // Blue
  6: '#FF00FF', // Magenta
  7: '#FFFFFF', // White / Black (display-dependent)
  8: '#808080', // Dark grey
  9: '#C0C0C0', // Light grey
};

/** Convert an AutoCAD Color Index to a CSS hex color string. */
export function aciToHex(colorIndex: number): string {
  return ACI_TABLE[colorIndex] ?? '#CCCCCC';
}

/* ── Entity rendering ──────────────────────────────────────────────────── */

export function renderEntities(
  ctx: CanvasRenderingContext2D,
  entities: DxfEntity[],
  vp: ViewportState,
  visibleLayers: Set<string>,
  selectedId?: string | null,
): void {
  for (const entity of entities) {
    if (!visibleLayers.has(entity.layer)) continue;

    ctx.strokeStyle = aciToHex(entity.color);
    ctx.fillStyle = aciToHex(entity.color);
    ctx.lineWidth = 1;

    const isSelected = entity.id === selectedId;
    if (isSelected) {
      ctx.strokeStyle = '#3b82f6';
      ctx.fillStyle = '#3b82f6';
      ctx.lineWidth = 2.5;
    }

    switch (entity.type) {
      case 'LINE':
        renderLine(ctx, entity, vp);
        break;
      case 'LWPOLYLINE':
        renderPolyline(ctx, entity, vp);
        break;
      case 'ARC':
        renderArc(ctx, entity, vp);
        break;
      case 'CIRCLE':
        renderCircle(ctx, entity, vp);
        break;
      case 'TEXT':
        renderText(ctx, entity, vp);
        break;
      case 'POINT':
        renderPoint(ctx, entity, vp);
        break;
      case 'INSERT':
        renderInsert(ctx, entity, vp);
        break;
    }
  }
}

export function renderLine(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  if (!entity.start || !entity.end) return;
  const s = worldToScreen(entity.start.x, entity.start.y, vp);
  const e = worldToScreen(entity.end.x, entity.end.y, vp);
  ctx.beginPath();
  ctx.moveTo(s.x, s.y);
  ctx.lineTo(e.x, e.y);
  ctx.stroke();
}

export function renderPolyline(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  if (!entity.vertices || entity.vertices.length < 2) return;
  ctx.beginPath();
  const v0 = entity.vertices[0]!;
  const first = worldToScreen(v0.x, v0.y, vp);
  ctx.moveTo(first.x, first.y);
  for (let i = 1; i < entity.vertices.length; i++) {
    const v = entity.vertices[i]!;
    const p = worldToScreen(v.x, v.y, vp);
    ctx.lineTo(p.x, p.y);
  }
  if (entity.closed) {
    ctx.closePath();
  }
  ctx.stroke();
}

export function renderArc(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  if (!entity.start || entity.radius == null) return;
  const center = worldToScreen(entity.start.x, entity.start.y, vp);
  const r = entity.radius * vp.scale;
  const startAngle = ((entity.start_angle ?? 0) * Math.PI) / 180;
  const endAngle = ((entity.end_angle ?? 360) * Math.PI) / 180;
  ctx.beginPath();
  // DXF arcs are CCW; with Y-axis flipped in worldToScreen, negate angles and sweep CW
  ctx.arc(center.x, center.y, r, -startAngle, -endAngle, false);
  ctx.stroke();
}

export function renderCircle(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  if (!entity.start || entity.radius == null) return;
  const center = worldToScreen(entity.start.x, entity.start.y, vp);
  const r = entity.radius * vp.scale;
  ctx.beginPath();
  ctx.arc(center.x, center.y, r, 0, Math.PI * 2);
  ctx.stroke();
}

export function renderText(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  if (!entity.start || !entity.text) return;
  const pos = worldToScreen(entity.start.x, entity.start.y, vp);
  const fontSize = Math.max(8, Math.min(72, (entity.height ?? 2.5) * vp.scale));
  ctx.font = `${fontSize}px monospace`;
  ctx.textBaseline = 'bottom';
  ctx.fillText(entity.text, pos.x, pos.y);
}

function renderPoint(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  if (!entity.start) return;
  const pos = worldToScreen(entity.start.x, entity.start.y, vp);
  ctx.beginPath();
  ctx.arc(pos.x, pos.y, 2, 0, Math.PI * 2);
  ctx.fill();
}

function renderInsert(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  if (!entity.start) return;
  const pos = worldToScreen(entity.start.x, entity.start.y, vp);
  // Render block insert as a small diamond marker
  const s = 5;
  ctx.beginPath();
  ctx.moveTo(pos.x, pos.y - s);
  ctx.lineTo(pos.x + s, pos.y);
  ctx.lineTo(pos.x, pos.y + s);
  ctx.lineTo(pos.x - s, pos.y);
  ctx.closePath();
  ctx.stroke();
  if (entity.block_name) {
    ctx.font = '9px monospace';
    ctx.textBaseline = 'top';
    ctx.fillText(entity.block_name, pos.x + s + 2, pos.y - s);
  }
}
