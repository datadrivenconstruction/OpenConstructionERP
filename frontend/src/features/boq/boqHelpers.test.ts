// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// boqHelpers.convertToBase — multi-currency rebase contract (Issue #88 / #111)
//
// User scenario from issue #111: project base USD, position priced in ARS,
// FX rate "1 ARS = 0.000707 USD" (the inverse of "1 USD = 1415 ARS").
// Without rebase, ARS totals were summed as if they were already USD,
// producing nonsensical figures.

import { describe, it, expect } from 'vitest';
import {
  classificationCode,
  convertToBase,
  getUnitsForLocale,
  hasContributingResources,
  resourceAwareTotalInBase,
  catalogComponentAmounts,
} from './boqHelpers';

describe('convertToBase - multi-currency rebase', () => {
  const fxRates = [
    { currency: 'ARS', rate: 1 / 1415 }, // 1 ARS = 0.000707 USD
    { currency: 'EUR', rate: 1.08 },     // 1 EUR = 1.08 USD
  ];

  it('returns value unchanged when source currency equals base', () => {
    expect(convertToBase(100, 'USD', 'USD', fxRates)).toBe(100);
  });

  it('returns value unchanged when source currency is empty/undefined', () => {
    expect(convertToBase(100, undefined, 'USD', fxRates)).toBe(100);
    expect(convertToBase(100, '', 'USD', fxRates)).toBe(100);
    expect(convertToBase(100, null, 'USD', fxRates)).toBe(100);
  });

  it('returns value unchanged when base currency is empty/undefined', () => {
    expect(convertToBase(100, 'ARS', undefined, fxRates)).toBe(100);
    expect(convertToBase(100, 'ARS', null, fxRates)).toBe(100);
  });

  it('rebases ARS → USD using provided FX rate', () => {
    // 1415 ARS at rate 0.000707 USD/ARS = ~1.0 USD
    const usd = convertToBase(1415, 'ARS', 'USD', fxRates);
    expect(usd).toBeCloseTo(1.0, 4);
  });

  it('rebases EUR → USD', () => {
    // 100 EUR at rate 1.08 = 108 USD
    expect(convertToBase(100, 'EUR', 'USD', fxRates)).toBeCloseTo(108, 4);
  });

  it('returns value unchanged + warns when FX rate is missing for source', () => {
    // No JPY in fxRates — fallback returns value as-is (graceful degradation)
    const result = convertToBase(100, 'JPY', 'USD', fxRates);
    expect(result).toBe(100);
  });

  it('returns value unchanged when rate is non-finite or non-positive', () => {
    const bad = [
      { currency: 'XXX', rate: 0 },
      { currency: 'YYY', rate: -1 },
      { currency: 'ZZZ', rate: NaN },
    ];
    expect(convertToBase(100, 'XXX', 'USD', bad)).toBe(100);
    expect(convertToBase(100, 'YYY', 'USD', bad)).toBe(100);
    expect(convertToBase(100, 'ZZZ', 'USD', bad)).toBe(100);
  });

  it('returns 0 when value is non-finite', () => {
    expect(convertToBase(NaN, 'ARS', 'USD', fxRates)).toBe(0);
    expect(convertToBase(Infinity, 'ARS', 'USD', fxRates)).toBe(0);
  });

  it('handles empty/missing fxRates list', () => {
    expect(convertToBase(100, 'ARS', 'USD', null)).toBe(100);
    expect(convertToBase(100, 'ARS', 'USD', undefined)).toBe(100);
    expect(convertToBase(100, 'ARS', 'USD', [])).toBe(100);
  });
});

// ── Issue #111 (skolodi follow-up) — resource-currency-aware rollup ──────
//
// The contributor's real data (Prueba_2.csv): project BASE = ARS, an
// additional USD currency @ 1415, and a position whose metadata.currency
// is UNSET but whose resource is priced in USD. The position total was
// built from Σ(r.qty×r.rate) with no FX, so the section subtotal AND the
// per-position resource subtotal summed a USD resource as if it were ARS
// ("1 USD = 1 ARS"). This block pins the fix in both grid code paths.
describe('resourceAwareTotalInBase - resource-currency rebase', () => {
  // FX semantics: rate = base units per 1 unit of the foreign currency.
  // Base ARS, so USD rate 1415 means 1 USD = 1415 ARS.
  const fx = [{ currency: 'USD', rate: 1415 }];

  it('Prueba_2: pos 0040 - USD resource in an ARS project converts', () => {
    // qty 2, one USD resource @ 25000 → stored total 50000 (raw).
    const pos = {
      total: 50000,
      quantity: 2,
      metadata: {
        resources: [
          {
            name: 'Recurso_1',
            type: 'operator',
            unit: 'HH',
            quantity: 1,
            unit_rate: 25000,
            total: 25000,
            currency: 'USD',
          },
        ],
      },
    };
    // 50000 USD × 1415 = 70_750_000 ARS — NOT the buggy raw 50000.
    expect(resourceAwareTotalInBase(pos, 'ARS', fx)).toBeCloseTo(70_750_000, 2);
  });

  it('per-unit resource subtotal converts (the 25.000,00 ARS cell)', () => {
    // The resource subtotal row shows Σ(per-unit r.qty×r.rate) in base.
    const pos = {
      total: 25000,
      quantity: 1,
      metadata: {
        resources: [
          { name: 'R', quantity: 1, unit_rate: 25000, total: 25000, currency: 'USD' },
        ],
      },
    };
    expect(resourceAwareTotalInBase(pos, 'ARS', fx)).toBeCloseTo(25000 * 1415, 2);
  });

  it('mixed resource currencies - only the foreign part converts', () => {
    const pos = {
      total: 26000,
      quantity: 1,
      metadata: {
        resources: [
          { name: 'A', quantity: 1, unit_rate: 25000, currency: 'USD' },
          { name: 'B', quantity: 1, unit_rate: 1000, currency: 'ARS' },
        ],
      },
    };
    // 25000×1415 (USD) + 1000 (already ARS) = 35_376_000
    expect(resourceAwareTotalInBase(pos, 'ARS', fx)).toBeCloseTo(
      25000 * 1415 + 1000,
      2,
    );
  });

  it('no foreign resource currency → stored total used as-is', () => {
    const pos = {
      total: 50000,
      quantity: 2,
      metadata: {
        resources: [{ name: 'R', quantity: 1, unit_rate: 25000, currency: 'ARS' }],
      },
    };
    // All ARS → no conversion, keep the exact stored total.
    expect(resourceAwareTotalInBase(pos, 'ARS', fx)).toBe(50000);
  });

  it('non-resource position keeps the verified #131 metadata.currency path', () => {
    const pos = {
      total: 500,
      quantity: 50,
      metadata: { currency: 'USD' },
    };
    // 500 USD × 1415 = 707500 ARS via the position-level path.
    expect(resourceAwareTotalInBase(pos, 'ARS', fx)).toBeCloseTo(707500, 2);
  });

  it('missing FX rate degrades visibly (never zeroes the row)', () => {
    const pos = {
      total: 25000,
      quantity: 1,
      metadata: {
        resources: [{ name: 'R', quantity: 1, unit_rate: 25000, currency: 'GBP' }],
      },
    };
    // GBP has no rate — summed in its own units, not dropped.
    expect(resourceAwareTotalInBase(pos, 'ARS', fx)).toBe(25000);
  });
});

// ── Founder bug — Unit Rate editable iff no CONTRIBUTING resource ────────
//
// "If you change the Unit Rate on a position WITHOUT resources, it does not
// change. It only changes if you add and fill in resource prices." The cause
// was that ANY non-empty resources array (even one of blank / zero-quantity
// rows) was treated as resource-driven, locking the cell. A resource only
// drives the rate when it has a non-zero quantity.
describe('hasContributingResources', () => {
  it('is false for empty / absent / non-array', () => {
    expect(hasContributingResources(undefined)).toBe(false);
    expect(hasContributingResources(null)).toBe(false);
    expect(hasContributingResources([])).toBe(false);
    expect(hasContributingResources('nope')).toBe(false);
  });

  it('is false when every resource has a zero / blank / non-numeric quantity', () => {
    // The founder's "phantom resources" position — reads as resource-less.
    expect(hasContributingResources([{ quantity: 0, unit_rate: 5 }])).toBe(false);
    expect(hasContributingResources([{ quantity: 0 }, { quantity: 0.0 }])).toBe(false);
    expect(hasContributingResources([{ name: 'blank' }])).toBe(false);
    expect(hasContributingResources([{ quantity: 'abc' }])).toBe(false);
    expect(hasContributingResources(['not-a-dict', { quantity: 0 }])).toBe(false);
  });

  it('is true once a resource carries a non-zero quantity', () => {
    // Non-zero quantity counts even before its price is filled in.
    expect(hasContributingResources([{ quantity: 1, unit_rate: 0 }])).toBe(true);
    expect(hasContributingResources([{ quantity: '2.5', unit_rate: 30 }])).toBe(true);
    expect(hasContributingResources([{ quantity: 0 }, { quantity: 3 }])).toBe(true);
  });
});

// classificationCode — the Code column showed three standards out of eighteen
//
// The grid and the Excel export both rendered a position's item code by
// reading `din276`, `nrm` and `masterformat` and nothing else. Those are the
// three the backend registry calls legacy. Against the shipped demos, nine of
// thirty three had an empty Code cell on every priced line, and eleven
// classification keys present in real demo data could never be rendered at
// all. The country rule sets ask for exactly those codes, so a Hungarian user
// could be told a line has no item code while the column that would show it
// stayed blank.

describe('classificationCode - every standard, not the legacy three', () => {
  it('still reads the three it always read', () => {
    expect(classificationCode({ din276: '331' })).toBe('331');
    expect(classificationCode({ nrm: '2.5.1' })).toBe('2.5.1');
    expect(classificationCode({ masterformat: '03 30 00' })).toBe('03 30 00');
  });

  it.each([
    ['tetelrend', 'MA-04-12-01', 'Hungary'],
    ['gesn', '08-01-003-01', 'Russia'],
    ['gb50500', '010401001001', 'China'],
    ['cpwd', '4.1.2', 'India'],
    ['sinapi', '92759', 'Brazil'],
    ['nbr', '03.02.010', 'Brazil'],
    ['dpgf', '02.1.3', 'France'],
    ['mexico', 'E-071', 'Mexico'],
    ['sbc', '03 30 53', 'Saudi Arabia'],
    ['asaqs', 'B.12', 'South Africa'],
    ['sans1200', 'DB 3.2', 'South Africa'],
  ])('renders a %s code (%s), which is what %s bills carry', (standard, code) => {
    expect(classificationCode({ [standard]: code })).toBe(code);
  });

  it('prefers the project standard when a line carries more than one code', () => {
    // A Brazilian bill carries both, and which one the reader expects is a
    // property of the project, not of the row.
    const brazilian = { sinapi: '92759', nbr: '03.02.010' };
    expect(classificationCode(brazilian, 'nbr')).toBe('03.02.010');
    expect(classificationCode(brazilian, 'sinapi')).toBe('92759');
  });

  it('falls back to the first code on the row when the preferred one is absent', () => {
    // The Brazilian demos declare masterformat as their project standard and
    // classify their lines under sinapi and nbr, so the preference misses and
    // the row still has to render something.
    expect(classificationCode({ sinapi: '92759', nbr: '03.02.010' }, 'masterformat')).toBe('92759');
    expect(classificationCode({ tetelrend: 'MA-01-11-01' }, 'din276')).toBe('MA-01-11-01');
  });

  it('returns an empty string rather than a stray value for a row with no code', () => {
    expect(classificationCode(undefined)).toBe('');
    expect(classificationCode(null)).toBe('');
    expect(classificationCode({})).toBe('');
    expect(classificationCode({ din276: '' })).toBe('');
    expect(classificationCode({ din276: '   ' })).toBe('');
    expect(classificationCode('331')).toBe('');
    // An array is an object; it is not a classification map.
    expect(classificationCode(['331'])).toBe('');
  });

  it('does not stringify a value that is not a code', () => {
    expect(classificationCode({ din276: true as unknown as string })).toBe('');
    expect(classificationCode({ din276: { code: '331' } as unknown as string })).toBe('');
    // A numeric code is still a code.
    expect(classificationCode({ gesn: 331 as unknown as string })).toBe('331');
  });

  it('skips an empty entry and keeps looking', () => {
    expect(classificationCode({ din276: '', tetelrend: 'MA-06-21-03' })).toBe('MA-06-21-03');
  });
});

// P-56: the Croatian site units existed but sat behind the hundred-odd base
// tokens, so a Croatian estimator scrolling the dropdown never reached them.
describe('getUnitsForLocale - locale trade units lead the list', () => {
  it('offers the Croatian troskovnik units first under hr', () => {
    const units = getUnitsForLocale('hr');
    expect(units.slice(0, 4)).toEqual(['kom', 'kpl', 'pauš.', "m'"]);
  });

  it('keeps the base catalogue, without duplicates', () => {
    const units = getUnitsForLocale('hr-HR');
    expect(units).toContain('m2');
    expect(units).toContain('lsum');
    expect(new Set(units).size).toBe(units.length);
  });

  it('starts with the base catalogue for a locale without trade units', () => {
    expect(getUnitsForLocale('en')[0]).toBe('mm');
  });
});

describe('catalogComponentAmounts', () => {
  it('keeps the source cost and takes the quantity it implies', () => {
    // 0.00 kg listed, 12.84 costed: the quantity column was rounded away.
    const r = catalogComponentAmounts({ quantity: 0, unit_rate: 15107.19, cost: 12.84 });
    expect(r.total).toBe(12.84);
    expect(r.quantity * r.unit_rate).toBeCloseTo(12.84, 9);
  });

  it('leaves a component that already adds up alone', () => {
    expect(catalogComponentAmounts({ quantity: 2, unit_rate: 15, cost: 30 })).toEqual({
      quantity: 2,
      unit_rate: 15,
      total: 30,
    });
  });

  it('prices a component without a cost at quantity x rate, one unit when unset', () => {
    expect(catalogComponentAmounts({ quantity: 3, unit_rate: 4, cost: null }).total).toBe(12);
    expect(catalogComponentAmounts({ unit_rate: 7 })).toEqual({ quantity: 1, unit_rate: 7, total: 7 });
  });
});
