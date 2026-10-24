// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { PROJECT_PALETTE, defaultProjectColor, isProjectColor, projectColor } from '../projectColor';

describe('project colour', () => {
  it('derives a stable palette colour from the id', () => {
    const id = '3f2a8c1e-0000-4000-8000-000000000001';
    expect(defaultProjectColor(id)).toBe(defaultProjectColor(id));
    expect((PROJECT_PALETTE as readonly string[]).includes(defaultProjectColor(id))).toBe(true);
  });

  it('spreads ids over the palette', () => {
    const seen = new Set(Array.from({ length: 200 }, (_, i) => defaultProjectColor(`p-${i}`)));
    expect(seen.size).toBeGreaterThan(PROJECT_PALETTE.length / 2);
  });

  it('prefers the stored colour and ignores a malformed one', () => {
    expect(projectColor({ id: 'a', color: '#AABBCC' })).toBe('#aabbcc');
    expect(projectColor({ id: 'a', color: 'red' })).toBe(defaultProjectColor('a'));
    expect(projectColor(null)).toBeNull();
    expect(isProjectColor('#12345')).toBe(false);
  });
});
