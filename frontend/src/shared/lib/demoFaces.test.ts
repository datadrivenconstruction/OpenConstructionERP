// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { DEMO_PROFILES } from './demoProfiles';
import { demoFaceFor } from './demoFaces';

describe('demoFaceFor', () => {
  it('gives every demo descriptor a photo for its hexagon', () => {
    for (const profile of DEMO_PROFILES) {
      expect(demoFaceFor(profile.slug).src, profile.slug).toMatch(/\/cmt-.+\.webp$/);
    }
  });

  it('covers the Paris and Shanghai demos before their descriptors declare a face', () => {
    expect(demoFaceFor('school-paris').src).toMatch(/\.webp$/);
    expect(demoFaceFor('office-shanghai').src).toMatch(/\.webp$/);
  });

  it('falls back to a drawing for an unknown demo', () => {
    expect(demoFaceFor('nowhere')).toEqual({ src: null, kind: 'warehouse' });
  });
});
