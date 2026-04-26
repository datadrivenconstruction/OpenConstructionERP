/**
 * Pure-function tests for the slot-type compatibility matrix and the canvas
 * drop translator. Both live in `dnd.ts` and have no React dependency, so we
 * exercise them as plain functions.
 */
import { describe, expect, it } from 'vitest';

import {
  BLOCK_KIND_TO_COLOR,
  buildDropPayload,
  canConnectSlots,
  colorForKind,
  isSlotCompatible,
  type SlotDefinition,
} from '../dnd';

describe('isSlotCompatible — type matrix', () => {
  it('allows like-typed connections', () => {
    expect(isSlotCompatible('selector', 'selector')).toBe(true);
    expect(isSlotCompatible('predicate', 'predicate')).toBe(true);
    expect(isSlotCompatible('attribute', 'attribute')).toBe(true);
    expect(isSlotCompatible('constraint', 'constraint')).toBe(true);
  });

  it('rejects cross-category connections', () => {
    expect(isSlotCompatible('selector', 'predicate')).toBe(false);
    expect(isSlotCompatible('attribute', 'constraint')).toBe(false);
    expect(isSlotCompatible('constraint', 'selector')).toBe(false);
    expect(isSlotCompatible('predicate', 'attribute')).toBe(false);
  });

  it('treats `any` as a wildcard on either side', () => {
    expect(isSlotCompatible('any', 'selector')).toBe(true);
    expect(isSlotCompatible('predicate', 'any')).toBe(true);
    expect(isSlotCompatible('any', 'any')).toBe(true);
  });

  it('routes variable into number slots (formula integration)', () => {
    expect(isSlotCompatible('variable', 'number')).toBe(true);
    expect(isSlotCompatible('number', 'variable')).toBe(true);
    expect(isSlotCompatible('variable', 'string')).toBe(false);
  });
});

describe('canConnectSlots — directionality', () => {
  const out: SlotDefinition = { id: 'a', label: 'A', direction: 'output', dataType: 'predicate' };
  const into: SlotDefinition = { id: 'b', label: 'B', direction: 'input', dataType: 'predicate' };

  it('accepts output → input with matching types', () => {
    expect(canConnectSlots(out, into)).toBe(true);
  });

  it('rejects output → output (no input target)', () => {
    const otherOut: SlotDefinition = { ...into, direction: 'output' };
    expect(canConnectSlots(out, otherOut)).toBe(false);
  });

  it('rejects input → input', () => {
    const fakeSource: SlotDefinition = { ...out, direction: 'input' };
    expect(canConnectSlots(fakeSource, into)).toBe(false);
  });

  it('rejects type-mismatched output → input', () => {
    const mismatched: SlotDefinition = { ...into, dataType: 'attribute' };
    expect(canConnectSlots(out, mismatched)).toBe(false);
  });
});

describe('colorForKind / BLOCK_KIND_TO_COLOR', () => {
  it('maps known kinds to canonical colors', () => {
    expect(colorForKind('and')).toBe('logic');
    expect(colorForKind('ifc_class')).toBe('selector');
    expect(colorForKind('eq')).toBe('constraint');
    expect(colorForKind('alias')).toBe('attribute');
  });

  it('falls back to selector for unknown kinds', () => {
    expect(colorForKind('totally-unknown-kind')).toBe('selector');
  });

  it('exports a frozen-shaped lookup table', () => {
    expect(Object.keys(BLOCK_KIND_TO_COLOR)).toContain('and');
    expect(Object.keys(BLOCK_KIND_TO_COLOR)).toContain('triplet');
  });
});

describe('buildDropPayload', () => {
  it('extracts kind from payload.type when present', () => {
    const payload = buildDropPayload({
      paletteItemId: 'logic.and',
      paletteLabel: 'AND',
      paletteColor: 'logic',
      paletteRawPayload: { type: 'and' },
      position: { x: 100, y: 200 },
    });
    expect(payload.kind).toBe('and');
    expect(payload.color).toBe('logic');
    expect(payload.position).toEqual({ x: 100, y: 200 });
    expect(payload.label).toBe('AND');
  });

  it('falls back to the last segment of the palette id when no payload.type', () => {
    const payload = buildDropPayload({
      paletteItemId: 'selector.spatial',
      paletteLabel: 'Spatial',
      paletteColor: 'selector',
      position: { x: 0, y: 0 },
    });
    expect(payload.kind).toBe('spatial');
  });

  it('reads kind from payload.kind or payload.operator when type is absent', () => {
    const a = buildDropPayload({
      paletteItemId: 'attr.alias',
      paletteLabel: 'Alias',
      paletteColor: 'attribute',
      paletteRawPayload: { kind: 'alias' },
      position: { x: 1, y: 2 },
    });
    expect(a.kind).toBe('alias');

    const b = buildDropPayload({
      paletteItemId: 'constraint.eq',
      paletteLabel: 'Equals',
      paletteColor: 'constraint',
      paletteRawPayload: { operator: 'eq' },
      position: { x: 3, y: 4 },
    });
    expect(b.kind).toBe('eq');
  });

  it('preserves the original raw payload for downstream consumers', () => {
    const payload = buildDropPayload({
      paletteItemId: 'variable.local',
      paletteLabel: 'Local',
      paletteColor: 'variable',
      paletteRawPayload: { scope: 'local', custom: 42 },
      position: { x: 0, y: 0 },
    });
    expect(payload.payload).toEqual({ scope: 'local', custom: 42 });
  });
});
