import { describe, expect, it } from 'vitest';
import en from '../en';

describe('BIM empty-state copy', () => {
  it('uses clearer text for empty BIM models', () => {
    expect(en.translation['bim.no_elements']).toBe('No BIM elements found');
  });
});
