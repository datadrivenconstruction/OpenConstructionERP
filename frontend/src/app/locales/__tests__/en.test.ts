import { describe, expect, it } from 'vitest';
import en from '../en';

describe('BIM copy', () => {
  it('uses clearer text for empty BIM models', () => {
    expect(en.translation['bim.no_elements']).toBe('No BIM elements found');
  });

  it('shows the 2 GB upload limit in the BIM hint text', () => {
    expect(en.translation['bim.upload_size_hint']).toBe('Revit (.rvt), IFC (.ifc) · Max 2 GB');
  });
});
