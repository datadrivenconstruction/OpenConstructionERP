import type { CountryTemplate } from '../_shared/templateTypes';

/** Australian ACMM template configuration. */
export const AU_TEMPLATE: CountryTemplate = {
  id: 'au-acmm',
  name: 'Australian ACMM/ANZSMM',
  country: 'Australia',
  countryCode: 'AU',
  currency: 'AUD',
  currencySymbol: 'A$',
  classification: 'ACMM',
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

/** Australian BOQ trade sections based on ACMM/ANZSMM classification. */
export const AU_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: 'A', label: 'Preliminaries' },
  { code: 'B', label: 'Demolition & Site Preparation' },
  { code: 'C', label: 'Earthworks' },
  { code: 'D', label: 'Piling & Special Foundations' },
  { code: 'E', label: 'Concrete & Formwork' },
  { code: 'F', label: 'Structural Steel' },
  { code: 'G', label: 'Masonry' },
  { code: 'H', label: 'Waterproofing & Dampproofing' },
  { code: 'J', label: 'Roofing' },
  { code: 'K', label: 'Windows & External Doors' },
  { code: 'L', label: 'Internal Doors & Frames' },
  { code: 'M', label: 'Metalwork' },
  { code: 'N', label: 'Plastering & Rendering' },
  { code: 'P', label: 'Tiling' },
  { code: 'Q', label: 'Joinery & Cabinetwork' },
  { code: 'R', label: 'Painting & Decorating' },
  { code: 'S', label: 'Floor Coverings' },
  { code: 'T', label: 'Mechanical Services' },
  { code: 'U', label: 'Hydraulic Services' },
  { code: 'V', label: 'Fire Protection' },
  { code: 'W', label: 'Electrical Services' },
  { code: 'X', label: 'External Works & Landscaping' },
];

/** Validate an ACMM trade code. Valid codes are a single uppercase letter optionally followed by digits. */
export function isValidACMMCode(code: string): boolean {
  return /^[A-Z](\d{1,4})?$/.test(code.trim());
}
