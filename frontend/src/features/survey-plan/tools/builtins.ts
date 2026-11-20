// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Built-in tools of the plan canvas. Each is plain data plus handlers over a
 * ToolContext; packages add theirs through `extraTools` with the same shape.
 */

import {
  Circle,
  Hand,
  MousePointer2,
  PenLine,
  Pentagon,
  Ruler,
  Spline,
  SquareDashed,
  Triangle,
  Type,
} from 'lucide-react';
import { createFeature } from '../engine/commands';
import { angleAt, arcThrough, pathLength, ringArea } from '../engine/geometry';
import { formatAngle } from '../units/angles';
import { formatArea, formatDistance } from '../units/linear';
import type { PlanConventions } from '../units/conventions';
import type { GridXY, MeasureResult, PlanFeature, PlanTool, ToolContext } from '../types';

function shape(ctx: ToolContext, geometry: PlanFeature['geometry'], properties: Record<string, unknown> = {}): void {
  const f: PlanFeature = { id: ctx.newId('sk'), layer: ctx.activeLayer, geometry, properties, entityType: 'sketch' };
  ctx.commit(createFeature(f));
  ctx.setSelection([f.id]);
}

/** Live measurement of the vertices collected so far (plus the cursor while drawing). */
export function measureOf(toolId: string, pts: readonly GridXY[], conv: PlanConventions): MeasureResult | null {
  if (toolId === 'measure-distance' && pts.length >= 2) {
    const value = pathLength(pts);
    return { kind: 'distance', value, text: formatDistance(value, conv) };
  }
  if (toolId === 'measure-area' && pts.length >= 3) {
    const value = ringArea(pts);
    const perimeter = pathLength(pts, true);
    return { kind: 'area', value, perimeter, text: `${formatArea(value, conv)} / ${formatDistance(perimeter, conv)}` };
  }
  if (toolId === 'measure-angle' && pts.length >= 3) {
    const value = angleAt(pts[0]!, pts[1]!, pts[2]!);
    return { kind: 'angle', value, text: formatAngle(value, conv.angleUnit, conv.angleDecimals) };
  }
  return null;
}

/** Segment labels for the measure preview: length of each leg at its middle. */
export function legLabels(pts: readonly GridXY[], conv: PlanConventions, closed = false): PlanFeature[] {
  const out: PlanFeature[] = [];
  const n = closed ? pts.length : pts.length - 1;
  for (let i = 0; i < n; i++) {
    const a = pts[i]!;
    const b = pts[(i + 1) % pts.length]!;
    const d = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (d <= 0) continue;
    out.push({
      id: `leg-${i}`,
      layer: 'measure',
      geometry: { type: 'LineString', coordinates: [a, b] },
      properties: { text: formatDistance(d, conv) },
    });
  }
  return out;
}

export const SELECT_TOOL = 'select';
export const PAN_TOOL = 'pan';

export const BUILTIN_TOOLS: PlanTool[] = [
  { id: SELECT_TOOL, icon: MousePointer2, labelKey: 'plan.tool.select', defaultLabel: 'Select', shortcut: 'V', group: 'select', collects: 'none' },
  { id: PAN_TOOL, icon: Hand, labelKey: 'plan.tool.pan', defaultLabel: 'Pan', shortcut: 'H', group: 'select', collects: 'none' },
  {
    id: 'point',
    icon: Circle,
    labelKey: 'plan.tool.point',
    defaultLabel: 'Point',
    shortcut: 'P',
    group: 'draw',
    edits: true,
    collects: 'point',
    onFinish: (v, ctx) => {
      if (v[0]) shape(ctx, { type: 'Point', coordinates: v[0] });
    },
  },
  {
    id: 'line',
    icon: PenLine,
    labelKey: 'plan.tool.line',
    defaultLabel: 'Line',
    shortcut: 'L',
    group: 'draw',
    edits: true,
    collects: 'line',
    onFinish: (v, ctx) => {
      if (v.length >= 2) shape(ctx, { type: 'LineString', coordinates: v });
    },
  },
  {
    id: 'polygon',
    icon: Pentagon,
    labelKey: 'plan.tool.polygon',
    defaultLabel: 'Polygon',
    shortcut: 'O',
    group: 'draw',
    edits: true,
    collects: 'ring',
    onFinish: (v, ctx) => {
      if (v.length >= 3) shape(ctx, { type: 'Polygon', coordinates: [[...v, v[0]!]] });
    },
  },
  {
    id: 'arc',
    icon: Spline,
    labelKey: 'plan.tool.arc',
    defaultLabel: 'Arc through 3 points',
    shortcut: 'C',
    group: 'draw',
    edits: true,
    collects: 'arc3',
    onFinish: (v, ctx) => {
      if (v.length === 3) shape(ctx, { type: 'LineString', coordinates: arcThrough(v[0]!, v[1]!, v[2]!) }, { arc: true });
    },
  },
  {
    id: 'text',
    icon: Type,
    labelKey: 'plan.tool.text',
    defaultLabel: 'Text',
    shortcut: 'T',
    group: 'annotate',
    edits: true,
    collects: 'point',
    onFinish: (v, ctx) => {
      if (v[0]) shape(ctx, { type: 'Point', coordinates: v[0] }, { text: ctx.t('plan.tool.text_default', { defaultValue: 'Note' }) });
    },
  },
  {
    id: 'measure-distance',
    icon: Ruler,
    labelKey: 'plan.tool.measure_distance',
    defaultLabel: 'Measure distance',
    shortcut: 'M',
    group: 'measure',
    collects: 'line',
    preview: (ctx) => legLabels(ctx.vertices, ctx.conventions),
    onFinish: (v, ctx) => ctx.setMeasure(measureOf('measure-distance', v, ctx.conventions)),
  },
  {
    id: 'measure-area',
    icon: SquareDashed,
    labelKey: 'plan.tool.measure_area',
    defaultLabel: 'Measure area',
    shortcut: 'A',
    group: 'measure',
    collects: 'ring',
    preview: (ctx) => legLabels(ctx.vertices, ctx.conventions, ctx.vertices.length >= 3),
    onFinish: (v, ctx) => ctx.setMeasure(measureOf('measure-area', v, ctx.conventions)),
  },
  {
    id: 'measure-angle',
    icon: Triangle,
    labelKey: 'plan.tool.measure_angle',
    defaultLabel: 'Measure angle',
    shortcut: 'N',
    group: 'measure',
    collects: 'line',
    onClick: (at, ctx) => {
      const next = [...ctx.vertices, at];
      if (next.length === 3) {
        ctx.setMeasure(measureOf('measure-angle', next, ctx.conventions));
        ctx.setVertices([]);
      } else {
        ctx.setVertices(next);
      }
      return true;
    },
  },
];

/** The ids a screen gets by default: everything, minus editing tools when it is read-only. */
export function defaultToolIds(editable: boolean): string[] {
  return BUILTIN_TOOLS.filter((t) => editable || !t.edits).map((t) => t.id);
}
