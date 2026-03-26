import type { CountryTemplate } from '../_shared/templateTypes';

/** UK NRM template configuration. */
export const NRM_TEMPLATE: CountryTemplate = {
  id: 'uk-nrm',
  name: 'UK NRM 1/2',
  country: 'United Kingdom',
  countryCode: 'GB',
  currency: 'GBP',
  currencySymbol: '\u00a3',
  classification: 'NRM',
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

/** NRM 1 element hierarchy -- Level 1 groups. */
export const NRM_ELEMENTS: { code: string; label: string }[] = [
  { code: '0', label: 'Facilitating works' },
  { code: '1', label: 'Substructure' },
  { code: '2', label: 'Superstructure' },
  { code: '3', label: 'Internal finishes' },
  { code: '4', label: 'Fittings, furnishings and equipment' },
  { code: '5', label: 'Services' },
  { code: '6', label: 'Prefabricated buildings and building units' },
  { code: '7', label: 'Work to existing buildings' },
  { code: '8', label: 'External works' },
  { code: '9', label: "Main contractor's preliminaries" },
  { code: '10', label: "Main contractor's overheads and profit" },
  { code: '11', label: 'Project/design team fees' },
  { code: '12', label: 'Other development/project costs' },
  { code: '13', label: 'Risks' },
  { code: '14', label: 'Inflation' },
];

/** Validate an NRM element code. */
export function isValidNRMCode(code: string): boolean {
  const parts = code.split('.');
  if (parts.length === 0 || parts.length > 4) return false;
  return parts.every((p) => /^\d+$/.test(p));
}
