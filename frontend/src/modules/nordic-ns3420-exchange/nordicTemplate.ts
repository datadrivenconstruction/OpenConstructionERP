import type { CountryTemplate } from '../_shared/templateTypes';

/** Nordic NS 3420 / AMA / V&S BOQ template configuration. */
export const NORDIC_TEMPLATE: CountryTemplate = {
  id: 'nordic-ns3420',
  name: 'NS 3420 / AMA / V&S',
  country: 'Nordic Countries',
  countryCode: 'NO',
  currency: 'NOK',
  currencySymbol: 'kr',
  classification: 'NS3420',
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

/** Nordic BOQ trade sections based on NS 3420 classification. */
export const NORDIC_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: 'A', label: 'Rigging og drift (Site Setup & Operation)' },
  { code: 'B', label: 'Grunnarbeid (Ground Works)' },
  { code: 'C', label: 'Betongarbeid (Concrete)' },
  { code: 'D', label: 'Stalkonstruksjoner (Steel Structures)' },
  { code: 'E', label: 'Trekonstruksjoner (Timber Structures)' },
  { code: 'F', label: 'Muring (Masonry)' },
  { code: 'G', label: 'Taktekking (Roofing)' },
  { code: 'H', label: 'Blikkenslager (Sheet Metal)' },
  { code: 'J', label: 'Tomrer (Carpentry)' },
  { code: 'K', label: 'Malerarbeid (Painting)' },
  { code: 'L', label: 'Gulvlegging (Flooring)' },
  { code: 'M', label: 'VVS-installasjoner (HVAC & Plumbing)' },
  { code: 'N', label: 'Elektroinstallasjoner (Electrical)' },
  { code: 'P', label: 'Heis (Elevators)' },
  { code: 'Q', label: 'Utomhus (External Works)' },
  { code: 'R', label: 'Riving (Demolition)' },
];

/** Validate a Nordic NS 3420 code (letter + digits format). */
export function isValidNordicCode(code: string): boolean {
  const clean = code.trim().toUpperCase();
  // Accepts codes like "A", "C1", "C1.2", "C1.23.4", or "AMA.23.456"
  return /^[A-R]\d{0,2}(\.\d{1,3}){0,3}$/.test(clean) || /^AMA\.\d{2}(\.\d{1,3}){0,2}$/.test(clean);
}
