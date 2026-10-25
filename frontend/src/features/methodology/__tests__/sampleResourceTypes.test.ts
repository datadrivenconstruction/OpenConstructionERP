import { describe, expect, it } from 'vitest';
import { sampleResourceTypes } from '../cascadeMath';

describe('sampleResourceTypes', () => {
  it('offers exactly the resource types the base mapping consumes', () => {
    const types = sampleResourceTypes({
      labor: ['labor'],
      direct: ['equipment', 'machinery', 'labor'],
    });
    expect(types).toEqual(['labor', 'equipment', 'machinery']);
  });
  it('falls back to the default set for an empty mapping', () => {
    expect(sampleResourceTypes({})).toContain('machinery');
  });
});
