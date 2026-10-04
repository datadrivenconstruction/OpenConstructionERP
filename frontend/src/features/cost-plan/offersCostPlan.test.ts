// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it } from 'vitest';
import { offersCostPlan } from './offersCostPlan';

describe('offersCostPlan', () => {
  it('offers the plan on a project classified under NRM, in either spelling', () => {
    expect(offersCostPlan('nrm', [])).toBe(true);
    expect(offersCostPlan('NRM', [])).toBe(true);
    expect(offersCostPlan(' NRM1 ', [])).toBe(true);
  });

  it('offers the plan on a bill whose positions carry NRM codes', () => {
    expect(offersCostPlan('din276', [{ classification: {} }, { classification: { nrm: '2.5.1' } }])).toBe(true);
  });

  it('does not offer it where no position can be allocated', () => {
    expect(offersCostPlan('din276', [{ classification: { din276: '330' } }])).toBe(false);
    expect(offersCostPlan('masterformat', [{ classification: { nrm: '  ' } }, {}])).toBe(false);
    expect(offersCostPlan(undefined, [{ classification: null }])).toBe(false);
  });
});
