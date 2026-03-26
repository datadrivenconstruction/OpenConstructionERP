import type { CountryTemplate } from '../_shared/templateTypes';

/** Canada BOQ template configuration. */
export const CA_TEMPLATE: CountryTemplate = {
  id: 'ca-masterformat',
  name: 'Canada MasterFormat/CIQS',
  country: 'Canada',
  countryCode: 'CA',
  currency: 'CAD',
  currencySymbol: 'C$',
  classification: 'MasterFormat/CIQS',
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

/** Canadian BOQ trade sections based on MasterFormat adapted for Canada. */
export const CA_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: 'General Requirements' },
  { code: '02', label: 'Site Work & Demolition' },
  { code: '03', label: 'Concrete' },
  { code: '04', label: 'Masonry' },
  { code: '05', label: 'Metals' },
  { code: '06', label: 'Wood & Plastics' },
  { code: '07', label: 'Thermal & Moisture Protection' },
  { code: '08', label: 'Doors & Windows' },
  { code: '09', label: 'Finishes' },
  { code: '10', label: 'Specialties' },
  { code: '11', label: 'Equipment' },
  { code: '12', label: 'Furnishings' },
  { code: '13', label: 'Special Construction' },
  { code: '14', label: 'Conveying Systems' },
  { code: '22', label: 'Mechanical (Plumbing)' },
  { code: '23', label: 'Mechanical (HVAC)' },
  { code: '21', label: 'Fire Protection' },
  { code: '26', label: 'Electrical' },
  { code: '27', label: 'Communications' },
  { code: '32', label: 'Exterior Improvements' },
  { code: '33', label: 'Utilities' },
];

/** Validate a Canadian MasterFormat/CIQS code (xx xx xx format). */
export function isValidCACode(code: string): boolean {
  const clean = code.replace(/\s+/g, ' ').trim();
  // Accepts codes like "03", "03 30", "03 30 00", or CIQS-style "3.1", "3.1.2"
  return /^\d{2}(\s\d{2}){0,2}$/.test(clean) || /^\d+(\.\d+){0,3}$/.test(clean);
}
