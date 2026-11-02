import { afterEach, describe, expect, it } from 'vitest';
import type { MarketScope } from '../api';
import {
  diffHidden,
  isCountryInScope,
  isModuleOtherMarket,
  isRouteHiddenByMarket,
  marketOffersAia,
  ruleSetsFromScope,
  showAiaForProject,
} from '../logic';
import { filterUnitsBySystem, getUnitsForLocale, setActiveUnitsSystem } from '@/features/boq/boqHelpers';

function scope(over: Partial<MarketScope>): MarketScope {
  return {
    profile: {
      primary: null,
      extra_markets: [],
      company_type: null,
      standards: { classification: '', measurement: '', contract_family: '', tax_profile: '', units: '' },
      keep_modules: [],
    },
    derived: false,
    markets: [],
    expanded_markets: [],
    all_markets: false,
    hidden_modules: [],
    module_markets: {},
    packs: [],
    units_system: 'metric',
    standards: {},
    options: { standards: [], contract_forms: [] },
    rule_sets: ['boq_quality'],
    can_edit: false,
    ...over,
  };
}

// Shapes the server returns for the three acceptance tenants (see backend tests/unit/test_market_scope.py).
const german = scope({
  markets: ['DE'],
  hidden_modules: ['uk_pack', 'us_pack', 'us_ca_pack', 'us_tx_pack', 'middle_east_pack', 'sa_pack'],
  options: { standards: ['DIN_276'], contract_forms: ['VOB_B_EINHEITSPREIS'] },
  rule_sets: ['boq_quality', 'din276', 'gaeb'],
});
const saudi = scope({
  markets: ['SA'],
  hidden_modules: ['dach_pack', 'uk_pack', 'us_pack', 'tax_withholding'],
  options: { standards: ['POMI'], contract_forms: ['FIDIC_RED'] },
});
const american = scope({
  markets: ['US'],
  units_system: 'imperial',
  hidden_modules: ['dach_pack', 'uk_pack', 'middle_east_pack', 'einvoice_clearance'],
  options: { standards: ['US_DIVISIONS'], contract_forms: ['AIA_A101'] },
});

afterEach(() => setActiveUnitsSystem('both'));

describe('market scope gates', () => {
  it('German tenant: no UK, US or Saudi rows', () => {
    for (const m of ['oe_uk_pack', 'us_pack', 'oe_middle_east_pack']) expect(isModuleOtherMarket(m, german)).toBe(true);
    expect(isModuleOtherMarket('oe_dach_pack', german)).toBe(false);
    expect(isRouteHiddenByMarket('oe_tax_withholding', german)).toBe(false);
    expect(marketOffersAia(german)).toBe(false);
    expect(ruleSetsFromScope(german)).toEqual(['boq_quality', 'din276', 'gaeb']);
  });

  it('Saudi tenant: GCC rows stay, withholding goes', () => {
    expect(isModuleOtherMarket('oe_middle_east_pack', saudi)).toBe(false);
    expect(isRouteHiddenByMarket('oe_einvoice_clearance', saudi)).toBe(false);
    expect(isRouteHiddenByMarket('oe_tax_withholding', saudi)).toBe(true);
    expect(marketOffersAia(saudi)).toBe(false);
  });

  it('US tenant: AIA and imperial', () => {
    expect(marketOffersAia(american)).toBe(true);
    expect(isModuleOtherMarket('oe_us_pack', american)).toBe(false);
    expect(isRouteHiddenByMarket(['oe_einvoice_clearance', 'oe_dach_pack'], american)).toBe(true);
  });

  it('fails open while the scope loads', () => {
    expect(isRouteHiddenByMarket('oe_uk_pack', undefined)).toBe(false);
    expect(ruleSetsFromScope(undefined)).toEqual(['boq_quality']);
  });
});

describe('unit picker by units system', () => {
  it('metric markets lose imperial tokens but keep neutral and used ones', () => {
    const out = filterUnitsBySystem(['m2', 'sqft', 'pcs', 'cuyd', 'h'], 'metric', ['cuyd']);
    expect(out).toEqual(['m2', 'pcs', 'cuyd', 'h']);
  });

  it('imperial markets lose metric tokens', () => {
    expect(filterUnitsBySystem(['m2', 'sqft', 'pcs'], 'imperial')).toEqual(['sqft', 'pcs']);
  });

  it('the active system drives getUnitsForLocale', () => {
    setActiveUnitsSystem('metric');
    const units = getUnitsForLocale('de');
    expect(units).toContain('m3');
    expect(units).not.toContain('bdft');
    setActiveUnitsSystem('both');
    expect(getUnitsForLocale('de')).toContain('bdft');
  });
});

describe('market preview and scoped lists', () => {
  it('diffs hidden modules into appear, disappear and unchanged', () => {
    expect(diffHidden(['aia', 'gaeb'], ['gaeb', 'zatca'], ['aia', 'gaeb', 'zatca', 'nrm'])).toEqual({
      appear: ['aia'],
      disappear: ['zatca'],
      unchanged: 1,
    });
  });

  it('shows AIA only for a US market and an eligible project', () => {
    const us = scope({ options: { standards: [], contract_forms: ['AIA_A101'] } });
    const de = scope({ options: { standards: [], contract_forms: ['VOB_B'] } });
    expect(showAiaForProject(us, true)).toBe(true);
    expect(showAiaForProject(us, false)).toBe(false);
    expect(showAiaForProject(de, true)).toBe(false);
  });

  it('filters countries by market and fails open while loading', () => {
    const sa = scope({ expanded_markets: ['SA'] });
    expect(isCountryInScope('sa', sa)).toBe(true);
    expect(isCountryInScope('DE', sa)).toBe(false);
    expect(isCountryInScope('DE', undefined)).toBe(true);
    expect(isCountryInScope('DE', scope({ all_markets: true, expanded_markets: ['SA'] }))).toBe(true);
  });
});

describe('units system hydration', () => {
  it('follows the tenant scope query, not project scopes', async () => {
    const { QueryClient } = await import('@tanstack/react-query');
    const { hydrateUnitsSystem, MARKET_QUERY_KEY } = await import('../api');
    const { getActiveUnitsSystem } = await import('@/features/boq/boqHelpers');
    const client = new QueryClient();
    const stop = hydrateUnitsSystem(client);
    client.setQueryData([...MARKET_QUERY_KEY, 'p1'], scope({ units_system: 'imperial' }));
    expect(getActiveUnitsSystem()).toBe('both');
    client.setQueryData([...MARKET_QUERY_KEY, null], scope({ units_system: 'metric' }));
    expect(getActiveUnitsSystem()).toBe('metric');
    stop();
  });
});
