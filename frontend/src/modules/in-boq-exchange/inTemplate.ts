import type { CountryTemplate } from '../_shared/templateTypes';

/** Indian CPWD / IS 1200 / SOR template configuration. */
export const IN_TEMPLATE: CountryTemplate = {
  id: 'in-cpwd',
  name: 'CPWD / IS 1200 / SOR',
  country: 'India',
  countryCode: 'IN',
  currency: 'INR',
  currencySymbol: '\u20B9',
  classification: 'CPWD',
  defaultColumns: {
    ordinal: '0',
    description: '1',
    unit: '2',
    quantity: '3',
    unitRate: '4',
    total: '5',
    classification: '6',
  },
  requiredColumns: ['description', 'quantity'],
  acceptedExtensions: ['.csv', '.tsv', '.xlsx'],
};

/** Indian BOQ trade sections based on CPWD / IS 1200 classification. */
export const IN_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: 'Earthwork' },
  { code: '02', label: 'Concrete Work' },
  { code: '03', label: 'Brick Work & Plastering' },
  { code: '04', label: 'Stone Work' },
  { code: '05', label: 'Wood Work & Joinery' },
  { code: '06', label: 'Steel & Iron Work' },
  { code: '07', label: 'Roofing' },
  { code: '08', label: 'Flooring' },
  { code: '09', label: 'Finishing' },
  { code: '10', label: 'Painting' },
  { code: '11', label: 'Plumbing & Sanitary' },
  { code: '12', label: 'Water Supply' },
  { code: '13', label: 'Electrical Works' },
  { code: '14', label: 'HVAC' },
  { code: '15', label: 'Fire Protection' },
  { code: '16', label: 'External Development' },
  { code: '17', label: 'Demolition & Dismantling' },
];

/** Validate a CPWD section code. Valid codes are two-digit numbers (01-17). */
export function isValidCPWDCode(code: string): boolean {
  return /^(0[1-9]|1[0-7])$/.test(code.trim());
}
