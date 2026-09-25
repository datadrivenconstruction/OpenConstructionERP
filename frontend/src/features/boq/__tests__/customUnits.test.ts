// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The per-user custom-unit list must only ever grow by genuinely new units.
 *
 * Committing a unit picked from the list used to PATCH the server whenever the
 * unit was missing from this browser's localStorage copy, and every page load
 * PATCHed the merged local list when its length differed from the server's.
 * Both sent a full list that REPLACED the stored one, so two sessions under
 * one login overwrote each other. Now loading never writes, a registry unit
 * or a spelling twin sends nothing, and a new unit is sent alone.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiGet = vi.fn();
const apiPatch = vi.fn();

vi.mock('@/shared/lib/api', () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPatch: (...args: unknown[]) => apiPatch(...args),
}));

// The module caches its in-flight sync promise, so each test imports a fresh copy.
async function freshHelpers() {
  vi.resetModules();
  return import('../boqHelpers');
}

beforeEach(() => {
  window.localStorage.clear();
  apiGet.mockReset();
  apiPatch.mockReset();
  apiPatch.mockResolvedValue({ units: [] });
});

describe('saveCustomUnit', () => {
  it('picking a unit the list offers sends nothing and stores nothing', async () => {
    const { saveCustomUnit } = await freshHelpers();
    // Base units, a locale unit from another language, and spelling twins.
    for (const unit of ['m3', 'M3', 'm³', 'lsum', 'Stk', 'шт', ' kW ']) {
      saveCustomUnit(unit);
    }
    expect(apiPatch).not.toHaveBeenCalled();
    expect(window.localStorage.getItem('oe_custom_units')).toBeNull();
  });

  it('a new unit is sent alone, once, whatever its spelling next time', async () => {
    window.localStorage.setItem('oe_custom_units', JSON.stringify(['crate']));
    const { saveCustomUnit, getUnitsForLocale } = await freshHelpers();

    saveCustomUnit('Pallet²');
    saveCustomUnit('pallet2');
    saveCustomUnit('CRATE');

    expect(apiPatch).toHaveBeenCalledTimes(1);
    expect(apiPatch).toHaveBeenCalledWith('/v1/users/me/custom-units/', { units: ['Pallet²'] });
    expect(getUnitsForLocale('en')).toContain('Pallet²');
  });
});

describe('syncCustomUnitsFromServer', () => {
  it('loading merges the server list locally and sends nothing', async () => {
    window.localStorage.setItem('oe_custom_units', JSON.stringify(['local-only', 'Crate']));
    apiGet.mockResolvedValue({ units: ['crate', 'from-other-session'] });
    const { syncCustomUnitsFromServer } = await freshHelpers();

    const merged = await syncCustomUnitsFromServer();

    expect(merged).toEqual(['local-only', 'Crate', 'from-other-session']);
    expect(JSON.parse(window.localStorage.getItem('oe_custom_units')!)).toEqual(merged);
    expect(apiPatch).not.toHaveBeenCalled();
  });
});
