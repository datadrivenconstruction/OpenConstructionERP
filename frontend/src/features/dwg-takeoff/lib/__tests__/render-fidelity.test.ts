// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { renderEntities, renderText, lineWeightPx, dimensionLabel } from '../dxf-renderer';
import { groupBlockDefinitions, expandBlockReferences } from '../blocks';
import { textBoxForEntity } from '../dwg-textsearch';
import type { ViewportState } from '../viewport';
import type { DxfEntity } from '../../api';

type Call = { op: string; args: unknown[]; lineWidth: number; textAlign: string; textBaseline: string };

function stubCtx(): { ctx: CanvasRenderingContext2D; calls: Call[] } {
  const calls: Call[] = [];
  const state = { lineWidth: 1, textAlign: 'start', textBaseline: 'alphabetic' };
  const rec =
    (op: string) =>
    (...args: unknown[]): void => {
      calls.push({ op, args, ...state });
    };
  const ctx = {
    font: '',
    fillStyle: '',
    strokeStyle: '',
    globalAlpha: 1,
    shadowColor: '',
    shadowBlur: 0,
    get lineWidth() {
      return state.lineWidth;
    },
    set lineWidth(v: number) {
      state.lineWidth = v;
    },
    get textAlign() {
      return state.textAlign;
    },
    set textAlign(v: string) {
      state.textAlign = v;
    },
    get textBaseline() {
      return state.textBaseline;
    },
    set textBaseline(v: string) {
      state.textBaseline = v;
    },
    save: rec('save'),
    restore: rec('restore'),
    beginPath: rec('beginPath'),
    closePath: rec('closePath'),
    moveTo: rec('moveTo'),
    lineTo: rec('lineTo'),
    stroke: rec('stroke'),
    fill: rec('fill'),
    translate: rec('translate'),
    rotate: rec('rotate'),
    fillText: rec('fillText'),
    arc: rec('arc'),
    ellipse: rec('ellipse'),
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls };
}

const vp = (scale: number): ViewportState => ({ offsetX: 0, offsetY: 0, scale });
const layers = new Set(['A']);
const line = (id: string, lineweight?: number, x = 0): DxfEntity => ({
  id,
  type: 'LINE',
  layer: 'A',
  color: 7,
  start: { x, y: 0 },
  end: { x: x + 1, y: 0 },
  lineweight,
});

describe('lineWeightPx', () => {
  it('draws the default weight and thin weights as one pixel at the fitted zoom', () => {
    expect(lineWeightPx(undefined, 1, 1, true)).toBe(1);
    expect(lineWeightPx(0.13, 1, 1, true)).toBe(1);
  });

  it('maps millimetres to screen pixels at 96 dpi', () => {
    expect(lineWeightPx(0.5, 1, 1, true)).toBeCloseTo(2, 0);
    expect(lineWeightPx(1.0, 1, 1, true)).toBeCloseTo(3.75, 1);
  });

  it('grows when zoomed in and shrinks back when zoomed out, within bounds', () => {
    const fitted = lineWeightPx(0.7, 1, 1, true);
    expect(lineWeightPx(0.7, 4, 1, true)).toBeGreaterThan(fitted);
    expect(lineWeightPx(0.7, 0.01, 1, true)).toBeGreaterThanOrEqual(1);
    expect(lineWeightPx(2.11, 1000, 1, true)).toBeLessThanOrEqual(16);
  });

  it('is one pixel for everything when weights are hidden', () => {
    expect(lineWeightPx(2.11, 4, 1, false)).toBe(1);
  });
});

describe('line weights in renderEntities', () => {
  it('strokes heavier lines wider and breaks the batch between weights', () => {
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [line('a', 0.18, 0), line('b', 0.7, 5)], vp(1), layers, null, 800, 600);
    const strokes = calls.filter((c) => c.op === 'stroke');
    expect(strokes).toHaveLength(2);
    expect(strokes[0]!.lineWidth).toBe(1);
    expect(strokes[1]!.lineWidth).toBeGreaterThan(2);
  });

  it('draws one batch at one pixel when the reader hides weights', () => {
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [line('a', 0.18, 0), line('b', 0.7, 5)], vp(1), layers, null, 800, 600, undefined, undefined, {
      visible: false,
      refScale: 1,
    });
    const strokes = calls.filter((c) => c.op === 'stroke');
    expect(strokes).toHaveLength(1);
    expect(strokes[0]!.lineWidth).toBe(1);
  });

  it('gives a ByBlock member the weight of the insert that places it', () => {
    const member: DxfEntity = { ...line('m'), block: 'DOOR' };
    const ins: DxfEntity = {
      id: 'i',
      type: 'INSERT',
      layer: 'A',
      color: 7,
      start: { x: 0, y: 0 },
      block_name: 'DOOR',
      lineweight: 0.5,
    };
    const [placed] = expandBlockReferences([ins], groupBlockDefinitions([member, ins]));
    expect(placed!.lineweight).toBe(0.5);
  });
});

describe('filled outlines and hatch islands', () => {
  it('fills a SOLID outline instead of stroking it', () => {
    const { ctx, calls } = stubCtx();
    const solid: DxfEntity = {
      id: 's',
      type: 'LWPOLYLINE',
      layer: 'A',
      color: 7,
      vertices: [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
        { x: 0, y: 1 },
      ],
      closed: true,
      filled: true,
    };
    renderEntities(ctx, [solid], vp(10), layers, null, 800, 600);
    expect(calls.some((c) => c.op === 'fill')).toBe(true);
  });

  it('cuts holes out of a hatch with the even-odd rule', () => {
    const { ctx, calls } = stubCtx();
    const sq = (o: number, s: number) => [
      { x: o, y: o },
      { x: o + s, y: o },
      { x: o + s, y: o + s },
      { x: o, y: o + s },
    ];
    const hatch: DxfEntity = {
      id: 'h',
      type: 'HATCH',
      layer: 'A',
      color: 7,
      vertices: sq(0, 10),
      holes: [sq(4, 2)],
      extra_loops: [sq(20, 5)],
      is_solid: true,
      pattern_name: 'SOLID',
    };
    renderEntities(ctx, [hatch], vp(10), layers, null, 800, 600);
    const fill = calls.find((c) => c.op === 'fill');
    expect(fill?.args).toEqual(['evenodd']);
    expect(calls.filter((c) => c.op === 'moveTo')).toHaveLength(3);
  });
});

describe('dimensionLabel', () => {
  it('prints the measured value', () => {
    expect(dimensionLabel(3000, '')).toBe('3000');
    expect(dimensionLabel(1234.567, '<>')).toBe('1234.57');
  });
  it('substitutes the value into an override', () => {
    expect(dimensionLabel(3000, '<> TYP')).toBe('3000 TYP');
  });
  it('keeps a plain override and strips MTEXT codes from it', () => {
    expect(dimensionLabel(3000, '{\\fArial|b1;VARIES}')).toBe('VARIES');
  });
  it('is empty when suppressed or unknown', () => {
    expect(dimensionLabel(3000, ' ')).toBe('');
    expect(dimensionLabel(null, '')).toBe('');
  });
});

describe('DIMENSION', () => {
  const dim: DxfEntity = {
    id: 'd',
    type: 'DIMENSION',
    layer: 'A',
    color: 7,
    block_name: '*D1',
    dimension_type: 0,
    measurement: 3000,
    text_override: '',
    start: { x: 0, y: 0 },
    end: { x: 3000, y: 0 },
    dim_line_point: { x: 0, y: 500 },
    text_position: { x: 1500, y: 600 },
    rotation: 0,
    height: 250,
  };

  it('draws extension lines, the dimension line and the value when its block is missing', () => {
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [dim], vp(0.1), layers, null, 800, 600, new Map());
    const texts = calls.filter((c) => c.op === 'fillText').map((c) => c.args[0]);
    expect(texts).toEqual(['3000']);
    expect(calls.filter((c) => c.op === 'lineTo').length).toBeGreaterThanOrEqual(3);
  });

  it('draws nothing of its own when the *D block is there, and the block lands in place', () => {
    const member: DxfEntity = { ...line('m', undefined, 0), block: '*D1', start: { x: 0, y: 500 }, end: { x: 3000, y: 500 } };
    const defs = groupBlockDefinitions([member]);
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [dim], vp(0.1), layers, null, 800, 600, defs);
    expect(calls.filter((c) => c.op === 'fillText')).toHaveLength(0);
    const [placed] = expandBlockReferences([dim], defs);
    expect(placed!.start).toEqual({ x: 0, y: 500 });
    expect(placed!.end).toEqual({ x: 3000, y: 500 });
    expect(placed!.layer).toBe('A');
  });
});

describe('text justification', () => {
  it('anchors justified TEXT on its alignment point', () => {
    const { ctx, calls } = stubCtx();
    renderText(
      ctx,
      {
        id: 't',
        type: 'TEXT',
        layer: 'A',
        color: 7,
        start: { x: 0, y: 0 },
        text: 'AXIS A',
        height: 10,
        halign: 2,
        valign: 2,
        align_point: { x: 50, y: -20 },
      },
      vp(1),
    );
    const ft = calls.find((c) => c.op === 'fillText')!;
    expect(ft.args.slice(1)).toEqual([50, 20]);
    expect(ft.textAlign).toBe('right');
    expect(ft.textBaseline).toBe('middle');
  });

  it('hangs top-left MTEXT below its insertion point', () => {
    const { ctx, calls } = stubCtx();
    renderText(
      ctx,
      { id: 'm', type: 'TEXT', layer: 'A', color: 7, start: { x: 0, y: 0 }, text: 'A\nB', height: 10, attachment_point: 1 },
      vp(1),
    );
    const ys = calls.filter((c) => c.op === 'fillText').map((c) => c.args[2] as number);
    expect(ys[0]).toBe(0);
    expect(ys[1]).toBeGreaterThan(0);
    expect(calls.find((c) => c.op === 'fillText')!.textBaseline).toBe('top');
  });

  it('centres middle-centre MTEXT on its insertion point', () => {
    const { ctx, calls } = stubCtx();
    renderText(
      ctx,
      { id: 'm', type: 'TEXT', layer: 'A', color: 7, start: { x: 0, y: 0 }, text: 'ROOM', height: 10, attachment_point: 5 },
      vp(1),
    );
    const ft = calls.find((c) => c.op === 'fillText')!;
    expect(ft.textAlign).toBe('center');
    expect(ft.args[2]).toBe(-5);
  });

  it('frames a find hit where centred text actually sits', () => {
    const box = textBoxForEntity({
      id: 't',
      type: 'TEXT',
      layer: 'A',
      color: 7,
      start: { x: 0, y: 0 },
      text: 'ROOM',
      height: 10,
      halign: 1,
      valign: 2,
      align_point: { x: 100, y: 100 },
    })!;
    expect((box.minX + box.maxX) / 2).toBeCloseTo(100, 5);
    expect((box.minY + box.maxY) / 2).toBeCloseTo(100, 5);
  });

  it('frames a quarter-turned label vertically', () => {
    const box = textBoxForEntity({
      id: 't',
      type: 'TEXT',
      layer: 'A',
      color: 7,
      start: { x: 0, y: 0 },
      text: 'CORRIDOR',
      height: 10,
      rotation: Math.PI / 2,
    })!;
    expect(box.maxY - box.minY).toBeGreaterThan(box.maxX - box.minX);
  });
});
