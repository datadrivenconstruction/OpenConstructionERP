import type { CountryTemplate } from '../_shared/templateTypes';

/** UAE FIDIC/NRM-POMI template configuration. */
export const UAE_TEMPLATE: CountryTemplate = {
  id: 'uae-fidic',
  name: 'UAE FIDIC / NRM-POMI',
  country: 'United Arab Emirates',
  countryCode: 'AE',
  currency: 'AED',
  currencySymbol: '\u062F.\u0625',
  classification: 'NRM/POMI',
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

/**
 * Common UAE BOQ trade sections based on FIDIC/NRM hybrid structure.
 *
 * These sections reflect the typical breakdown used in UAE construction
 * projects (high-rise, infrastructure, hospitality) following FIDIC
 * contract forms and NRM/POMI measurement standards.
 */
export const UAE_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: 'A', label: 'Preliminaries' },
  { code: 'B', label: 'Substructure' },
  { code: 'C', label: 'Concrete Works' },
  { code: 'D', label: 'Masonry' },
  { code: 'E', label: 'Structural Steelwork' },
  { code: 'F', label: 'Waterproofing' },
  { code: 'G', label: 'Roofing' },
  { code: 'H', label: 'Windows & Doors' },
  { code: 'I', label: 'Internal Finishes' },
  { code: 'J', label: 'External Finishes' },
  { code: 'K', label: 'MEP - Mechanical' },
  { code: 'L', label: 'MEP - Electrical' },
  { code: 'M', label: 'MEP - Plumbing' },
  { code: 'N', label: 'Fire Protection' },
  { code: 'O', label: 'Landscaping & External Works' },
  { code: 'P', label: 'Swimming Pools & Water Features' },
  { code: 'Q', label: 'Specialist Works' },
];

/**
 * Validate a UAE BOQ trade section code.
 *
 * Valid formats:
 *  - Single letter: "A", "B", "C" ... "Q"
 *  - Letter + number: "A.01", "C.03.001"
 *  - Numeric ordinal: "01.02.003"
 */
export function isValidUAECode(code: string): boolean {
  if (!code || code.trim().length === 0) return false;

  // Letter-based section code (e.g. "A", "B.01", "C.03.001")
  if (/^[A-Q](\.\d{1,3})*$/.test(code.trim())) return true;

  // Numeric ordinal (e.g. "01", "01.02", "01.02.003")
  const parts = code.trim().split('.');
  if (parts.length === 0 || parts.length > 4) return false;
  return parts.every((p) => /^\d+$/.test(p));
}
