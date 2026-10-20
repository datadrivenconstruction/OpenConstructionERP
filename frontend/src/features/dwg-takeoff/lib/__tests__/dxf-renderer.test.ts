// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import {
  textFontSize,
  renderText,
  renderInsert,
  renderEntities,
  renderLine,
  hatchPatternSpacing,
} from '../dxf-renderer';
import { groupBlockDefinitions, expandBlockReferences } from '../blocks';
import type { ViewportState } from '../viewport';
import type { DxfEntity } from '../../api';

/**
 * Minimal recording stand-in for CanvasRenderingContext2D. jsdom has no 2D
 * context, and none of these assertions need real rasterisation — they only
 * need to know which drawing calls were issued and with what coordinates.
 */
function stubCtx(): { ctx: CanvasRenderingContext2D; calls: { op: string; args: unknown[] }[] } {
  const calls: { op: string; args: unknown[] }[] = [];
  const rec =
    (op: string) =>
    (...args: unknown[]): void => {
      calls.push({ op, args });
    };
  const ctx = {
    font: '',
    textBaseline: '',
    fillStyle: '',
    strokeStyle: '',
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
    scale: rec('scale'),
    fillText: rec('fillText'),
    arc: rec('arc'),
    ellipse: rec('ellipse'),
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls };
}

const vp = (scale: number): ViewportState => ({ offsetX: 0, offsetY: 0, scale });

function text(height: number | undefined, str = 'ROOM 101'): DxfEntity {
  return {
    id: 't',
    type: 'TEXT',
    layer: 'ANNOT',
    color: 7,
    start: { x: 0, y: 0 },
    text: str,
    height,
  };
}

function insert(over: Partial<DxfEntity> = {}): DxfEntity {
  return {
    id: 'i',
    type: 'INSERT',
    layer: 'BLOCKS',
    color: 7,
    start: { x: 0, y: 0 },
    block_name: 'DOOR-900',
    ...over,
  };
}

function pathPoints(calls: { op: string; args: unknown[] }[]): [number, number][] {
  return calls
    .filter((c) => c.op === 'moveTo' || c.op === 'lineTo')
    .map((c) => [c.args[0] as number, c.args[1] as number]);
}

describe('textFontSize', () => {
  // The authored height, scaled, and nothing else. A readable band here has
  // been reverted once and is the defect behind issue 426 - see the docstring
  // on `textFontSize` and `issue-426-render.test.ts`, which measures what the
  // band does to a real drawing.
  it('tracks the viewport scale', () => {
    const e = text(2.5);
    expect(textFontSize(e, vp(4))).toBeCloseTo(10);
    expect(textFontSize(e, vp(10))).toBeCloseTo(25);
    expect(textFontSize(e, vp(20))).toBeCloseTo(50);
  });

  it('draws a fitted plan’s annotation at the size that plan asks for', () => {
    // A 100 m plan fitted into a 1877 px canvas puts vp.scale near 0.019, so
    // 2.5 mm annotation really is 0.0475 px. Lifting it to a legible floor
    // would lift most of a real plan's annotation with it, which is the
    // reported "labels are much bigger". `renderText` omits it instead.
    expect(textFontSize(text(2.5), vp(0.019))).toBeCloseTo(0.0475, 6);
  });

  it('reports a pathological glyph at its pathological size', () => {
    // The 06_text_large case. A glyph that covers the canvas is a true report
    // of a drawing that says so, and the reader has a size control and a zoom.
    // Capping it here would also cap every ordinary label on the same sheet.
    expect(textFontSize(text(1000), vp(56.8))).toBeCloseTo(56800);
    expect(textFontSize(text(2.5), vp(1000))).toBeCloseTo(2500);
  });

  it('is proportional in the scale, over the whole usable range', () => {
    const e = text(2.5);
    let previous = 0;
    for (const s of [0.001, 0.01, 0.1, 1, 10, 100, 1000]) {
      const px = textFontSize(e, vp(s));
      expect(px).toBeCloseTo(2.5 * s, 6);
      expect(px).toBeGreaterThan(previous);
      previous = px;
    }
  });

  it('defaults a missing height to 2.5 world units', () => {
    expect(textFontSize(text(undefined), vp(4))).toBeCloseTo(10);
  });
});

describe('renderText', () => {
  it('omits a string too small to be anything but a smudge', () => {
    // Half a pixel. Drawing it adds noise rather than information, and this
    // omission is the cheapest cull the renderer has: a zoomed-out plan would
    // otherwise lay out and fill every label in the drawing, once per frame.
    const { ctx, calls } = stubCtx();
    renderText(ctx, text(2.5), vp(0.1)); // 0.25 px
    expect(calls.filter((c) => c.op === 'fillText')).toHaveLength(0);
    expect(calls).toHaveLength(0); // not even a save/restore pair
  });

  it('draws a string that is small but still legible', () => {
    // The line either side of the omission. 2 px is small, and small is what
    // the drawing asked for.
    const { ctx, calls } = stubCtx();
    renderText(ctx, text(2.5), vp(0.8));
    expect(calls.filter((c) => c.op === 'fillText')).toHaveLength(1);
    expect(ctx.font).toContain('2px');
  });

  it('draws every line of an MTEXT', () => {
    const { ctx, calls } = stubCtx();
    renderText(ctx, text(2.5, 'LINE1\nLINE2\nLINE3'), vp(10));
    expect(calls.filter((c) => c.op === 'fillText')).toHaveLength(3);
  });

  it('steps lines by 1.25 of the size it draws', () => {
    // The line step follows what is drawn, so the lines of a scaled MTEXT
    // neither fly apart nor collapse together.
    const { ctx, calls } = stubCtx();
    renderText(ctx, text(1000, 'A\nB'), vp(1));
    const ys = calls.filter((c) => c.op === 'fillText').map((c) => c.args[2] as number);
    expect(ys).toHaveLength(2);
    expect(ys[1]! - ys[0]!).toBeCloseTo(1000 * 1.25);
  });
});

describe('renderInsert marker', () => {
  it('draws the unrotated unit-scale marker as the classic 5 px diamond', () => {
    const { ctx, calls } = stubCtx();
    renderInsert(ctx, insert(), vp(1));
    expect(pathPoints(calls)).toEqual([
      [0, -5],
      [5, 0],
      [0, 5],
      [-5, 0],
    ]);
  });

  it('rotates the marker with the block reference', () => {
    const { ctx, calls } = stubCtx();
    renderInsert(ctx, insert({ rotation: Math.PI / 2 }), vp(1));
    const pts = pathPoints(calls);
    // A quarter turn moves the leading corner off the vertical axis.
    expect(pts[0]![0]).toBeCloseTo(-5);
    expect(pts[0]![1]).toBeCloseTo(0);
  });

  it('shows a non-uniform x/y scale as a non-uniform marker', () => {
    const { ctx, calls } = stubCtx();
    renderInsert(ctx, insert({ x_scale: 2, y_scale: 1 }), vp(1));
    const pts = pathPoints(calls);
    expect(pts[0]![1]).toBeCloseTo(-2.5); // vertical half-axis halved
    expect(pts[1]![0]).toBeCloseTo(5); // horizontal half-axis unchanged
  });

  it('keeps a uniformly scaled block at the marker size — the footprint is unknown', () => {
    // x_scale says the block was scaled 50x but not what it was scaled from,
    // so there is no honest world-space footprint to draw.
    const { ctx, calls } = stubCtx();
    renderInsert(ctx, insert({ x_scale: 50, y_scale: 50 }), vp(1));
    expect(pathPoints(calls)).toEqual([
      [0, -5],
      [5, 0],
      [0, 5],
      [-5, 0],
    ]);
  });

  it('leaves the shared context state as it found it', () => {
    const { ctx, calls } = stubCtx();
    renderInsert(ctx, insert(), vp(1));
    expect(calls.filter((c) => c.op === 'save')).toHaveLength(1);
    expect(calls.filter((c) => c.op === 'restore')).toHaveLength(1);
  });

  it('draws no marker once the definition is available', () => {
    // The marker stands in for geometry the client did not have. When the
    // geometry arrives the caller draws it, and a diamond on top of the door
    // it stands for is worse than either alone.
    const defs = groupBlockDefinitions([
      { id: 'm', type: 'LINE', layer: '0', color: 7, block: 'DOOR-900' },
    ]);
    const { ctx, calls } = stubCtx();
    renderInsert(ctx, insert(), vp(1), defs);
    expect(calls).toHaveLength(0);
  });

  it('still draws the marker when the named definition is missing', () => {
    const defs = groupBlockDefinitions([
      { id: 'm', type: 'LINE', layer: '0', color: 7, block: 'WINDOW' },
    ]);
    const { ctx, calls } = stubCtx();
    renderInsert(ctx, insert(), vp(1), defs);
    expect(pathPoints(calls)).toHaveLength(4);
  });
});

describe('renderEntities', () => {
  it('draws nothing for an unplaced definition member', () => {
    // Its coordinates are in block space, so drawing it here scatters loose
    // parts across the sheet at coordinates that mean nothing.
    const { ctx, calls } = stubCtx();
    const leaf: DxfEntity = {
      id: 'leaf',
      type: 'LINE',
      layer: '0',
      color: 7,
      block: 'DOOR-900',
      start: { x: 0, y: 0 },
      end: { x: 1, y: 1 },
    };
    renderEntities(ctx, [leaf], vp(1), new Set(['0']), null, 800, 600);
    expect(calls.filter((c) => c.op === 'lineTo')).toHaveLength(0);
  });

  it('draws an ordinary entity on a visible layer', () => {
    const { ctx, calls } = stubCtx();
    const line: DxfEntity = {
      id: 'l',
      type: 'LINE',
      layer: 'A-WALL',
      color: 7,
      start: { x: 0, y: 0 },
      end: { x: 1, y: 1 },
    };
    renderEntities(ctx, [line], vp(1), new Set(['A-WALL']), null, 800, 600);
    expect(calls.filter((c) => c.op === 'lineTo')).toHaveLength(1);
  });
});

/* ── Text display ────────────────────────────────────────────────────── */

/** A wall and a label on the same layer: what a dense sheet looks like in
 *  miniature, and enough to tell "text is hidden" from "nothing is drawn". */
const WALL: DxfEntity = {
  id: 'w',
  type: 'LINE',
  layer: 'A-WALL',
  color: 7,
  start: { x: 0, y: 0 },
  end: { x: 10, y: 0 },
};
const LABEL: DxfEntity = { ...text(2.5, 'ROOM 101'), layer: 'A-WALL' };

describe('text size multiplier', () => {
  it('multiplies the size the entity would have been drawn at', () => {
    const e = text(2.5);
    const own = textFontSize(e, vp(10)); // 25 px at this viewport
    expect(own).toBeCloseTo(25);
    expect(textFontSize(e, vp(10), 2)).toBeCloseTo(50);
    expect(textFontSize(e, vp(10), 0.5)).toBeCloseTo(12.5);
  });

  it('defaults to the drawing’s own size when no multiplier is given', () => {
    expect(textFontSize(text(2.5), vp(10))).toBe(textFontSize(text(2.5), vp(10), 1));
  });

  it('moves the label at any zoom, on any drawing', () => {
    // The control multiplies the authored height, so there is no zoom and no
    // drawing where it stops responding. A band would have created two such
    // places - the floor and the ceiling - which is exactly where a reader
    // reaches for it.
    expect(textFontSize(text(2.5), vp(0.019), 0.5)).toBeCloseTo(2.5 * 0.5 * 0.019, 9);
    expect(textFontSize(text(1000), vp(56.8), 2)).toBeCloseTo(1000 * 2 * 56.8, 6);
  });

  it('leaves the proportions between two labels alone', () => {
    // The reason it multiplies the authored height rather than a drawn size:
    // a room tag and a heading keep their ratio at every setting.
    const tag = text(25);
    const heading = text(200);
    for (const preference of [0.5, 1, 2.5]) {
      expect(textFontSize(heading, vp(0.2), preference) / textFontSize(tag, vp(0.2), preference))
        .toBeCloseTo(8, 9);
    }
  });

  it('reaches the font the canvas is set to', () => {
    const { ctx } = stubCtx();
    renderText(ctx, text(2.5), vp(10), 2);
    expect(ctx.font).toContain('50px');
  });

  it('steps the lines of an MTEXT by the multiplied size', () => {
    // The line step follows what is drawn, so scaled lines must not overlap.
    const { ctx, calls } = stubCtx();
    renderText(ctx, text(2.5, 'A\nB'), vp(10), 2);
    const ys = calls.filter((c) => c.op === 'fillText').map((c) => c.args[2] as number);
    expect(ys[1]! - ys[0]!).toBeCloseTo(50 * 1.25);
  });

  it('carries the multiplier through renderEntities', () => {
    const { ctx } = stubCtx();
    renderEntities(ctx, [LABEL], vp(10), new Set(['A-WALL']), null, 800, 600, undefined, {
      visible: true,
      scale: 2,
    });
    expect(ctx.font).toContain('50px');
  });
});

describe('hidden text', () => {
  it('issues no text draw call at all', () => {
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [WALL, LABEL], vp(10), new Set(['A-WALL']), null, 800, 600, undefined, {
      visible: false,
      scale: 1,
    });
    expect(calls.filter((c) => c.op === 'fillText')).toHaveLength(0);
  });

  it('leaves the geometry under it untouched', () => {
    // The whole point of hiding the label is to see the wall it was over.
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [WALL, LABEL], vp(10), new Set(['A-WALL']), null, 800, 600, undefined, {
      visible: false,
      scale: 1,
    });
    expect(calls.filter((c) => c.op === 'lineTo')).toHaveLength(1);
  });

  it('draws the label again when it is switched back on', () => {
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [WALL, LABEL], vp(10), new Set(['A-WALL']), null, 800, 600, undefined, {
      visible: true,
      scale: 1,
    });
    expect(calls.filter((c) => c.op === 'fillText')).toHaveLength(1);
  });

  it('shows text when no setting is passed', () => {
    // Every existing caller passes nothing, and text is what they drew.
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [LABEL], vp(10), new Set(['A-WALL']), null, 800, 600);
    expect(calls.filter((c) => c.op === 'fillText')).toHaveLength(1);
  });

  it('hides the name beside a block marker but keeps the marker', () => {
    // The name is a label; the marker stands in for geometry, and a reader
    // who hid the labels still has to see that something is placed here.
    const { ctx, calls } = stubCtx();
    renderInsert(ctx, insert(), vp(1), undefined, { visible: false, scale: 1 });
    expect(calls.filter((c) => c.op === 'fillText')).toHaveLength(0);
    expect(pathPoints(calls)).toHaveLength(4);
  });

  it('scales the name beside a block marker', () => {
    const { ctx } = stubCtx();
    renderInsert(ctx, insert(), vp(1), undefined, { visible: true, scale: 2 });
    expect(ctx.font).toBe('18px monospace');
  });

  it('hides text carried inside a block reference', () => {
    // A door tag or a room stamp is authored once inside the block and
    // reaches the canvas as a placed copy, never as a loose entity. It is
    // still text, so it goes when text goes - otherwise hiding the labels
    // would clear the sheet and leave every repeated tag behind.
    const { defs, renderList } = blockWithTag();
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, renderList, vp(10), new Set(['A-WALL']), null, 800, 600, defs, {
      visible: false,
      scale: 1,
    });
    expect(calls.filter((c) => c.op === 'fillText')).toHaveLength(0);
  });

  it('draws and scales that same text when it is shown', () => {
    // Guards the test above against passing because the placed copy never
    // reached the renderer in the first place.
    const { defs, renderList } = blockWithTag();
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, renderList, vp(10), new Set(['A-WALL']), null, 800, 600, defs, {
      visible: true,
      scale: 2,
    });
    expect(calls.filter((c) => c.op === 'fillText')).toHaveLength(1);
    expect(ctx.font).toBe('50px Arial, Helvetica, sans-serif'); // 2.5 x 10, doubled
  });
});

/**
 * A block holding one text member, plus the reference that places it, in the
 * shape the renderer actually receives: the reference and its expansion in one
 * list, with the definitions alongside.
 */
function blockWithTag(): { defs: ReturnType<typeof groupBlockDefinitions>; renderList: DxfEntity[] } {
  const defs = groupBlockDefinitions([
    { ...text(2.5, 'D-12'), id: 'tag', block: 'DOOR-900' },
    { ...WALL, id: 'leaf', block: 'DOOR-900' },
  ]);
  const ref = insert({ layer: 'A-WALL' });
  const placed = expandBlockReferences([ref], defs);
  return { defs, renderList: [ref, ...placed] };
}

describe('hatchPatternSpacing', () => {
  // The bug this replaces: the spacing was the literal 8 and the pattern cache
  // keyed on the colour and that literal, so a hatch was drawn 8 screen px apart
  // at every zoom. Zoomed out, a region a few pixels across was filled solid by
  // its own hatch and covered the linework beneath it, which is why the reported
  // overlaps went away on zooming in. The single assertion that would have
  // caught it is that two different zooms do not agree.
  it('answers the zoom instead of returning one constant', () => {
    expect(hatchPatternSpacing(1, 500)).not.toBe(hatchPatternSpacing(2, 500));
  });

  it('scales with the drawing between its two clamps', () => {
    expect(hatchPatternSpacing(1, 500)).toBe(8);
    expect(hatchPatternSpacing(2, 500)).toBe(16);
    expect(hatchPatternSpacing(4, 500)).toBe(32);
  });

  it('stops growing at the upper clamp so the tile cache stays small', () => {
    expect(hatchPatternSpacing(6, 500)).toBe(48);
    expect(hatchPatternSpacing(600, 500)).toBe(48);
  });

  it('rounds to whole pixels, because zoom is continuous and the cache is not', () => {
    expect(hatchPatternSpacing(1.3, 500)).toBe(10); // 10.4
    expect(hatchPatternSpacing(1.45, 500)).toBe(12); // 11.6
  });

  it('gives up on the pattern once the lines would be closer than the floor', () => {
    expect(hatchPatternSpacing(0.5, 500)).toBe(4); // exactly the floor, still drawn
    expect(hatchPatternSpacing(0.49, 500)).toBeNull();
    expect(hatchPatternSpacing(0.01, 500)).toBeNull();
  });

  it('gives up on a region too small to hold a repeat', () => {
    expect(hatchPatternSpacing(1, 3)).toBe(8);
    expect(hatchPatternSpacing(1, 2)).toBeNull();
    expect(hatchPatternSpacing(1, 0)).toBeNull();
  });

  it('treats a degenerate scale as no pattern rather than as a huge one', () => {
    expect(hatchPatternSpacing(0, 500)).toBeNull();
    expect(hatchPatternSpacing(Number.NaN, 500)).toBeNull();
  });
});

describe('stroke batching in renderEntities', () => {
  // A canvas charges for every stroke() and every state change, and a drawing is
  // thousands of short segments that mostly agree about their colour. The loop
  // used to issue beginPath and stroke per entity. It now collects a run of
  // entities that would be stroked with the same style into one path.
  //
  // Runs, deliberately, not groups: sorting by colour would batch harder and
  // would also change which line lands on top of which where they cross. Every
  // test here pins that the order and the geometry come out unchanged, because
  // that is the property the optimisation is only worth having if it keeps.
  const line = (id: string, color: number, x: number): DxfEntity => ({
    id,
    type: 'LINE',
    layer: 'A-WALL',
    color,
    start: { x, y: 0 },
    end: { x: x + 1, y: 0 },
  });

  const layers = new Set(['A-WALL']);
  const strokes = (calls: { op: string; args: unknown[] }[]): number =>
    calls.filter((c) => c.op === 'stroke').length;

  it('strokes a run of one colour once instead of once per entity', () => {
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [line('a', 7, 0), line('b', 7, 5), line('c', 7, 10)], vp(1), layers, null, 800, 600);
    expect(strokes(calls)).toBe(1);
    expect(calls.filter((c) => c.op === 'beginPath')).toHaveLength(1);
    // All three are still drawn, in the order they arrived.
    expect(pathPoints(calls)).toHaveLength(6);
  });

  it('keeps the geometry identical to drawing each entity on its own', () => {
    const entities = [line('a', 7, 0), line('b', 7, 5), line('c', 7, 10)];
    const batched = stubCtx();
    renderEntities(batched.ctx, entities, vp(1), layers, null, 800, 600);

    const oneByOne = stubCtx();
    for (const e of entities) renderLine(oneByOne.ctx, e, vp(1));

    expect(pathPoints(batched.calls)).toEqual(pathPoints(oneByOne.calls));
  });

  it('breaks the run when the colour changes', () => {
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [line('a', 7, 0), line('b', 1, 5), line('c', 7, 10)], vp(1), layers, null, 800, 600);
    expect(strokes(calls)).toBe(3);
  });

  it('rejoins a run after a colour interrupts it, rather than giving up', () => {
    // Four entities, one odd one in the middle: 7, 7, 1, 7. Three batches, not
    // four, and not one. A flush that forgot to reset would keep breaking after
    // the first interruption and quietly undo the whole optimisation on any
    // drawing that mixes colours.
    const { ctx, calls } = stubCtx();
    renderEntities(
      ctx,
      [line('a', 7, 0), line('b', 7, 5), line('c', 1, 10), line('d', 7, 15)],
      vp(1),
      layers,
      null,
      800,
      600,
    );
    expect(strokes(calls)).toBe(3);
    expect(pathPoints(calls)).toHaveLength(8);
  });

  it('breaks the run on both sides of the selected entity', () => {
    // The selected entity gets a wider stroke and a glow. Lending that to a
    // neighbour, or borrowing a neighbour's plain style, would both be visible.
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [line('a', 7, 0), line('sel', 7, 5), line('c', 7, 10)], vp(1), layers, 'sel', 800, 600);
    expect(strokes(calls)).toBe(3);
  });

  it('closes the batch before anything that fills or writes text', () => {
    // renderText and renderPoint open paths and fill. Leaving a half-built
    // stroke path open across them would either lose it or stroke it twice.
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [line('a', 7, 0), LABEL, line('c', 7, 10)], vp(1), layers, null, 800, 600);
    const order = calls.filter((c) => c.op === 'stroke' || c.op === 'fillText').map((c) => c.op);
    expect(order).toEqual(['stroke', 'fillText', 'stroke']);
  });

  it('moves to the start of an arc so a batch does not draw a chord to it', () => {
    // Inside a shared path, arc() is joined to the previous subpath by a
    // straight line. That would be a stray chord across the drawing, and it is
    // the one way this optimisation could change pixels.
    const arc: DxfEntity = {
      id: 'arc',
      type: 'ARC',
      layer: 'A-WALL',
      color: 7,
      start: { x: 100, y: 100 },
      radius: 10,
      start_angle: 0,
      end_angle: Math.PI,
    };
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [line('a', 7, 0), arc], vp(1), layers, null, 800, 600);
    const ops = calls.filter((c) => ['moveTo', 'lineTo', 'arc'].includes(c.op)).map((c) => c.op);
    expect(ops).toEqual(['moveTo', 'lineTo', 'moveTo', 'arc']);
    expect(strokes(calls)).toBe(1);
  });

  it('strokes nothing when every entity is filtered out', () => {
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [line('a', 7, 0)], vp(1), new Set(['OTHER']), null, 800, 600);
    expect(strokes(calls)).toBe(0);
    expect(calls.filter((c) => c.op === 'beginPath')).toHaveLength(0);
  });
});

describe('ARC sweep direction', () => {
  it('draws the short arc, not its complement', () => {
    // A quarter arc from +x to +y in world space. With Y flipped on screen the
    // canvas must sweep anticlockwise from 0 to -PI/2; clockwise would draw
    // the other three quarters (a flat arc then shows as a giant circle).
    const arc: DxfEntity = {
      id: 'q',
      type: 'ARC',
      layer: 'A-WALL',
      color: 7,
      start: { x: 0, y: 0 },
      radius: 10,
      start_angle: 0,
      end_angle: Math.PI / 2,
    };
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [arc], vp(1), new Set(['A-WALL']), null, 800, 600);
    const call = calls.find((c) => c.op === 'arc');
    expect(call?.args.slice(3)).toEqual([-0, -Math.PI / 2, true]);
  });
});

describe('ELLIPSE arcs', () => {
  it('draws only the parameter range of an elliptical arc', () => {
    const swing: DxfEntity = {
      id: 'swing',
      type: 'ELLIPSE',
      layer: 'A-WALL',
      color: 7,
      start: { x: 0, y: 0 },
      major_radius: 10,
      minor_radius: 8,
      rotation: 0,
      start_angle: 0,
      end_angle: Math.PI / 2,
    };
    const { ctx, calls } = stubCtx();
    renderEntities(ctx, [swing], vp(1), new Set(['A-WALL']), null, 800, 600);
    const call = calls.find((c) => c.op === 'ellipse');
    expect(call?.args.slice(5)).toEqual([-0, -Math.PI / 2, true]);
  });
});
