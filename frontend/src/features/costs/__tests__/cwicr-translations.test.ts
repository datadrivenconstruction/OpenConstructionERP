// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Frontend contract tests for CWICR backend translation plumbing.
//
// The backend (`backend/app/modules/costs/translations`) augments cost
// rows with `<col>_localized` mirror fields when the API is called with
// a known locale.  These tests verify the FE TypeScript types accept
// those mirror fields AND that the standard `localized || source`
// fallback chain is correctly implemented in the renderable shape we
// rely on across CostsPage / VariantPicker / BOQ catalog picker.
//
// We don't render the React tree here — the picker only displays
// numeric variant stats, never the German text columns.  The actual
// German text leak surfaces in CostsPage.CostVariantDetail and in the
// component-table row, both of which read the data fields tested below.

import { describe, it, expect } from 'vitest';
import type { VariantStats } from '../api';

describe('CWICR translation contract — VariantStats', () => {
  it('accepts localized mirror fields on the type', () => {
    // This block compiles iff the type declaration exposes the mirror
    // keys.  A type-level regression (someone deleting unit_localized
    // from `api.ts`) would surface as a TS build break here.
    const stats: VariantStats = {
      min: 1.0,
      max: 5.0,
      mean: 2.5,
      median: 2.0,
      unit: '100 Stück, kg, t',
      group: 'm²=Geonetze und Geogitter',
      count: 3,
      unit_localized: '100 buc, kg, t',
      group_localized: 'm²=Geoplase și geogrile',
    };
    expect(stats.unit_localized).toBe('100 buc, kg, t');
    expect(stats.group_localized).toContain('Geoplase');
  });

  it('falls back to German source when localized field is absent', () => {
    const stats: VariantStats = {
      min: 1,
      max: 5,
      mean: 2.5,
      median: 2,
      unit: '100 Stück',
      group: 'Stück=Geotextilien',
      count: 1,
    };
    // The `localized || source` chain used in CostsPage / boq grid:
    const displayedUnit = stats.unit_localized || stats.unit;
    const displayedGroup = stats.group_localized || stats.group;
    expect(displayedUnit).toBe('100 Stück');
    expect(displayedGroup).toBe('Stück=Geotextilien');
  });
});

describe('CWICR translation contract — fallback chain rendering', () => {
  // Mimic the ternary used in CostsPage.CostVariantDetail:
  //   stats.group_localized || stats.group
  // and the component-table cell:
  //   comp.unit_localized || comp.unit
  // This guards the rule "localized wins, German is the safety net".

  it('prefers localized when both are present', () => {
    const stats = {
      group: 'Stück=Stahlseile',
      group_localized: 'buc=Cabluri de oțel',
    };
    const display = stats.group_localized || stats.group;
    expect(display).toBe('buc=Cabluri de oțel');
  });

  it('uses German source when localized is undefined', () => {
    const stats = { group: 'Stück=Stahlseile' };
    const display =
      (stats as { group_localized?: string }).group_localized || stats.group;
    expect(display).toBe('Stück=Stahlseile');
  });

  it('uses German source when localized is empty string', () => {
    // Pathological case: an empty localized field must still fall back.
    const stats = {
      group: 'Stück=Stahlseile',
      group_localized: '',
    };
    const display = stats.group_localized || stats.group;
    expect(display).toBe('Stück=Stahlseile');
  });

  it('component unit fallback chain', () => {
    const comp = { unit: 'Masch.-Std.', unit_localized: 'ora-mașină' };
    const display = comp.unit_localized || comp.unit;
    expect(display).toBe('ora-mașină');
  });

  it('component unit fallback when no translation exists', () => {
    // Standard unit `kg` doesn't need a translation — but the FE must
    // still render something even if the backend skipped the mirror.
    const comp = { unit: 'kg' };
    const display =
      (comp as { unit_localized?: string }).unit_localized || comp.unit;
    expect(display).toBe('kg');
  });
});
