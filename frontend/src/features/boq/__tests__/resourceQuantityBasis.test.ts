// Issue #555: resource quantities entered per 1 unit of the position (stored
// norms, the catalogue convention) or for the whole position (the entered
// figure is kept, the norm is derived from it by the server).
import { describe, it, expect } from 'vitest';
import {
  RESOURCE_BASIS_KEY,
  RESOURCE_QTY_FOR_POSITION_KEY,
  resourceQuantityBasis,
  resourceQuantityEdit,
  resourceQuantityForPosition,
} from '../boqHelpers';

describe('resourceQuantityBasis', () => {
  it('defaults to per unit, so catalogue build-ups keep their meaning', () => {
    expect(resourceQuantityBasis(undefined)).toBe('per_unit');
    expect(resourceQuantityBasis({})).toBe('per_unit');
    expect(resourceQuantityBasis({ [RESOURCE_BASIS_KEY]: 'other' })).toBe('per_unit');
    expect(resourceQuantityBasis({ [RESOURCE_BASIS_KEY]: 'per_position' })).toBe('per_position');
  });
});

describe('resourceQuantityForPosition', () => {
  it('prefers the figure entered for the whole position', () => {
    expect(resourceQuantityForPosition({ quantity: 1, [RESOURCE_QTY_FOR_POSITION_KEY]: 50 }, 50)).toBe(50);
  });

  it('falls back to norm x position quantity', () => {
    expect(resourceQuantityForPosition({ quantity: 0.5 }, 50)).toBe(25);
    expect(resourceQuantityForPosition({ quantity: '0.5' }, 50)).toBe(25);
    expect(resourceQuantityForPosition({}, 50)).toBe(0);
  });
});

describe('resourceQuantityEdit', () => {
  it('writes a norm under the per-unit basis', () => {
    expect(resourceQuantityEdit('per_unit', 50, 50)).toEqual({ quantity: 50 });
  });

  it('keeps the typed whole-position figure and derives the norm', () => {
    // The reporter's case: 25 poles for a position of 50 is half a pole per unit.
    expect(resourceQuantityEdit('per_position', 25, 50)).toEqual({
      [RESOURCE_QTY_FOR_POSITION_KEY]: 25,
      quantity: 0.5,
    });
  });

  it('cannot divide by a zero position quantity and writes a norm instead', () => {
    expect(resourceQuantityEdit('per_position', 25, 0)).toEqual({ quantity: 25 });
  });
});
