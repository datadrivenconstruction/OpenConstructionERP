// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { groupBlockDefinitions, expandBlockReferences, isResolvedInsert } from '../blocks';
import type { DxfEntity } from '../../api';

function member(block: string, over: Partial<DxfEntity> = {}): DxfEntity {
  return {
    id: 'm',
    type: 'LINE',
    layer: '0',
    color: 7,
    block,
    start: { x: 0, y: 0 },
    end: { x: 1, y: 0 },
    ...over,
  };
}

function insert(over: Partial<DxfEntity> = {}): DxfEntity {
  return {
    id: 'i',
    type: 'INSERT',
    layer: 'A-DOOR',
    color: 3,
    layout: 'Model',
    start: { x: 0, y: 0 },
    block_name: 'DOOR-900',
    ...over,
  };
}

const defs = (entities: DxfEntity[]) => groupBlockDefinitions(entities);

describe('groupBlockDefinitions', () => {
  it('keys members by their block and ignores placed entities', () => {
    const map = defs([
      member('DOOR-900', { id: 'a' }),
      member('DOOR-900', { id: 'b' }),
      member('WINDOW', { id: 'c' }),
      insert(),
      { id: 'p', type: 'LINE', layer: 'A-WALL', color: 7, layout: 'Model' },
    ]);
    expect([...map.keys()].sort()).toEqual(['DOOR-900', 'WINDOW']);
    expect(map.get('DOOR-900')!.map((e) => e.id)).toEqual(['a', 'b']);
  });

  it('is empty for a payload with no definitions at all', () => {
    expect(defs([insert()]).size).toBe(0);
  });
});

describe('expandBlockReferences', () => {
  it('places a member at the reference point', () => {
    const map = defs([member('DOOR-900')]);
    const [placed] = expandBlockReferences([insert({ start: { x: 100, y: 200 } })], map);
    expect(placed!.start).toEqual({ x: 100, y: 200 });
    expect(placed!.end).toEqual({ x: 101, y: 200 });
  });

  it('reads rotation as radians and never as degrees', () => {
    // The wire carries radians. A right angle arrives as 1.5707963267948966,
    // and the backend is the one place that converts. If a degrees-to-radians
    // step is ever added here the two conversions compound and this member
    // lands at (1, 0) instead of (0, 1) - a quarter turn becomes 1.6 degrees.
    const map = defs([member('DOOR-900')]);
    const [placed] = expandBlockReferences([insert({ rotation: Math.PI / 2 })], map);
    expect(placed!.start!.x).toBeCloseTo(0);
    expect(placed!.start!.y).toBeCloseTo(0);
    expect(placed!.end!.x).toBeCloseTo(0);
    expect(placed!.end!.y).toBeCloseTo(1);
  });

  it('scales, rotates and translates in that order', () => {
    const map = defs([member('DOOR-900')]);
    const [placed] = expandBlockReferences(
      [insert({ start: { x: 10, y: 5 }, x_scale: 3, y_scale: 3, rotation: Math.PI })],
      map,
    );
    expect(placed!.end!.x).toBeCloseTo(7); // 10 - 3
    expect(placed!.end!.y).toBeCloseTo(5);
  });

  it('gives placed members the reference’s layer and layout, not their own', () => {
    // A definition is authored on layer "0", which the user never sees in the
    // layer panel. Inheriting the reference's layer is what makes the block
    // obey the panel at all - and it is the CAD rule besides.
    const map = defs([member('DOOR-900')]);
    const [placed] = expandBlockReferences([insert()], map);
    expect(placed!.layer).toBe('A-DOOR');
    expect(placed!.layout).toBe('Model');
    expect(placed!.block).toBeUndefined();
  });

  it('resolves ByBlock colour to the reference’s colour', () => {
    const map = defs([member('DOOR-900', { color: 0 }), member('DOOR-900', { id: 'n', color: 1 })]);
    const placed = expandBlockReferences([insert({ color: 3 })], map);
    expect(placed[0]!.color).toBe(3); // ByBlock -> takes the reference
    expect(placed[1]!.color).toBe(1); // explicit -> keeps its own
  });

  it('gives every placement a distinct id', () => {
    const map = defs([member('DOOR-900', { id: 'leaf' })]);
    const placed = expandBlockReferences(
      [insert({ id: 'i1' }), insert({ id: 'i2', start: { x: 50, y: 0 } })],
      map,
    );
    expect(placed.map((e) => e.id)).toEqual(['i1/leaf', 'i2/leaf']);
  });

  it('leaves an unresolvable reference to its marker', () => {
    expect(expandBlockReferences([insert({ block_name: 'MISSING' })], defs([member('OTHER')])))
      .toEqual([]);
    expect(expandBlockReferences([insert()], new Map())).toEqual([]);
  });

  it('does not expand an INSERT that is itself a definition member', () => {
    // Its coordinates are in block space; it is reached through its parent.
    const map = defs([member('DOOR-900')]);
    const nested = { ...insert({ id: 'inner' }), block: 'OUTER' } as DxfEntity;
    expect(expandBlockReferences([nested], map)).toEqual([]);
  });
});

describe('expandBlockReferences nesting', () => {
  it('follows a block that places another block', () => {
    const map = defs([
      { ...insert({ id: 'in', start: { x: 10, y: 0 }, block_name: 'INNER' }), block: 'OUTER' },
      member('INNER', { id: 'leaf' }),
    ]);
    const placed = expandBlockReferences([insert({ id: 'top', block_name: 'OUTER' })], map);
    expect(placed).toHaveLength(1);
    expect(placed[0]!.start).toEqual({ x: 10, y: 0 });
    expect(placed[0]!.id).toBe('top/in/leaf');
  });

  it('terminates on a self-referential definition instead of hanging', () => {
    // A block that inserts itself is a legal export and an infinite drawing.
    const map = defs([
      { ...insert({ id: 'self', block_name: 'LOOP' }), block: 'LOOP' },
      member('LOOP', { id: 'leaf' }),
    ]);
    const placed = expandBlockReferences([insert({ id: 'top', block_name: 'LOOP' })], map);
    expect(placed).toHaveLength(1);
    expect(placed[0]!.id).toBe('top/leaf');
  });

  it('terminates on a two-block cycle', () => {
    const map = defs([
      { ...insert({ id: 'a2b', block_name: 'B' }), block: 'A' },
      { ...insert({ id: 'b2a', block_name: 'A' }), block: 'B' },
      member('A', { id: 'leafA' }),
    ]);
    const placed = expandBlockReferences([insert({ id: 'top', block_name: 'A' })], map);
    expect(placed.every((e) => e.id.startsWith('top/'))).toBe(true);
    expect(placed.length).toBeLessThan(10);
  });

  it('places a block twice when one definition references it twice', () => {
    // The cycle guard is per chain, not global. A shared visited set would
    // silently drop the second door and nothing anywhere would report it.
    const map = defs([
      { ...insert({ id: 'l', start: { x: 0, y: 0 }, block_name: 'LEAF' }), block: 'PAIR' },
      { ...insert({ id: 'r', start: { x: 40, y: 0 }, block_name: 'LEAF' }), block: 'PAIR' },
      member('LEAF', { id: 'leaf' }),
    ]);
    const placed = expandBlockReferences([insert({ id: 'top', block_name: 'PAIR' })], map);
    expect(placed).toHaveLength(2);
    expect(placed.map((e) => e.start!.x)).toEqual([0, 40]);
  });

  it('stops at depth 8', () => {
    // Each level nests one deeper and carries the leaf, so the leaf placement
    // is what disappears once the cap is reached.
    const entities: DxfEntity[] = [];
    for (let i = 0; i < 12; i++) {
      entities.push({ ...insert({ id: `n${i}`, block_name: `L${i + 1}` }), block: `L${i}` });
    }
    entities.push(member('L12', { id: 'leaf' }));
    const placed = expandBlockReferences([insert({ id: 'top', block_name: 'L0' })], defs(entities));
    expect(placed).toEqual([]);
  });
});

describe('expandBlockReferences shapes', () => {
  it('scales a circle radius under a uniform scale', () => {
    const map = defs([
      member('DOOR-900', { type: 'CIRCLE', radius: 2, start: { x: 0, y: 0 }, end: undefined }),
    ]);
    const [placed] = expandBlockReferences([insert({ x_scale: 4, y_scale: 4 })], map);
    expect(placed!.type).toBe('CIRCLE');
    expect(placed!.radius).toBeCloseTo(8);
  });

  it('turns a circle under a non-uniform scale into an ellipse', () => {
    // A circle stretched twice as far in x is an ellipse in the drawing.
    // Drawing it as a circle at some averaged radius is wrong in both axes.
    const map = defs([
      member('DOOR-900', { type: 'CIRCLE', radius: 2, start: { x: 0, y: 0 }, end: undefined }),
    ]);
    const [placed] = expandBlockReferences([insert({ x_scale: 2, y_scale: 1 })], map);
    expect(placed!.type).toBe('ELLIPSE');
    expect(placed!.major_radius).toBeCloseTo(4);
    expect(placed!.minor_radius).toBeCloseTo(2);
    expect(placed!.radius).toBeUndefined();
  });

  it('swaps arc endpoints under a mirror so the sweep stays counter-clockwise', () => {
    // Reflecting a CCW sweep gives a CW one, and the renderer only draws CCW.
    // Without the swap a mirrored door arc bulges the wrong way.
    const map = defs([
      member('DOOR-900', {
        type: 'ARC',
        radius: 1,
        start: { x: 0, y: 0 },
        end: undefined,
        start_angle: 0,
        end_angle: Math.PI / 2,
      }),
    ]);
    const [plain] = expandBlockReferences([insert()], map);
    expect(plain!.start_angle).toBeCloseTo(0);
    expect(plain!.end_angle).toBeCloseTo(Math.PI / 2);

    const [mirrored] = expandBlockReferences([insert({ x_scale: -1, y_scale: 1 })], map);
    // x-mirror sends a -> pi - a, and the endpoints trade places.
    expect(mirrored!.start_angle).toBeCloseTo(Math.PI / 2);
    expect(mirrored!.end_angle).toBeCloseTo(Math.PI);
  });

  it('draws an arc under an anisotropic scale as an elliptical arc', () => {
    const map = defs([
      member('DOOR-900', {
        type: 'ARC',
        radius: 1,
        start: { x: 0, y: 0 },
        end: undefined,
        start_angle: 0,
        end_angle: Math.PI / 2,
      }),
      member('DOOR-900', { id: 'ln' }),
    ]);
    const placed = expandBlockReferences([insert({ x_scale: 3, y_scale: 1 })], map);
    expect(placed.map((e) => e.id)).toEqual(['i/m', 'i/ln']);
    const arc = placed[0]!;
    expect(arc.type).toBe('ELLIPSE');
    expect(arc.major_radius).toBeCloseTo(3);
    expect(arc.minor_radius).toBeCloseTo(1);
    expect(arc.start_angle).toBeCloseTo(0);
    expect(arc.end_angle).toBeCloseTo(Math.PI / 2);
  });

  it('keeps an elliptical arc counter-clockwise under a mirror', () => {
    const map = defs([
      member('DOOR-900', {
        type: 'ELLIPSE',
        start: { x: 0, y: 0 },
        end: undefined,
        major_radius: 2,
        minor_radius: 1,
        rotation: 0,
        start_angle: 0,
        end_angle: Math.PI / 2,
      }),
    ]);
    const [mirrored] = expandBlockReferences([insert({ x_scale: -1, y_scale: 1 })], map);
    // The quarter in +x+y lands in -x+y: parameters -pi/2..0 with the major axis turned to pi.
    expect(mirrored!.rotation).toBeCloseTo(Math.PI);
    expect(mirrored!.start_angle).toBeCloseTo(-Math.PI / 2);
    expect(mirrored!.end_angle).toBeCloseTo(0);
  });

  it('scales text height by the reference and keeps it readable side up', () => {
    const map = defs([
      member('DOOR-900', { type: 'TEXT', text: 'D9', height: 2.5, end: undefined }),
    ]);
    const [placed] = expandBlockReferences([insert({ x_scale: -4, y_scale: 4 })], map);
    expect(placed!.height).toBeCloseTo(10);
  });
});

describe('isResolvedInsert', () => {
  it('is true only for a reference whose definition arrived', () => {
    const map = defs([member('DOOR-900')]);
    expect(isResolvedInsert(insert(), map)).toBe(true);
    expect(isResolvedInsert(insert({ block_name: 'MISSING' }), map)).toBe(false);
    expect(isResolvedInsert(insert({ block_name: undefined }), map)).toBe(false);
    expect(isResolvedInsert(member('DOOR-900'), map)).toBe(false);
  });
});
