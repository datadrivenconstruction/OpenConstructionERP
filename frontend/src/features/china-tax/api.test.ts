// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';

import { findingKey, toFeeSettings, toProfileFields } from './api';
import type { ProfileFields } from './api';

const base: ProfileFields = {
  tax_method: 'general',
  election_date: '',
  lock_months: null,
  grandfathered: false,
  simplified_basis: 'old_project',
  employer_supplied: true,
  taxpayer_size: 'general',
  permit_start_date: ' ',
  contract_date: '2026-03-10',
  tender_date: null,
  standard_edition: 'gb50500@2024',
  site_subdivision: 'cn-ah',
  site_city: ' Hefei ',
  home_subdivision: '',
  home_city: 'Shanghai',
  notes: '',
};

describe('toProfileFields', () => {
  it('turns blanks into null and normalises regions', () => {
    const out = toProfileFields(base);
    expect(out.election_date).toBeNull();
    expect(out.permit_start_date).toBeNull();
    expect(out.site_subdivision).toBe('CN-AH');
    expect(out.home_subdivision).toBeNull();
    expect(out.site_city).toBe('Hefei');
  });

  it('drops the simplified basis unless the method is simplified', () => {
    expect(toProfileFields(base).simplified_basis).toBeNull();
    expect(toProfileFields({ ...base, tax_method: 'simplified' }).simplified_basis).toBe('old_project');
  });
});

describe('findingKey', () => {
  it('makes a rule id a flat i18n key', () => {
    expect(findingKey('cn.vat_base_pc_sum')).toBe('china_tax.rule.cn_vat_base_pc_sum');
  });
});

describe('toFeeSettings', () => {
  it('drops blank rates and keeps the rest as stated', () => {
    const out = toFeeSettings({ rates: { mgmt: ' 25.71 ', profit: '' }, options: { zone: 'urban' } });
    expect(out.rates).toEqual({ mgmt: '25.71' });
    expect(out.options).toEqual({ zone: 'urban' });
    expect(out.schedule_key).toBeNull();
    expect(out.apply_labour_factor).toBeNull();
    expect(out.labour_includes_social_insurance).toBe(false);
  });
});
